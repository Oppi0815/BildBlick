"""Read-only WYSIWYG view for already planned multi-image pages."""

from collections.abc import Callable, Sequence

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPalette, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from printing.layout import ImageSourceInfo, PagePlan
from printing.renderer import MmTransform, render_page_plan


class MultiWysiwygPreview(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent); self.pages: list[PagePlan] = []; self.index = 0; self.image_provider: Callable[[ImageSourceInfo], QImage] = lambda _source: QImage()
        self.setMinimumSize(440, 440); self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_pages(self, pages: Sequence[PagePlan], index: int, image_provider: Callable[[ImageSourceInfo], QImage]) -> None:
        self.pages, self.index, self.image_provider = list(pages), min(max(0, index), max(0, len(pages) - 1)), image_provider; self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self); painter.fillRect(self.rect(), self.palette().color(QPalette.ColorRole.Window))
        if not self.pages: return
        plan = self.pages[self.index]; available = QRectF(self.rect()).adjusted(16, 16, -16, -16)
        scale = min(available.width() / plan.page_size.width_mm, available.height() / plan.page_size.height_mm)
        paper = QRectF(available.center().x() - plan.page_size.width_mm * scale / 2, available.center().y() - plan.page_size.height_mm * scale / 2, plan.page_size.width_mm * scale, plan.page_size.height_mm * scale)
        shadow = self.palette().color(QPalette.ColorRole.Shadow); shadow.setAlpha(45)
        painter.fillRect(paper.translated(3, 3), shadow); painter.fillRect(paper, Qt.GlobalColor.white)
        transform = MmTransform(plan, paper); painter.setPen(QPen(self.palette().color(QPalette.ColorRole.Mid), 1, Qt.PenStyle.DashLine)); painter.drawRect(transform.rect_to_target(plan.printable_rect))
        render_page_plan(painter, plan, paper, self.image_provider)
