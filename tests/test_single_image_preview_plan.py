from pathlib import Path

import pytest

from printing.layout import ImageSourceInfo, PageSizeMm, RectMm
from printing.legacy_single_image import plan_single_image_from_legacy_settings
from printing.printer_geometry import PrinterGeometryMm, preview_printer_geometry_mm


def source() -> ImageSourceInfo:
    return ImageSourceInfo(Path("photo.jpg"), 1800, 1200, 300, 300)


def test_preview_geometry_is_explicit_mm_geometry_not_a_widget_percentage():
    geometry = preview_printer_geometry_mm(PageSizeMm.a4(), "portrait")

    assert geometry.page_size == PageSizeMm(210, 297)
    assert geometry.paint_rect == RectMm(5, 5, 200, 287)
    assert geometry.hardware_margins_mm == pytest.approx((5, 5, 5, 5))


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_preview_and_print_page_plans_match_for_identical_geometry(rotation: int):
    preview_geometry = preview_printer_geometry_mm(PageSizeMm.a4(), "landscape")
    print_geometry = PrinterGeometryMm(
        preview_geometry.page_size, preview_geometry.paint_rect,
    )

    preview_plan = plan_single_image_from_legacy_settings(
        source(), preview_geometry, "fill", True, rotation,
    )
    print_plan = plan_single_image_from_legacy_settings(
        source(), print_geometry, "fill", True, rotation,
    )

    assert preview_plan == print_plan
    image = preview_plan.image_elements[0]
    assert image.rotation_degrees == rotation
    assert image.clip_rect == preview_plan.printable_rect


@pytest.mark.parametrize("mode", ["fit", "original", "10x15", "13x18", "a4"])
def test_preview_plan_uses_the_same_legacy_settings_adapter_as_printing(mode: str):
    geometry = preview_printer_geometry_mm(PageSizeMm.a4(), "portrait")

    plan = plan_single_image_from_legacy_settings(source(), geometry, mode, False)

    assert plan.page_size == geometry.page_size
    assert plan.printable_rect == geometry.paint_rect
    assert plan.image_elements[0].target_rect.x_mm == pytest.approx(geometry.paint_rect.x_mm)
