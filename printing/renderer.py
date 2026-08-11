"""Render an already planned mm-based page without making layout decisions."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter

from printing.layout import ImageSourceInfo, PagePlan, RectMm


class MmTransform:
    """Maps the complete physical paper proportionally into a target rectangle."""

    def __init__(self, page_plan: PagePlan, target_rect: QRectF) -> None:
        if target_rect.width() <= 0 or target_rect.height() <= 0:
            raise ValueError("Das Zielrechteck muss eine positive Größe haben.")
        self.page_plan = page_plan
        self.target_rect = QRectF(target_rect)
        self.scale = min(
            target_rect.width() / page_plan.page_size.width_mm,
            target_rect.height() / page_plan.page_size.height_mm,
        )
        self.page_rect = QRectF(
            target_rect.x() + (target_rect.width() - page_plan.page_size.width_mm * self.scale) / 2,
            target_rect.y() + (target_rect.height() - page_plan.page_size.height_mm * self.scale) / 2,
            page_plan.page_size.width_mm * self.scale,
            page_plan.page_size.height_mm * self.scale,
        )

    def rect_to_target(self, rect: RectMm) -> QRectF:
        return QRectF(
            self.page_rect.x() + rect.x_mm * self.scale,
            self.page_rect.y() + rect.y_mm * self.scale,
            rect.width_mm * self.scale,
            rect.height_mm * self.scale,
        )


def _alignment(value: str) -> Qt.AlignmentFlag:
    values = {
        "left": Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        "right": Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        "center": Qt.AlignmentFlag.AlignCenter,
    }
    return values.get(value, Qt.AlignmentFlag.AlignCenter)


def _elide_mode(value: str) -> Qt.TextElideMode | None:
    return {
        "left": Qt.TextElideMode.ElideLeft,
        "middle": Qt.TextElideMode.ElideMiddle,
        "right": Qt.TextElideMode.ElideRight,
    }.get(value)


def render_page_plan(
    painter: QPainter,
    page_plan: PagePlan,
    target_rect: QRectF,
    image_provider: Callable[[ImageSourceInfo], QImage],
) -> None:
    """Draw a prepared plan. Geometry comes exclusively from ``page_plan``."""

    transform = MmTransform(page_plan, target_rect)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    for element in page_plan.image_elements:
        image = image_provider(element.source)
        if image.isNull():
            continue
        painter.save()
        if element.clip_rect is not None:
            painter.setClipRect(transform.rect_to_target(element.clip_rect))
        target = transform.rect_to_target(element.target_rect)
        if element.rotation_degrees:
            painter.translate(target.center())
            painter.rotate(element.rotation_degrees)
            painter.translate(-target.center())
            normalized_rotation = element.rotation_degrees % 180
            if normalized_rotation:
                target = QRectF(
                    target.center().x() - target.height() / 2,
                    target.center().y() - target.width() / 2,
                    target.height(),
                    target.width(),
                )
        if element.source_crop_rect is None:
            painter.drawImage(target, image)
        else:
            crop = element.source_crop_rect
            painter.drawImage(
                target,
                image,
                QRectF(
                    crop.x * image.width(),
                    crop.y * image.height(),
                    crop.width * image.width(),
                    crop.height * image.height(),
                ),
            )
        painter.restore()
    for element in page_plan.text_elements:
        painter.save()
        font = QFont(painter.font())
        font.setPointSizeF(element.font_size_pt)
        font.setBold(element.bold)
        font.setItalic(element.italic)
        painter.setFont(font)
        painter.setPen(QColor("#111111"))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = transform.rect_to_target(element.rect)
        text = element.text
        elide = _elide_mode(element.elide_policy)
        if elide is not None and "\n" not in text:
            text = painter.fontMetrics().elidedText(text, elide, max(0, round(rect.width())))
        painter.drawText(rect, _alignment(element.alignment), text)
        painter.restore()
    painter.restore()
