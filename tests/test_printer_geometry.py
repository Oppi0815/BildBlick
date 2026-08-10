import pytest
from PySide6.QtCore import QMarginsF, QRectF, QSizeF
from PySide6.QtGui import QPageLayout, QPageSize

from printing.printer_geometry import (
    printer_geometry_mm,
    printer_target_rect_for_painter,
)


class FakePrinter:
    def __init__(self, page_layout: QPageLayout) -> None:
        self._page_layout = page_layout

    def pageLayout(self) -> QPageLayout:
        return self._page_layout


def layout(width: float, height: float, orientation, margins: QMarginsF) -> QPageLayout:
    return QPageLayout(
        QPageSize(QSizeF(width, height), QPageSize.Unit.Millimeter),
        orientation,
        margins,
        QPageLayout.Unit.Millimeter,
    )


def test_printer_geometry_returns_a4_and_hardware_margins_in_mm():
    geometry = printer_geometry_mm(
        FakePrinter(layout(210, 297, QPageLayout.Orientation.Portrait, QMarginsF(5, 6, 7, 8)))
    )
    assert geometry.page_size.width_mm == pytest.approx(210)
    assert geometry.page_size.height_mm == pytest.approx(297)
    assert geometry.paint_rect.x_mm == pytest.approx(5)
    assert geometry.paint_rect.y_mm == pytest.approx(6)
    assert geometry.paint_rect.width_mm == pytest.approx(198)
    assert geometry.paint_rect.height_mm == pytest.approx(283)
    assert geometry.hardware_margins_mm == pytest.approx((5, 6, 7, 8))


def test_printer_geometry_honours_final_landscape_and_custom_paper_layouts():
    landscape = printer_geometry_mm(
        FakePrinter(layout(210, 297, QPageLayout.Orientation.Landscape, QMarginsF()))
    )
    custom = printer_geometry_mm(
        FakePrinter(layout(100, 150, QPageLayout.Orientation.Portrait, QMarginsF()))
    )
    assert (landscape.page_size.width_mm, landscape.page_size.height_mm) == pytest.approx((297, 210))
    assert (custom.page_size.width_mm, custom.page_size.height_mm) == pytest.approx((100, 150))


def test_printer_target_maps_physical_page_around_the_painter_paint_viewport():
    geometry = printer_geometry_mm(
        FakePrinter(layout(210, 297, QPageLayout.Orientation.Portrait, QMarginsF(5, 6, 7, 8)))
    )
    target = printer_target_rect_for_painter(geometry, QRectF(0, 0, 1980, 2830))
    assert target.x() == pytest.approx(-50)
    assert target.y() == pytest.approx(-60)
    assert target.width() == pytest.approx(2100)
    assert target.height() == pytest.approx(2970)
