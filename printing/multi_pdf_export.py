"""Multi-page PDF export using the shared PagePlan renderer."""

from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSizeF
from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPainter, QPdfWriter

from printing.layout import ImageSourceInfo, PagePlan
from printing.pdf_export import ensure_pdf_suffix
from printing.renderer import render_page_plan


def export_multi_page_plan_pdf(path: str | Path, pages: Sequence[PagePlan], image_provider: Callable[[ImageSourceInfo], QImage]) -> Path:
    if not pages:
        raise ValueError("Es gibt keine Druckseiten zum Exportieren.")
    target = ensure_pdf_suffix(path)
    if not target.parent.is_dir():
        raise ValueError("Der Zielordner für die PDF-Datei existiert nicht.")
    writer = QPdfWriter(str(target)); writer.setResolution(300)
    painter = QPainter()
    for index, page in enumerate(pages):
        layout = QPageLayout(QPageSize(QSizeF(page.page_size.width_mm, page.page_size.height_mm), QPageSize.Unit.Millimeter, "BildBlick"), QPageLayout.Orientation.Portrait, QMarginsF())
        writer.setPageLayout(layout)
        if index and not writer.newPage():
            raise RuntimeError("Die nächste PDF-Seite konnte nicht erstellt werden.")
        if not painter.isActive() and not painter.begin(writer):
            raise RuntimeError("Die PDF-Datei konnte nicht geöffnet werden.")
        render_page_plan(painter, page, QRectF(0, 0, writer.width(), writer.height()), image_provider)
    if painter.isActive(): painter.end()
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError("Die PDF-Datei wurde nicht erzeugt.")
    return target
