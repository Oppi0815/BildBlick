"""Screen preview for the single-image WYSIWYG dialog.

The widget owns only screen scaling and chrome.  Every printable object comes
from the supplied PagePlan and is drawn by the shared renderer.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPalette, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from printing.layout import ImageSourceInfo, PagePlan
from printing.renderer import MmTransform, render_page_plan
from i18n import t


class WysiwygPagePreview(QWidget):
    geometryEdited = Signal(object)  # RectMm, deliberately independent of pixels
    centerRequested = Signal()
    HANDLE_SIZE = 10
    MIN_SIZE_MM = 5.0
    SNAP_PIXELS = 7.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.page_plan: PagePlan | None = None
        self.image_provider: Callable[[ImageSourceInfo], QImage] = lambda _source: QImage()
        self.zoom_percent = 0  # 0 means fit to window
        self.lock_aspect_ratio = True
        self._drag_mode: str | None = None
        self._drag_start = None
        self._start_rect = None
        self._guide_lines: tuple[bool, bool] = (False, False)
        self._guide_positions: tuple[float | None, float | None] = (None, None)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(360, 420)

    def set_page_plan(self, page_plan: PagePlan | None, image_provider: Callable[[ImageSourceInfo], QImage]) -> None:
        self.page_plan, self.image_provider = page_plan, image_provider
        self.updateGeometry()
        self.update()

    def set_zoom_percent(self, value: int) -> None:
        self.zoom_percent = value
        self.updateGeometry()
        self.update()

    def set_lock_aspect_ratio(self, locked: bool) -> None:
        self.lock_aspect_ratio = locked

    def _paper_rect(self) -> QRectF | None:
        if self.page_plan is None:
            return None
        available = QRectF(self.rect()).adjusted(20, 20, -20, -20)
        plan = self.page_plan
        if self.zoom_percent:
            scale = self.zoom_percent / 100.0 * 96.0 / 25.4
            paper = QRectF(0, 0, plan.page_size.width_mm * scale, plan.page_size.height_mm * scale)
            paper.moveCenter(available.center())
            return paper
        scale = min(available.width() / plan.page_size.width_mm, available.height() / plan.page_size.height_mm)
        return QRectF(available.center().x() - plan.page_size.width_mm * scale / 2, available.center().y() - plan.page_size.height_mm * scale / 2, plan.page_size.width_mm * scale, plan.page_size.height_mm * scale)

    def _content_rect_mm(self):
        if self.page_plan is None:
            return None
        printable = self.page_plan.printable_rect
        if self.page_plan.text_elements:
            text_top = min(element.rect.y_mm for element in self.page_plan.text_elements)
            return type(printable)(printable.x_mm, printable.y_mm, printable.width_mm, max(0.0, text_top - printable.y_mm - 1.0))
        return printable

    def _image_screen_rect(self) -> QRectF | None:
        if self.page_plan is None or not self.page_plan.image_elements:
            return None
        paper = self._paper_rect()
        return MmTransform(self.page_plan, paper).rect_to_target(self.page_plan.image_elements[0].target_rect) if paper else None

    def _handle_at(self, point) -> str | None:
        rect = self._image_screen_rect()
        if rect is None:
            return None
        handles = {"top_left": rect.topLeft(), "top_right": rect.topRight(), "bottom_left": rect.bottomLeft(), "bottom_right": rect.bottomRight()}
        for name, center in handles.items():
            if QRectF(center.x() - self.HANDLE_SIZE / 2, center.y() - self.HANDLE_SIZE / 2, self.HANDLE_SIZE, self.HANDLE_SIZE).contains(point):
                return name
        return "move" if rect.contains(point) else None

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        mode = self._handle_at(event.position())
        if mode is None or self.page_plan is None:
            return super().mousePressEvent(event)
        self._drag_mode, self._drag_start = mode, event.position()
        self._start_rect = self.page_plan.image_elements[0].target_rect
        self._guide_lines = (False, False)
        self._guide_positions = (None, None)
        self.setCursor(Qt.CursorShape.ClosedHandCursor if mode == "move" else Qt.CursorShape.SizeFDiagCursor)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_mode is None or self._start_rect is None or self.page_plan is None:
            mode = self._handle_at(event.position())
            self.setCursor(Qt.CursorShape.OpenHandCursor if mode == "move" else Qt.CursorShape.SizeFDiagCursor if mode else Qt.CursorShape.ArrowCursor)
            return super().mouseMoveEvent(event)
        paper = self._paper_rect()
        transform = MmTransform(self.page_plan, paper)
        dx = (event.position().x() - self._drag_start.x()) / transform.scale
        dy = (event.position().y() - self._drag_start.y()) / transform.scale
        rect = self._resized_rect(dx, dy) if self._drag_mode != "move" else type(self._start_rect)(self._start_rect.x_mm + dx, self._start_rect.y_mm + dy, self._start_rect.width_mm, self._start_rect.height_mm)
        rect = self._constrain_and_snap(rect, transform.scale)
        self.geometryEdited.emit(rect)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_mode is not None:
            self._drag_mode = self._drag_start = self._start_rect = None
            self._guide_lines = (False, False); self._guide_positions = (None, None); self.setCursor(Qt.CursorShape.ArrowCursor); self.update(); event.accept(); return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._image_screen_rect() and self._image_screen_rect().contains(event.position()):
            self.centerRequested.emit(); event.accept(); return
        super().mouseDoubleClickEvent(event)

    def _resized_rect(self, dx: float, dy: float):
        rect = self._start_rect
        left, top, right, bottom = rect.x_mm, rect.y_mm, rect.right_mm, rect.bottom_mm
        if "left" in self._drag_mode: left += dx
        else: right += dx
        if "top" in self._drag_mode: top += dy
        else: bottom += dy
        width, height = max(self.MIN_SIZE_MM, right - left), max(self.MIN_SIZE_MM, bottom - top)
        if self.lock_aspect_ratio:
            aspect = rect.width_mm / rect.height_mm
            if abs(dx) >= abs(dy): height = width / aspect
            else: width = height * aspect
            if "left" in self._drag_mode: left = right - width
            else: right = left + width
            if "top" in self._drag_mode: top = bottom - height
            else: bottom = top + height
        return type(rect)(left, top, width, height)

    def _constrain_and_snap(self, rect, screen_scale: float):
        bounds = self._content_rect_mm()
        if bounds is None:
            return rect
        width, height = min(rect.width_mm, bounds.width_mm), min(rect.height_mm, bounds.height_mm)
        x = min(max(rect.x_mm, bounds.x_mm), bounds.right_mm - width)
        y = min(max(rect.y_mm, bounds.y_mm), bounds.bottom_mm - height)
        tolerance = self.SNAP_PIXELS / screen_scale
        snap_x = snap_y = False
        guide_x = guide_y = None
        if abs(x - bounds.x_mm) <= tolerance: x, snap_x, guide_x = bounds.x_mm, True, bounds.x_mm
        elif abs((x + width) - bounds.right_mm) <= tolerance: x, snap_x, guide_x = bounds.right_mm - width, True, bounds.right_mm
        elif abs((x + width / 2) - (bounds.x_mm + bounds.width_mm / 2)) <= tolerance: x, snap_x, guide_x = bounds.x_mm + (bounds.width_mm - width) / 2, True, bounds.x_mm + bounds.width_mm / 2
        if abs(y - bounds.y_mm) <= tolerance: y, snap_y, guide_y = bounds.y_mm, True, bounds.y_mm
        elif abs((y + height) - bounds.bottom_mm) <= tolerance: y, snap_y, guide_y = bounds.bottom_mm - height, True, bounds.bottom_mm
        elif abs((y + height / 2) - (bounds.y_mm + bounds.height_mm / 2)) <= tolerance: y, snap_y, guide_y = bounds.y_mm + (bounds.height_mm - height) / 2, True, bounds.y_mm + bounds.height_mm / 2
        self._guide_lines = (snap_x, snap_y)
        self._guide_positions = (guide_x, guide_y)
        return type(rect)(x, y, width, height)

    def sizeHint(self):  # Qt API deliberately returns a QSize-like value.
        from PySide6.QtCore import QSize
        if self.page_plan is not None and self.zoom_percent:
            return QSize(round(self.page_plan.page_size.width_mm * self.zoom_percent / 25.4), round(self.page_plan.page_size.height_mm * self.zoom_percent / 25.4))
        return QSize(600, 760)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().color(QPalette.ColorRole.Window))
        if self.page_plan is None:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, t("Vorschau nicht verfügbar"))
            return
        plan = self.page_plan
        paper = self._paper_rect()
        shadow = self.palette().color(QPalette.ColorRole.Shadow); shadow.setAlpha(45)
        painter.fillRect(paper.translated(4, 5), shadow)
        painter.fillRect(paper, Qt.GlobalColor.white)
        painter.setPen(QPen(self.palette().color(QPalette.ColorRole.Mid), 1))
        painter.drawRect(paper)
        printable = MmTransform(plan, paper).rect_to_target(plan.printable_rect)
        painter.setPen(QPen(self.palette().color(QPalette.ColorRole.Mid), 1, Qt.PenStyle.DashLine))
        painter.drawRect(printable)
        render_page_plan(painter, plan, paper, self.image_provider)
        image_rect = self._image_screen_rect()
        if image_rect:
            painter.setPen(QPen(QColor("#5c7ea5"), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawRect(image_rect)
            painter.setBrush(QColor("#f4f7fa")); painter.setPen(QPen(QColor("#5c7ea5"), 1))
            for point in (image_rect.topLeft(), image_rect.topRight(), image_rect.bottomLeft(), image_rect.bottomRight()):
                painter.drawRect(QRectF(point.x() - self.HANDLE_SIZE / 2, point.y() - self.HANDLE_SIZE / 2, self.HANDLE_SIZE, self.HANDLE_SIZE))
            if any(self._guide_lines):
                bounds = MmTransform(plan, paper).rect_to_target(self._content_rect_mm())
                painter.setPen(QPen(QColor("#7c98b5"), 1, Qt.PenStyle.DotLine))
                if self._guide_lines[0]:
                    x = MmTransform(plan, paper).rect_to_target(type(plan.printable_rect)(self._guide_positions[0], 0, 0, 0)).x()
                    painter.drawLine(x, bounds.top(), x, bounds.bottom())
                if self._guide_lines[1]:
                    y = MmTransform(plan, paper).rect_to_target(type(plan.printable_rect)(0, self._guide_positions[1], 0, 0)).y()
                    painter.drawLine(bounds.left(), y, bounds.right(), y)
