from pathlib import Path

import pytest

from printing.layout import ImageSourceInfo, MarginsMm, PageSizeMm
from printing.planner import plan_multi_image_pages


def sources(count: int) -> list[ImageSourceInfo]:
    return [ImageSourceInfo(Path(f"{index}.jpg"), 1600, 900, 300, 300) for index in range(count)]


def test_mm_grid_planner_keeps_page_count_and_cell_aspect_ratio():
    pages = plan_multi_image_pages(sources(5), PageSizeMm.a4(), MarginsMm(5, 5, 5, 5), 2, 2, 4)
    assert [len(page.image_elements) for page in pages] == [4, 1]
    assert [page.page_number for page in pages] == [1, 2]
    first = pages[0].image_elements[0]
    assert first.target_rect.width_mm / first.target_rect.height_mm == pytest.approx(1600 / 900)
    assert first.target_rect.x_mm >= pages[0].printable_rect.x_mm


def test_mm_grid_planner_rejects_invalid_grid_inputs_and_accepts_empty_images():
    assert plan_multi_image_pages([], PageSizeMm.a4(), MarginsMm(), 2, 2) == []
    with pytest.raises(ValueError):
        plan_multi_image_pages(sources(1), PageSizeMm.a4(), MarginsMm(), 0, 2)
    with pytest.raises(ValueError):
        plan_multi_image_pages(sources(1), PageSizeMm.a4(), MarginsMm(), 2, 2, -1)
from pathlib import Path

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter

from printing.layout import ImageElementPlan, ImageSourceInfo, PagePlan, PageSizeMm, RectMm, TextElementPlan
from printing.renderer import MmTransform, render_page_plan


def source() -> ImageSourceInfo:
    return ImageSourceInfo(Path("photo.jpg"), 100, 50, 300, 300)


def test_transform_keeps_paper_proportions_inside_any_target():
    plan = PagePlan(PageSizeMm.a4(), RectMm(0, 0, 210, 297))
    transform = MmTransform(plan, QRectF(0, 0, 600, 300))
    assert transform.page_rect.height() == 300
    assert transform.page_rect.width() == 300 / 297 * 210
    assert transform.rect_to_target(RectMm(0, 0, 210, 297)) == transform.page_rect


def test_renderer_draws_only_planned_geometry_and_honours_clip_and_text():
    plan = PagePlan(
        PageSizeMm(100, 100),
        RectMm(0, 0, 100, 100),
        (ImageElementPlan(source(), RectMm(-50, 0, 100, 100), clip_rect=RectMm(0, 0, 50, 100)),),
        (TextElementPlan("X", RectMm(50, 50, 50, 40), alignment="center"),),
    )
    canvas = QImage(200, 200, QImage.Format.Format_ARGB32)
    canvas.fill(QColor("white"))
    image = QImage(100, 50, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    painter = QPainter(canvas)
    render_page_plan(painter, plan, QRectF(0, 0, 200, 200), lambda _source: image)
    painter.end()
    assert canvas.pixelColor(25, 50) == QColor("red")
    assert canvas.pixelColor(150, 20) == QColor("white")
