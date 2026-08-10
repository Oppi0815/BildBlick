from pathlib import Path

from PySide6.QtCore import QSize, QSizeF, Qt
from PySide6.QtGui import QColor, QImage, QPageSize, QPainter, QPdfWriter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import bildbetrachter
from bildbetrachter import ImageViewer
from pdf_support import (
    PDF_SCREEN_RENDER_MAX_EDGE,
    PDF_DISPLAY_MIN_RENDER_EDGE,
    pdf_display_target_size,
    load_pdf,
    pdf_page_render_size,
    prepare_pdf_rendered_image,
    render_pdf_page,
    render_pdf_page_with_fallback,
)


def _write_pdf(path: Path, page_sizes: list[QSizeF]) -> None:
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(page_sizes[0], QPageSize.Unit.Point))
    painter = QPainter(writer)
    for index, page_size in enumerate(page_sizes):
        if index:
            writer.newPage()
        painter.drawText(20, 30, f"Seite {index + 1}")
    painter.end()


def _viewer(tmp_path: Path) -> tuple[QApplication, ImageViewer]:
    application = QApplication.instance() or QApplication([])
    viewer = ImageViewer(tmp_path)
    viewer.window.resize(900, 700)
    viewer.window.show()
    application.processEvents()
    return application, viewer


def _open_pdf(viewer: ImageViewer, path: Path) -> None:
    viewer.current_image = path
    viewer._load_current_image()


def test_pdf_portrait_rendering_preserves_page_aspect_ratio(tmp_path: Path):
    application = QApplication.instance() or QApplication([])
    pdf_path = tmp_path / "portrait.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)])

    result = load_pdf(pdf_path)
    image = render_pdf_page(result.document, 0, QSize(240, 160))

    assert result.error is None
    assert image.size() == QSize(80, 160)
    application.processEvents()


def test_pdf_landscape_rendering_preserves_page_aspect_ratio(tmp_path: Path):
    application = QApplication.instance() or QApplication([])
    pdf_path = tmp_path / "landscape.pdf"
    _write_pdf(pdf_path, [QSizeF(400, 200)])

    result = load_pdf(pdf_path)
    image = render_pdf_page(result.document, 0, QSize(160, 240))

    assert result.error is None
    assert image.size() == QSize(160, 80)
    application.processEvents()


def test_pdf_render_and_thumbnail_sizes_fit_without_distortion(tmp_path: Path):
    application = QApplication.instance() or QApplication([])
    pdf_path = tmp_path / "thumbnail.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)])
    document = load_pdf(pdf_path).document

    assert pdf_page_render_size(document, 0, QSize(500, 300)) == QSize(150, 300)
    assert pdf_page_render_size(document, 0, QSize(160, 120)) == QSize(60, 120)
    application.processEvents()


def test_pdf_render_size_has_a_screen_resolution_limit(tmp_path: Path):
    application = QApplication.instance() or QApplication([])
    pdf_path = tmp_path / "large-render.pdf"
    _write_pdf(pdf_path, [QSizeF(400, 200)])
    document = load_pdf(pdf_path).document

    render_size = pdf_page_render_size(document, 0, QSize(12000, 12000))

    assert max(render_size.width(), render_size.height()) == PDF_SCREEN_RENDER_MAX_EDGE
    assert render_size == QSize(PDF_SCREEN_RENDER_MAX_EDGE, PDF_SCREEN_RENDER_MAX_EDGE // 2)
    application.processEvents()


def test_pdf_display_target_uses_a_minimum_resolution_for_invalid_viewports():
    assert pdf_display_target_size(QSize()) == QSize(
        PDF_DISPLAY_MIN_RENDER_EDGE,
        PDF_DISPLAY_MIN_RENDER_EDGE,
    )
    assert pdf_display_target_size(QSize(1, 1)) == QSize(
        PDF_DISPLAY_MIN_RENDER_EDGE,
        PDF_DISPLAY_MIN_RENDER_EDGE,
    )


def test_pdf_first_display_render_is_never_thumbnail_sized(tmp_path: Path):
    application = QApplication.instance() or QApplication([])
    pdf_path = tmp_path / "display-quality.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)])
    document = load_pdf(pdf_path).document

    thumbnail_size = pdf_page_render_size(document, 0, QSize(160, 120))
    display_size = pdf_page_render_size(
        document,
        0,
        pdf_display_target_size(QSize()),
    )

    assert thumbnail_size == QSize(60, 120)
    assert display_size == QSize(900, 1800)
    assert display_size.height() > thumbnail_size.height()
    application.processEvents()


def test_many_pdf_pages_render_without_retaining_all_pages(tmp_path: Path):
    application = QApplication.instance() or QApplication([])
    pdf_path = tmp_path / "many-pages.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)] * 100)
    document = load_pdf(pdf_path).document

    assert document.pageCount() == 100
    for page in (0, 1, 50, 99):
        image = render_pdf_page(document, page, QSize(500, 400))
        assert not image.isNull()
        assert image.width() > 0
        assert image.height() > 0
    application.processEvents()


def test_pdf_render_fallback_retries_once_at_half_the_render_size():
    class FailingOnceDocument:
        def __init__(self):
            self.render_sizes: list[QSize] = []

        def pageCount(self) -> int:
            return 1

        def pagePointSize(self, _page: int) -> QSizeF:
            return QSizeF(200, 400)

        def render(self, _page: int, size: QSize) -> QImage:
            self.render_sizes.append(size)
            if len(self.render_sizes) == 1:
                return QImage()
            return QImage(size, QImage.Format.Format_RGB32)

    document = FailingOnceDocument()
    image = render_pdf_page_with_fallback(document, 0, QSize(800, 800))

    assert not image.isNull()
    assert document.render_sizes == [QSize(400, 800), QSize(200, 400)]


def test_transparent_pdf_render_is_composited_onto_opaque_white():
    rendered = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    rendered.fill(Qt.GlobalColor.transparent)

    prepared = prepare_pdf_rendered_image(rendered)

    assert prepared.format() == QImage.Format.Format_ARGB32_Premultiplied
    assert prepared.pixelColor(1, 1) == QColor(Qt.GlobalColor.white)
    assert prepared.pixelColor(1, 1).alpha() == 255


def test_half_transparent_black_pdf_content_is_composited_not_darkened():
    rendered = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    rendered.fill(QColor(0, 0, 0, 128))

    prepared = prepare_pdf_rendered_image(rendered)
    color = prepared.pixelColor(1, 1)

    assert color.alpha() == 255
    assert 126 <= color.red() <= 128
    assert color.red() == color.green() == color.blue()


def test_opaque_pdf_colors_and_rgb_images_remain_color_correct():
    rendered = QImage(4, 4, QImage.Format.Format_RGB32)
    original_color = QColor(35, 130, 220)
    rendered.fill(original_color)

    prepared = prepare_pdf_rendered_image(rendered)

    assert prepared.pixelColor(1, 1) == original_color
    assert rendered.pixelColor(1, 1) == original_color


def test_argb32_pdf_render_is_made_opaque_without_changing_opaque_pixels():
    rendered = QImage(4, 4, QImage.Format.Format_ARGB32)
    original_color = QColor(210, 80, 40, 255)
    rendered.fill(original_color)

    prepared = prepare_pdf_rendered_image(rendered)

    assert prepared.pixelColor(1, 1) == original_color
    assert prepared.pixelColor(1, 1).alpha() == 255


def test_thumbnail_and_full_view_use_the_same_pdf_image_preparation():
    class TransparentDocument:
        def pageCount(self) -> int:
            return 1

        def pagePointSize(self, _page: int) -> QSizeF:
            return QSizeF(200, 400)

        def render(self, _page: int, size: QSize) -> QImage:
            image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            return image

    document = TransparentDocument()
    thumbnail = render_pdf_page(document, 0, QSize(160, 120))
    full_view = render_pdf_page_with_fallback(document, 0, QSize(800, 600))

    assert thumbnail.pixelColor(0, 0) == QColor(Qt.GlobalColor.white)
    assert full_view.pixelColor(0, 0) == QColor(Qt.GlobalColor.white)


def test_one_page_pdf_hides_navigation(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "one.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)])

    _open_pdf(viewer, pdf_path)

    assert viewer.pdf_page_navigation.isHidden()
    assert viewer.pdf_page_label.text() == "Seite 1 von 1"
    assert not viewer.previous_pdf_page_button.isEnabled()
    assert not viewer.next_pdf_page_button.isEnabled()
    viewer.window.close()
    application.processEvents()


def test_pdf_page_buttons_follow_current_page(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "three-pages.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)] * 3)

    _open_pdf(viewer, pdf_path)
    assert not viewer.pdf_page_navigation.isHidden()
    assert viewer.pdf_page_navigation.parentWidget() is viewer.preview_panel
    assert viewer.previous_pdf_page_button.toolTip() == "Vorherige PDF-Seite"
    assert viewer.next_pdf_page_button.toolTip() == "Nächste PDF-Seite"
    assert viewer.previous_pdf_page_button.accessibleName() == "Vorherige PDF-Seite"
    assert viewer.next_pdf_page_button.accessibleName() == "Nächste PDF-Seite"
    assert not viewer.previous_pdf_page_button.isEnabled()
    assert viewer.next_pdf_page_button.isEnabled()

    viewer.next_pdf_page_button.click()
    assert viewer.pdf_page_label.text() == "Seite 2 von 3"
    assert viewer.previous_pdf_page_button.isEnabled()
    assert viewer.next_pdf_page_button.isEnabled()

    viewer.next_pdf_page_button.click()
    assert viewer.pdf_page_label.text() == "Seite 3 von 3"
    assert viewer.previous_pdf_page_button.isEnabled()
    assert not viewer.next_pdf_page_button.isEnabled()
    viewer.window.close()
    application.processEvents()


def test_pdf_page_index_is_clamped_and_another_pdf_starts_at_page_one(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    first_pdf = tmp_path / "first.pdf"
    second_pdf = tmp_path / "second.pdf"
    _write_pdf(first_pdf, [QSizeF(200, 400)] * 3)
    _write_pdf(second_pdf, [QSizeF(400, 200)] * 2)

    _open_pdf(viewer, first_pdf)
    viewer._pdf_page = 99
    viewer._render_pdf_page()
    assert viewer.pdf_page_label.text() == "Seite 3 von 3"

    _open_pdf(viewer, second_pdf)
    assert viewer.pdf_page_label.text() == "Seite 1 von 2"
    viewer.window.close()
    application.processEvents()


def test_failed_pdf_page_render_keeps_the_visible_page_index(tmp_path: Path, monkeypatch):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "fallback.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)] * 3)
    _open_pdf(viewer, pdf_path)

    monkeypatch.setattr(
        bildbetrachter,
        "render_pdf_page_with_fallback",
        lambda *_args: QImage(),
    )
    viewer._change_pdf_page(1)

    assert viewer._pdf_page == 0
    assert viewer.pdf_page_label.text() == "Seite 1 von 3"
    assert viewer.image_label.text() == "Die PDF-Seite konnte nicht gerendert werden"
    viewer.window.close()
    application.processEvents()


def test_pdf_quality_refresh_rerenders_only_when_the_current_render_is_too_small(
    tmp_path: Path, monkeypatch
):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "quality-refresh.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)])
    _open_pdf(viewer, pdf_path)
    rendered_pages: list[tuple[int | None, bool]] = []

    monkeypatch.setattr(
        viewer,
        "_render_pdf_page",
        lambda page, schedule_quality_refresh: rendered_pages.append(
            (page, schedule_quality_refresh)
        ),
    )
    viewer._pdf_render_size = QSize(60, 120)
    viewer._refresh_pdf_render_quality()
    assert rendered_pages == [(0, False)]

    rendered_pages.clear()
    viewer._pdf_render_size = QSize(3600, 3600)
    viewer._refresh_pdf_render_quality()
    assert rendered_pages == []
    viewer.window.close()
    application.processEvents()


def test_normal_image_hides_pdf_navigation(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "document.pdf"
    image_path = tmp_path / "photo.png"
    _write_pdf(pdf_path, [QSizeF(200, 400)])
    image = QImage(120, 80, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.red)
    assert image.save(str(image_path))

    _open_pdf(viewer, pdf_path)
    _open_pdf(viewer, image_path)

    assert viewer.pdf_page_navigation.isHidden()
    assert viewer.pdf_page_label.text() == ""
    viewer.window.close()
    application.processEvents()


def test_page_shortcuts_use_the_same_navigation_logic(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "shortcuts.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)] * 3)
    _open_pdf(viewer, pdf_path)

    assert viewer.next_pdf_page_action.shortcut() == Qt.Key.Key_PageDown
    assert viewer.previous_pdf_page_action.shortcut() == Qt.Key.Key_PageUp
    viewer.window.activateWindow()
    viewer.image_label.setFocus()
    application.processEvents()
    QTest.keyClick(viewer.window, Qt.Key.Key_PageDown)
    assert viewer.pdf_page_label.text() == "Seite 2 von 3"
    QTest.keyClick(viewer.window, Qt.Key.Key_PageUp)
    assert viewer.pdf_page_label.text() == "Seite 1 von 3"
    viewer.window.close()
    application.processEvents()


def test_fullscreen_hides_thumbnail_container_and_restores_splitters(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    image_path = tmp_path / "fullscreen.png"
    image = QImage(120, 80, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.blue)
    assert image.save(str(image_path))
    _open_pdf(viewer, image_path)
    main_sizes = viewer.splitter.sizes()
    right_sizes = viewer.right_splitter.sizes()

    viewer._enter_fullscreen()
    application.processEvents()
    assert viewer.thumbnail_panel.isHidden()
    assert viewer.directory_panel.isHidden()
    assert viewer.previous_button.isHidden()
    assert not viewer.image_scroll_area.isHidden()

    viewer._leave_fullscreen()
    application.processEvents()
    assert not viewer.thumbnail_panel.isHidden()
    assert not viewer.directory_panel.isHidden()
    assert viewer.splitter.sizes() == main_sizes
    assert viewer.right_splitter.sizes() == right_sizes
    viewer.window.close()
    application.processEvents()


def test_fullscreen_state_is_stable_for_a_pdf(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "fullscreen.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)] * 2)
    _open_pdf(viewer, pdf_path)

    for _ in range(2):
        viewer._enter_fullscreen()
        application.processEvents()
        assert viewer.thumbnail_panel.isHidden()
        assert not viewer.pdf_page_navigation.isHidden()
        viewer._change_pdf_page(1)
        assert viewer.pdf_page_label.text() == "Seite 2 von 2"
        viewer._leave_fullscreen()
        application.processEvents()
        assert not viewer.thumbnail_panel.isHidden()
    viewer.window.close()
    application.processEvents()
