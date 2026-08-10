from pathlib import Path

import pytest

from printing.layout import (
    ImageSourceInfo,
    MarginsMm,
    PageSizeMm,
    RectMm,
    SingleImageLayout,
    SizeMm,
    printable_rect_mm,
)
from printing.planner import DEFAULT_IMAGE_DPI, effective_dpi, original_size_mm, plan_single_image


def image(width: int, height: int, dpi_x: float | None = 300, dpi_y: float | None = 300) -> ImageSourceInfo:
    return ImageSourceInfo(Path("photo.jpg"), width, height, dpi_x, dpi_y)


def test_standard_paper_sizes_and_orientation_are_physical():
    assert PageSizeMm.a4() == PageSizeMm(210, 297)
    assert PageSizeMm.a4("landscape") == PageSizeMm(297, 210)
    assert PageSizeMm.photo_10x15() == PageSizeMm(100, 150)
    assert PageSizeMm.photo_13x18() == PageSizeMm(130, 180)


def test_printable_rect_uses_mm_only_and_validates_margins():
    assert printable_rect_mm(PageSizeMm.a4(), MarginsMm(10, 20, 30, 40)) == RectMm(10, 20, 170, 237)
    assert printable_rect_mm(PageSizeMm.a4(), MarginsMm()) == RectMm(0, 0, 210, 297)
    with pytest.raises(ValueError, match="Druckränder dürfen nicht negativ sein"):
        MarginsMm(-1)
    with pytest.raises(ValueError, match="größer"):
        printable_rect_mm(PageSizeMm.a4(), MarginsMm(120, 0, 100, 0))


def test_user_margins_are_inset_from_an_explicit_hardware_print_area():
    plan = plan_single_image(
        image(100, 100),
        SingleImageLayout(
            PageSizeMm.a4(),
            margins=MarginsMm(2, 3, 4, 5),
            available_rect=RectMm(10, 12, 180, 260),
        ),
    )
    assert plan.printable_rect == RectMm(12, 15, 174, 252)


@pytest.mark.parametrize("width,height", [(1200, 1800), (1800, 1200), (1000, 1000), (6000, 1000), (1000, 6000)])
def test_fit_preserves_aspect_ratio_for_all_image_shapes(width: int, height: int):
    plan = plan_single_image(image(width, height), SingleImageLayout(PageSizeMm.a4(), margins=MarginsMm(10, 10, 10, 10)))
    target = plan.image_elements[0].target_rect
    assert target.width_mm / target.height_mm == pytest.approx(width / height)
    epsilon = 1e-9
    assert target.x_mm >= plan.printable_rect.x_mm - epsilon
    assert target.y_mm >= plan.printable_rect.y_mm - epsilon
    assert target.right_mm <= plan.printable_rect.right_mm + epsilon
    assert target.bottom_mm <= plan.printable_rect.bottom_mm + epsilon


def test_fill_covers_printable_rect_and_uses_clip_without_distortion():
    plan = plan_single_image(image(1600, 900), SingleImageLayout(PageSizeMm.a4(), scale_mode="fill"))
    element = plan.image_elements[0]
    assert element.clip_rect == plan.printable_rect
    assert element.target_rect.width_mm >= plan.printable_rect.width_mm
    assert element.target_rect.height_mm >= plan.printable_rect.height_mm
    assert element.target_rect.width_mm / element.target_rect.height_mm == pytest.approx(1600 / 900)


def test_original_size_uses_valid_dpi_and_a_central_fallback():
    assert original_size_mm(image(3000, 1500, 300, 300)) == SizeMm(254, 127)
    assert original_size_mm(image(720, 720, 72, 72)) == SizeMm(254, 254)
    assert effective_dpi(None) == DEFAULT_IMAGE_DPI
    assert effective_dpi(0) == DEFAULT_IMAGE_DPI
    assert effective_dpi(2000) == DEFAULT_IMAGE_DPI
    assert original_size_mm(image(3000, 3000, None, 0)) == SizeMm(254, 254)


def test_fixed_size_can_lock_or_release_aspect_ratio():
    source = image(1600, 900)
    locked = plan_single_image(source, SingleImageLayout(PageSizeMm.a4(), scale_mode="fixed_size", requested_size=SizeMm(100, 100)))
    unlocked = plan_single_image(source, SingleImageLayout(PageSizeMm.a4(), scale_mode="fixed_size", requested_size=SizeMm(100, 100), lock_aspect_ratio=False))
    assert locked.image_elements[0].target_rect.width_mm == pytest.approx(100)
    assert locked.image_elements[0].target_rect.height_mm == pytest.approx(56.25)
    assert unlocked.image_elements[0].target_rect == RectMm(55, 98.5, 100, 100)


@pytest.mark.parametrize(
    "requested_size",
    [PageSizeMm.photo_10x15(), PageSizeMm.photo_13x18()],
)
def test_photo_format_bounds_are_available_as_fixed_mm_sizes(requested_size: PageSizeMm):
    plan = plan_single_image(
        image(1600, 900),
        SingleImageLayout(
            PageSizeMm.a4(),
            scale_mode="fixed_size",
            requested_size=SizeMm(requested_size.width_mm, requested_size.height_mm),
        ),
    )
    target = plan.image_elements[0].target_rect
    assert target.width_mm <= requested_size.width_mm
    assert target.height_mm <= requested_size.height_mm


@pytest.mark.parametrize(
    ("position", "expected"),
    [("center", (55, 98.5)), ("top_left", (0, 0)), ("bottom_right", (110, 197))],
)
def test_positioning_occurs_inside_printable_area(position: str, expected: tuple[float, float]):
    plan = plan_single_image(
        image(100, 100),
        SingleImageLayout(PageSizeMm.a4(), scale_mode="fixed_size", requested_size=SizeMm(100, 100), position=position),
    )
    target = plan.image_elements[0].target_rect
    assert (target.x_mm, target.y_mm) == pytest.approx(expected)
