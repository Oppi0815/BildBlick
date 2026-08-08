from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColorSpace, QImage, QPainter
from PySide6.QtPdf import QPdfDocument


PDF_EXTENSIONS = {".pdf"}
PDF_SCREEN_RENDER_MAX_EDGE = 3600


@dataclass
class PdfLoadResult:
    document: QPdfDocument | None
    page_count: int
    error: str | None


def load_pdf(path: Path) -> PdfLoadResult:
    document = QPdfDocument()
    error = document.load(str(path))
    if error != QPdfDocument.Error.None_:
        messages = {
            QPdfDocument.Error.FileNotFound: "Die PDF-Datei wurde nicht gefunden.",
            QPdfDocument.Error.InvalidFileFormat: "Die Datei ist keine gültige PDF.",
            QPdfDocument.Error.IncorrectPassword: "Die PDF ist passwortgeschützt.",
            QPdfDocument.Error.UnsupportedSecurityScheme: "Die PDF-Verschlüsselung wird nicht unterstützt.",
        }
        return PdfLoadResult(None, 0, messages.get(error, "Die PDF konnte nicht geöffnet werden."))
    if document.pageCount() < 1:
        return PdfLoadResult(None, 0, "Die PDF enthält keine Seiten.")
    return PdfLoadResult(document, document.pageCount(), None)


def render_pdf_page(document: QPdfDocument, page: int, size: QSize) -> QImage:
    if not 0 <= page < document.pageCount():
        return QImage()
    render_size = pdf_page_render_size(document, page, size)
    if render_size.isEmpty():
        return QImage()
    return prepare_pdf_rendered_image(document.render(page, render_size))


def render_pdf_page_with_fallback(
    document: QPdfDocument, page: int, size: QSize
) -> QImage:
    """Render a page once at the requested size and once smaller on failure."""
    if not 0 <= page < document.pageCount():
        return QImage()
    render_size = pdf_page_render_size(document, page, size)
    if render_size.isEmpty():
        return QImage()
    image = prepare_pdf_rendered_image(document.render(page, render_size))
    if not image.isNull() and image.width() > 0 and image.height() > 0:
        return image
    smaller_size = QSize(
        max(1, render_size.width() // 2),
        max(1, render_size.height() // 2),
    )
    return prepare_pdf_rendered_image(document.render(page, smaller_size))


def prepare_pdf_rendered_image(image: QImage) -> QImage:
    """Composite a rendered PDF page onto opaque white for reliable display."""
    if image.isNull() or image.width() <= 0 or image.height() <= 0:
        return QImage()
    prepared = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    color_space = prepared.colorSpace()
    if color_space.isValid():
        srgb = QColorSpace(QColorSpace.NamedColorSpace.SRgb)
        converted = prepared.convertedToColorSpace(srgb)
        if not converted.isNull():
            prepared = converted
    result = QImage(prepared.size(), QImage.Format.Format_ARGB32_Premultiplied)
    result.fill(Qt.GlobalColor.white)
    painter = QPainter(result)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    painter.drawImage(0, 0, prepared)
    painter.end()
    return result


def pdf_page_render_size(
    document: QPdfDocument, page: int, target_size: QSize
) -> QSize:
    """Return a render size that fits ``target_size`` without distorting a page."""
    if not 0 <= page < document.pageCount() or target_size.isEmpty():
        return QSize()
    page_size = document.pagePointSize(page)
    if page_size.isEmpty():
        return QSize()
    fitted_size = QSize(
        max(1, round(page_size.width())),
        max(1, round(page_size.height())),
    ).scaled(target_size, Qt.AspectRatioMode.KeepAspectRatio)
    longest_edge = max(fitted_size.width(), fitted_size.height())
    if longest_edge <= PDF_SCREEN_RENDER_MAX_EDGE:
        return fitted_size
    return fitted_size.scaled(
        QSize(PDF_SCREEN_RENDER_MAX_EDGE, PDF_SCREEN_RENDER_MAX_EDGE),
        Qt.AspectRatioMode.KeepAspectRatio,
    )
