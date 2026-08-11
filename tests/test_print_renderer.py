from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from printing.layout import (
    ImageElementPlan,
    ImageSourceInfo,
    PagePlan,
    PageSizeMm,
    RectMm,
    TextElementPlan,
)
from printing.renderer import MmTransform, render_page_plan


app = QApplication.instance() or QApplication([])


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
        (
            ImageElementPlan(
                source(), RectMm(-50, 0, 100, 100), clip_rect=RectMm(0, 0, 50, 100)
            ),
        ),
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


def test_renderer_applies_right_angle_rotation_to_the_planned_bounding_rect():
    plan = PagePlan(
        PageSizeMm(100, 100),
        RectMm(0, 0, 100, 100),
        (ImageElementPlan(source(), RectMm(25, 0, 50, 100), rotation_degrees=90),),
    )
    canvas = QImage(200, 200, QImage.Format.Format_ARGB32)
    canvas.fill(QColor("white"))
    image = QImage(100, 50, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    painter = QPainter(canvas)
    render_page_plan(painter, plan, QRectF(0, 0, 200, 200), lambda _source: image)
    painter.end()
    assert canvas.pixelColor(100, 20) == QColor("red")
    assert canvas.pixelColor(20, 100) == QColor("white")


def test_renderer_draws_text_with_dark_print_color_even_if_the_painter_is_light():
    plan = PagePlan(
        PageSizeMm(100, 100),
        RectMm(0, 0, 100, 100),
        text_elements=(TextElementPlan("Hallo", RectMm(10, 10, 80, 20), alignment="center"),),
    )
    canvas = QImage(200, 200, QImage.Format.Format_ARGB32)
    canvas.fill(QColor("white"))
    painter = QPainter(canvas)
    painter.setPen(QColor("white"))
    render_page_plan(painter, plan, QRectF(0, 0, 200, 200), lambda _source: QImage())
    painter.end()

    dark_pixels = []
    for y in range(20, 60):
        for x in range(20, 120):
            color = canvas.pixelColor(x, y)
            if color != QColor("white"):
                dark_pixels.append(color)

    assert dark_pixels, "No text pixels were rendered at all"
    assert any(
        color.red() < 200 and color.green() < 200 and color.blue() < 200
        for color in dark_pixels
    )
