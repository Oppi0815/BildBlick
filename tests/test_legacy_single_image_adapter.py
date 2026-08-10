from pathlib import Path

import pytest
from PySide6.QtCore import QRectF, QSize

import bildbetrachter
from printing.layout import ImageSourceInfo, PageSizeMm, RectMm
from printing.legacy_single_image import (
    rotated_source_info,
    single_image_layout_from_legacy_settings,
)
from printing.planner import plan_single_image


def source(width: int = 1200, height: int = 800) -> ImageSourceInfo:
    return ImageSourceInfo(Path("photo.jpg"), width, height, 300, 300)


def _legacy_rect(mode: str, centered: bool, width: int = 1200, height: int = 800) -> QRectF:
    return bildbetrachter.calculate_print_layout(
        QSize(width, height), QRectF(100, 200, 1900, 2700), mode, 254, 300, centered,
    ).target_rect


@pytest.mark.parametrize("mode", ["fit", "fill", "original", "10x15", "13x18", "a4"])
@pytest.mark.parametrize("centered", [True, False])
def test_legacy_adapter_matches_existing_physical_single_image_layout(mode: str, centered: bool):
    page_size = PageSizeMm(210, 297)
    paint_rect = RectMm(10, 20, 190, 270)
    layout = single_image_layout_from_legacy_settings(page_size, paint_rect, mode, centered)
    plan = plan_single_image(source(), layout)
    old = _legacy_rect("fit" if mode == "a4" else mode, centered)
    target = plan.image_elements[0].target_rect
    assert target.x_mm * 10 == pytest.approx(old.x())
    assert target.y_mm * 10 == pytest.approx(old.y())
    assert target.width_mm * 10 == pytest.approx(old.width())
    assert target.height_mm * 10 == pytest.approx(old.height())


@pytest.mark.parametrize(
    ("rotation", "expected_size"),
    [(0, (1200, 800)), (90, (800, 1200)), (180, (1200, 800)), (270, (800, 1200))],
)
def test_rotation_is_described_once_by_the_page_plan(rotation: int, expected_size: tuple[int, int]):
    rotated = rotated_source_info(source(), rotation)
    assert (rotated.pixel_width, rotated.pixel_height) == expected_size
    plan = plan_single_image(
        rotated,
        single_image_layout_from_legacy_settings(
            PageSizeMm.a4(), RectMm(10, 20, 190, 270), "fit", True,
        ),
        rotation_degrees=rotation,
    )
    assert plan.image_elements[0].rotation_degrees == rotation
    old = _legacy_rect("fit", True, *expected_size)
    target = plan.image_elements[0].target_rect
    assert target.x_mm * 10 == pytest.approx(old.x())
    assert target.y_mm * 10 == pytest.approx(old.y())
    assert target.width_mm * 10 == pytest.approx(old.width())
    assert target.height_mm * 10 == pytest.approx(old.height())
