"""PDF output using exactly the same PagePlan renderer as print preview."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSizeF
from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPainter, QPdfWriter

from printing.layout import ImageSourceInfo, PagePlan
from printing.renderer import render_page_plan


def ensure_pdf_suffix(path: str | Path) -> Path:
    result = Path(path)
    return result if result.suffix.lower() == ".pdf" else result.with_suffix(".pdf")


def export_page_plan_pdf(path: str | Path, page_plan: PagePlan, image_provider: Callable[[ImageSourceInfo], QImage]) -> Path:
    """Write a full-page PDF; unlike printers it has no hardware margins."""
    target = ensure_pdf_suffix(path)
    if not target.parent.is_dir():
        raise ValueError("Der Zielordner für die PDF-Datei existiert nicht.")
    writer = QPdfWriter(str(target))
    writer.setResolution(300)
    page_size = QPageSize(QSizeF(page_plan.page_size.width_mm, page_plan.page_size.height_mm), QPageSize.Unit.Millimeter, "BildBlick")
    writer.setPageLayout(QPageLayout(page_size, QPageLayout.Orientation.Portrait, QMarginsF()))
    painter = QPainter()
    if not painter.begin(writer):
        raise RuntimeError("Die PDF-Datei konnte nicht geöffnet werden.")
    try:
        render_page_plan(painter, page_plan, QRectF(0, 0, writer.width(), writer.height()), image_provider)
    finally:
        painter.end()
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError("Die PDF-Datei wurde nicht erzeugt.")
    return target
