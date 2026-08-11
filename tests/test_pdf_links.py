from pathlib import Path

from PySide6.QtCore import QModelIndex, QPointF, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtPdf import QPdfLinkModel
from PySide6.QtWidgets import QApplication

from bildbetrachter import ImageViewer
from pdf_support import load_pdf


def _write_pdf_with_uri_link(path: Path, url: str = "https://example.org/docs") -> None:
    """Create a minimal PDF containing an actual Link annotation."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Annots [4 0 R] >>",
        (
            b"<< /Type /Annot /Subtype /Link /Rect [10 160 120 190] "
            b"/Border [0 0 0] /A << /S /URI /URI ("
            + url.encode("ascii")
            + b") >> >>"
        ),
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, payload in enumerate(objects, 1):
        offsets.append(len(content))
        content.extend(f"{number} 0 obj\n".encode())
        content.extend(payload)
        content.extend(b"\nendobj\n")
    xref_offset = len(content)
    content.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode())
    content.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    path.write_bytes(content)


class _Link:
    def __init__(self, url: str = "", page: int = -1):
        self._url = QUrl(url)
        self._page = page

    def url(self):
        return self._url

    def page(self):
        return self._page


def _viewer(tmp_path: Path) -> tuple[QApplication, ImageViewer]:
    application = QApplication.instance() or QApplication([])
    viewer = ImageViewer(tmp_path)
    viewer.window.resize(900, 700)
    viewer.window.show()
    application.processEvents()
    return application, viewer


def test_qpdf_link_model_recognizes_an_actual_uri_annotation(tmp_path: Path):
    path = tmp_path / "linked.pdf"
    _write_pdf_with_uri_link(path)
    document = load_pdf(path).document
    model = QPdfLinkModel()
    model.setDocument(document)
    model.setPage(0)

    index = model.index(0, 0)
    link = model.data(index, QPdfLinkModel.Role.Link.value)

    assert model.rowCount(QModelIndex()) == 1
    assert model.data(index, QPdfLinkModel.Role.Rectangle.value).contains(QPointF(20, 20))
    assert model.data(index, QPdfLinkModel.Role.Url.value).toString() == "https://example.org/docs"
    assert model.data(index, QPdfLinkModel.Role.Page.value) == -1
    assert model.data(index, QPdfLinkModel.Role.Location.value) == QPointF()
    # Qt 6.8 reports False for URI links, although URL, rectangle and linkAt
    # prove that the annotation is present.
    assert not link.isValid()
    assert model.linkAt(QPointF(20, 20)).url().toString() == "https://example.org/docs"


def test_widget_to_pdf_mapping_and_hover_use_the_actual_link_model(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    path = tmp_path / "linked.pdf"
    _write_pdf_with_uri_link(path)
    viewer.current_image = path
    viewer._load_current_image()
    application.processEvents()

    page_size = viewer._pdf_document.pagePointSize(0)
    # The link begins at (10, 10) points.  Use a point safely inside it.
    click = viewer.image_label.mapToGlobal(
        QPointF(20 / page_size.width() * viewer.image_label.width(), 20 / page_size.height() * viewer.image_label.height()).toPoint()
    )
    assert viewer._pdf_link_at_widget_position(click) is not None
    viewer._update_pdf_link_hover(click)
    assert viewer.image_label.cursor().shape() == Qt.CursorShape.PointingHandCursor
    viewer._update_pdf_link_hover(viewer.image_label.mapToGlobal(viewer.image_label.rect().bottomRight()))
    assert viewer.image_label.cursor().shape() != Qt.CursorShape.PointingHandCursor


def test_safe_external_schemes_open_and_other_schemes_are_blocked(tmp_path: Path, monkeypatch):
    _application, viewer = _viewer(tmp_path)
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)

    assert viewer._open_pdf_link(_Link("https://example.org"))
    assert viewer._open_pdf_link(_Link("http://example.org"))
    assert viewer._open_pdf_link(_Link("mailto:name@example.org?subject=Hello&body=Text"))
    assert not viewer._open_pdf_link(_Link("file:///tmp/nope"))
    assert not viewer._open_pdf_link(_Link("javascript:alert(1)"))
    assert opened == [
        "https://example.org",
        "http://example.org",
        "mailto:name@example.org?subject=Hello&body=Text",
    ]


def test_mailto_url_is_passed_to_open_url_without_losing_recipients_or_parameters(
    tmp_path: Path, monkeypatch
):
    _application, viewer = _viewer(tmp_path)
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    link = _Link(
        "mailto:test@example.org?subject=BildBlick-Test&body=Hallo"
    )

    assert viewer._open_pdf_link(link)
    assert opened == [link.url()]
    assert opened[0].toString() == (
        "mailto:test@example.org?subject=BildBlick-Test&body=Hallo"
    )


def test_mailto_encoding_is_forwarded_to_open_url_unchanged(tmp_path: Path, monkeypatch):
    _application, viewer = _viewer(tmp_path)
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    link = _Link(
        "mailto:max@example.org?subject=Hallo%20Welt&body=Gr%C3%BC%C3%9Fe"
    )

    assert viewer._open_pdf_link(link)
    assert opened[0].path() == "max@example.org"
    assert opened[0].query() == "subject=Hallo Welt&body=Grüße"
    assert bytes(opened[0].toEncoded()).decode() == (
        "mailto:max@example.org?subject=Hallo%20Welt&body=Gr%C3%BC%C3%9Fe"
    )


def test_internal_link_uses_existing_pdf_page_renderer(tmp_path: Path, monkeypatch):
    _application, viewer = _viewer(tmp_path)
    rendered = []
    monkeypatch.setattr(viewer, "_render_pdf_page", lambda page: rendered.append(page) or True)

    assert viewer._open_pdf_link(_Link(page=2))
    assert rendered == [2]
