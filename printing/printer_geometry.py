"""Qt boundary helpers for converting printer geometry to millimetres."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, QSizeF
from PySide6.QtGui import QPageLayout, QPageSize

from printing.layout import Orientation, PageSizeMm, RectMm


@dataclass(frozen=True)
class PrinterGeometryMm:
    """Physical page and hardware-printable area in physical page coordinates."""

    page_size: PageSizeMm
    paint_rect: RectMm

    @property
    def hardware_margins_mm(self) -> tuple[float, float, float, float]:
        """Left, top, right and bottom hardware margins reported by Qt."""

        return (
            self.paint_rect.x_mm,
            self.paint_rect.y_mm,
            self.page_size.width_mm - self.paint_rect.right_mm,
            self.page_size.height_mm - self.paint_rect.bottom_mm,
        )


# A preview has no selected physical printer in Phase 3.  Five millimetres on
# every edge is therefore an intentionally explicit, conservative preview
# default -- it is not a widget-relative visual margin.
DEFAULT_PREVIEW_HARDWARE_MARGIN_MM = 5.0


def configure_printer_page_layout(
    printer,
    page_size: PageSizeMm | None,
    orientation: QPageLayout.Orientation,
) -> None:
    """Apply BildBlick's page setup to ``printer`` before its native dialog.

    ``QPrinter.pageLayout()`` returns a value object in Qt 6.  Change that
    copy and install it again so the platform print dialog receives both the
    selected paper format and orientation.  Existing layout settings, such as
    printer-provided margins, are deliberately retained.
    """

    page_layout = printer.pageLayout()
    if page_size is not None:
        page_layout.setPageSize(
            QPageSize(
                QSizeF(page_size.width_mm, page_size.height_mm),
                QPageSize.Unit.Millimeter,
                "BildBlick",
            )
        )
    page_layout.setOrientation(orientation)
    printer.setPageLayout(page_layout)


def preview_printer_geometry_mm(
    page_size: PageSizeMm,
    orientation: Orientation,
    hardware_margin_mm: float = DEFAULT_PREVIEW_HARDWARE_MARGIN_MM,
) -> PrinterGeometryMm:
    """Create the documented mm geometry used before a printer is selected."""

    if hardware_margin_mm < 0:
        raise ValueError("Der Vorschau-Druckerrand darf nicht negativ sein.")
    oriented_page = page_size.for_orientation(orientation)
    printable_width = oriented_page.width_mm - 2 * hardware_margin_mm
    printable_height = oriented_page.height_mm - 2 * hardware_margin_mm
    if printable_width <= 0 or printable_height <= 0:
        raise ValueError("Die Vorschau-Ränder lassen keine bedruckbare Fläche übrig.")
    return PrinterGeometryMm(
        oriented_page,
        RectMm(
            hardware_margin_mm,
            hardware_margin_mm,
            printable_width,
            printable_height,
        ),
    )


def printer_geometry_mm(printer) -> PrinterGeometryMm:
    """Read the final ``QPrinter`` page/paint geometry without using pixels."""

    page_layout = printer.pageLayout()
    full_rect = page_layout.fullRect(QPageLayout.Unit.Millimeter)
    paint_rect = page_layout.paintRect(QPageLayout.Unit.Millimeter)
    if full_rect.width() <= 0 or full_rect.height() <= 0:
        raise ValueError("Der Drucker meldet kein gültiges Papierformat.")
    if paint_rect.width() <= 0 or paint_rect.height() <= 0:
        raise ValueError("Der Drucker meldet keine bedruckbare Fläche.")
    page_size = PageSizeMm(full_rect.width(), full_rect.height())
    result = RectMm(
        paint_rect.x() - full_rect.x(),
        paint_rect.y() - full_rect.y(),
        paint_rect.width(),
        paint_rect.height(),
    )
    if (
        result.x_mm < 0
        or result.y_mm < 0
        or result.right_mm > page_size.width_mm
        or result.bottom_mm > page_size.height_mm
    ):
        raise ValueError("Die bedruckbare Fläche liegt außerhalb des Papierformats.")
    return PrinterGeometryMm(page_size, result)


def printer_target_rect_for_painter(
    geometry: PrinterGeometryMm, paint_target_rect: QRectF,
) -> QRectF:
    """Map the physical full page into a QPrinter painter's paint viewport.

    With Qt's default ``fullPage=False``, the painter origin is the hardware
    paint area, not the paper corner. The returned rectangle intentionally
    extends beyond that viewport by the hardware margins; consequently the
    plan's ``paint_rect`` maps exactly to the painter's available area.
    """

    if paint_target_rect.width() <= 0 or paint_target_rect.height() <= 0:
        raise ValueError("Das Drucker-Zielrechteck muss positiv sein.")
    if geometry.paint_rect.width_mm <= 0 or geometry.paint_rect.height_mm <= 0:
        raise ValueError("Die Druckergeometrie enthält keine bedruckbare Fläche.")
    scale_x = paint_target_rect.width() / geometry.paint_rect.width_mm
    scale_y = paint_target_rect.height() / geometry.paint_rect.height_mm
    return QRectF(
        paint_target_rect.x() - geometry.paint_rect.x_mm * scale_x,
        paint_target_rect.y() - geometry.paint_rect.y_mm * scale_y,
        geometry.page_size.width_mm * scale_x,
        geometry.page_size.height_mm * scale_y,
    )
