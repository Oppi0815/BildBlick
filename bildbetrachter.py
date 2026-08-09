import hashlib
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from io import BytesIO
from datetime import datetime
from dataclasses import dataclass
from functools import cmp_to_key
from pathlib import Path
from typing import Callable, TypeVar

from PIL import Image as PillowImage, ImageOps
from send2trash import send2trash
from PySide6.QtCore import (
    QDir,
    QEvent,
    QEasingCurve,
    QFile,
    QIODevice,
    QItemSelectionModel,
    QLineF,
    QMimeData,
    QObject,
    QPropertyAnimation,
    QRunnable,
    QSettings,
    QSize,
    QRectF,
    QStandardPaths,
    QCommandLineParser,
    QCommandLineOption,
    QCollator,
    Qt,
    QThreadPool,
    QTimer,
    QSignalBlocker,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QBrush,
    QColor,
    QCursor,
    QDrag,
    QFileOpenEvent,
    QFont,
    QIcon,
    QImage,
    QImageReader,
    QKeySequence,
    QPageLayout,
    QPageSize,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QShortcut,
    QTransform,
)
from PySide6.QtUiTools import QUiLoader
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFileSystemModel,
    QFormLayout,
    QGroupBox,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QProxyStyle,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSizePolicy,
    QSplitter,
    QStyle,
    QStyleOptionMenuItem,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QToolButton,
    QToolTip,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from duplicate_finder import DuplicateFinderDialog
from printing.multi_image_print import (
    MultiImagePrintSettings,
    calculate_multi_image_page,
    draw_multi_print_header,
    draw_multi_print_footer,
    folder_title_from_path,
    grid_for,
    current_print_date_text,
)
from printing.print_profiles import (
    MultiImagePrintProfile,
    create_user_profile,
    delete_user_profile,
    find_matching_profile,
    is_reserved_profile_name,
    load_user_profiles,
    normalize_profile_name,
    overwrite_user_profile,
    save_user_profile,
)
from pdf_support import (
    PDF_EXTENSIONS,
    pdf_display_target_size,
    pdf_page_render_size,
    load_pdf,
    render_pdf_page,
    render_pdf_page_with_fallback,
)


APP_NAME = "BildBlick"
APP_VERSION = "1.14.1"
APP_DESCRIPTION = "Ein schneller und komfortabler Bildbetrachter"

_DialogResult = TypeVar("_DialogResult")


def should_auto_enter_pdf_preview(image_path: Path | None) -> bool:
    """Return whether a direct PDF open should use the macOS-only preview."""
    return (
        sys.platform == "darwin"
        and image_path is not None
        and image_path.suffix.lower() in PDF_EXTENSIONS
    )


def run_without_application_stylesheet(
    callback: Callable[[], _DialogResult],
) -> _DialogResult:
    application = QApplication.instance()
    original_stylesheet = (
        application.styleSheet() if application is not None else ""
    )
    try:
        if application is not None:
            application.setStyleSheet("")
        return callback()
    finally:
        if application is not None:
            application.setStyleSheet(original_stylesheet)

ROOT_DIRECTORY = Path("/")
HOME_DIRECTORY = Path.home()
_pictures_location = QStandardPaths.writableLocation(
    QStandardPaths.StandardLocation.PicturesLocation
)
START_DIRECTORY = Path(_pictures_location) if _pictures_location else HOME_DIRECTORY
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
SUPPORTED_FILE_EXTENSIONS = IMAGE_EXTENSIONS | PDF_EXTENSIONS
THUMBNAIL_SIZE = QSize(160, 120)
THUMBNAIL_GRID_SIZE = QSize(190, 175)
THUMBNAIL_SPACING = 8
THUMBNAIL_MINIMUM = 80
THUMBNAIL_MAXIMUM = 256
THUMBNAIL_STEP = 16
THUMBNAIL_DEFAULT = 160
FOLDER_HISTORY_LIMIT = 50
TOOLTIP_METADATA_VERSION = 3
DIRECTORY_ENTRIES_PER_BATCH = 100
LIST_ITEMS_PER_BATCH = 100
CACHE_DIRECTORY = Path.home() / f".cache/{APP_NAME}/vorschaubilder"
LEGACY_CACHE_DIRECTORY = (
    Path.home() / ".cache/EinfacherBildbetrachter/vorschaubilder"
)
SETTINGS_ORGANIZATION = APP_NAME
SETTINGS_APPLICATION = APP_NAME
LEGACY_SETTINGS_ORGANIZATION = "EinfacherBildbetrachter"
LEGACY_SETTINGS_APPLICATION = "EinfacherBildbetrachter"
LAST_DIRECTORY_KEY = "lastDirectory"
SLIDESHOW_INTERVAL_KEY = "slideshowInterval"
SLIDESHOW_REPEAT_KEY = "slideshowRepeat"
SLIDESHOW_FULLSCREEN_KEY = "slideshowFullscreen"
SLIDESHOW_SELECTED_ONLY_KEY = "slideshow/selectedOnly"
SLIDESHOW_RANDOM_KEY = "slideshow/randomOrder"
SLIDESHOW_METADATA_KEY = "slideshow/showMetadata"
SLIDESHOW_FADE_KEY = "slideshow/softFade"
COLOR_SCHEME_KEY = "colorScheme"
THUMBNAIL_SIZE_KEY = "thumbnailSize"
SHOW_HIDDEN_FILES_KEY = "view/showHiddenFiles"
SORT_CRITERION_KEY = "sortCriterion"
SORT_ASCENDING_KEY = "sortAscending"
EXPORT_WIDTH_KEY = "export/maxWidth"
EXPORT_HEIGHT_KEY = "export/maxHeight"
EXPORT_QUALITY_KEY = "export/jpegQuality"
EXPORT_ENLARGE_KEY = "export/enlargeSmaller"
EXPORT_SUFFIX_KEY = "export/nameSuffix"
EXPORT_DIRECTORY_KEY = "export/lastDirectory"
EXPORT_METADATA_KEY = "export/keepMetadata"
EXPORT_REMOVE_GPS_KEY = "export/removeGps"
PRINT_ORIENTATION_KEY = "print/orientation"
PRINT_ROTATION_KEY = "print/additionalRotation"
PRINT_SIZE_MODE_KEY = "print/sizeMode"
PRINT_CENTERED_KEY = "print/centered"
MULTI_PRINT_SOURCE_KEY = "printing/multi/source"
MULTI_PRINT_ORIENTATION_KEY = "printing/multi/orientation"
MULTI_PRINT_IMAGES_PER_PAGE_KEY = "printing/multi/imagesPerPage"
MULTI_IMAGE_PRINT_TARGET_DPI = 300
MULTI_PRINT_CONTACT_SHEET_KEY = "printing/multi/contactSheet"
MULTI_PRINT_SHOW_FILENAME_KEY = "printing/multi/showFilename"
MULTI_PRINT_SHOW_CAPTURE_DATE_KEY = "printing/multi/showCaptureDate"
MULTI_PRINT_SHOW_PAGE_NUMBER_KEY = "printing/multi/showPageNumber"
MULTI_PRINT_SHOW_HEADER_KEY = "printing/multi/showHeader"
MULTI_PRINT_HEADER_TEXT_KEY = "printing/multi/headerText"
MULTI_PRINT_USE_FOLDER_NAME_AS_TITLE_KEY = "printing/multi/useFolderNameAsTitle"
MULTI_PRINT_SHOW_PRINT_DATE_KEY = "printing/multi/showPrintDate"
MULTI_PRINT_SHOW_FOLDER_IN_FOOTER_KEY = "printing/multi/showFolderInFooter"
MULTI_PRINT_CUSTOM_ROWS_KEY = "printing/multi/customRows"
MULTI_PRINT_CUSTOM_COLUMNS_KEY = "printing/multi/customColumns"
MULTI_PRINT_PAGE_MARGIN_KEY = "printing/multi/pageMarginMm"
MULTI_PRINT_CELL_SPACING_KEY = "printing/multi/cellSpacingMm"
MULTI_PRINT_SPLITTER_SIZES_KEY = "printing/multi/splitterSizes"
MULTI_PRINT_DIALOG_SIZE_KEY = "printing/multi/dialogSize"
SLIDESHOW_INTERVALS = (3, 5, 10, 15)
SORT_CRITERIA = ("name", "recording_date", "modified", "size")
ZOOM_STEP = 1.15
MIN_ZOOM = 0.10
MAX_ZOOM = 8.0
FULLSCREEN_TOOLTIP_DURATION = 3000
ZOOM_INDICATOR_DURATION = 1500
CHECK_ACCENT_COLOR = "#D32F2F"
ZOOM_INDICATOR_STYLESHEET = (
    "QLabel { background-color: rgba(24, 24, 24, 210);"
    " color: #f7f7f7; border: 1px solid rgba(255, 255, 255, 45);"
    " border-radius: 7px; padding: 7px 11px; font-size: 14px;"
    " font-weight: 600; }"
)
FULLSCREEN_TOOLTIP = """←  Vorheriges Bild
→  Nächstes Bild
Esc oder F11  Vollbild beenden
Mausrad  Zoomen
Linke Maustaste ziehen  Bild verschieben"""

COLOR_SCHEMES = {
    "System": None,
    "Hell": {
        "window": "#f4f6f8", "panel": "#ffffff", "preview": "#eef1f4",
        "image": "#202327", "text": "#20242a", "muted": "#6a717b",
        "border": "#c8cdd3", "button": "#ffffff", "hover": "#e7edf4",
        "selection": "#2878c8", "selection_text": "#ffffff",
        "tooltip": "#fffbdc", "tooltip_text": "#20242a",
    },
    "Dunkel": {
        "window": "#20242a", "panel": "#292e35", "preview": "#252a30",
        "image": "#111315", "text": "#edf0f3", "muted": "#aeb5bd",
        "border": "#444b54", "button": "#343a42", "hover": "#424a54",
        "selection": "#3b8edb", "selection_text": "#ffffff",
        "tooltip": "#353b43", "tooltip_text": "#ffffff",
    },
    "Anthrazit": {
        "window": "#1b1d20", "panel": "#272a2f", "preview": "#22252a",
        "image": "#090a0c", "text": "#f1f2f4", "muted": "#adb2b9",
        "border": "#3b4047", "button": "#30343a", "hover": "#3d424a",
        "selection": "#d88932", "selection_text": "#ffffff",
        "tooltip": "#30343a", "tooltip_text": "#ffffff",
    },
    "Warm": {
        "window": "#e8e2d9", "panel": "#f3eee7", "preview": "#ddd5ca",
        "image": "#282522", "text": "#322e29", "muted": "#716960",
        "border": "#b9aea0", "button": "#f5f0e9", "hover": "#ded3c5",
        "selection": "#9a6136", "selection_text": "#ffffff",
        "tooltip": "#fff4d8", "tooltip_text": "#322e29",
    },
}


class SelectionAccentStyle(QProxyStyle):
    """Draws selection indicators consistently, independently of the theme."""

    INDICATOR_SIZE = 18

    def pixelMetric(self, metric, option=None, widget=None) -> int:
        if metric in (
            QStyle.PixelMetric.PM_IndicatorWidth,
            QStyle.PixelMetric.PM_IndicatorHeight,
            QStyle.PixelMetric.PM_ExclusiveIndicatorWidth,
            QStyle.PixelMetric.PM_ExclusiveIndicatorHeight,
        ):
            return self.INDICATOR_SIZE
        return super().pixelMetric(metric, option, widget)

    @staticmethod
    def _indicator_rect(rect) -> QRectF:
        size = min(SelectionAccentStyle.INDICATOR_SIZE, rect.width(), rect.height())
        return QRectF(
            rect.x() + (rect.width() - size) / 2,
            rect.y() + (rect.height() - size) / 2,
            size,
            size,
        )

    @staticmethod
    def _draw_checkmark(painter: QPainter, rect: QRectF, color: QColor) -> None:
        path = QPainterPath()
        path.moveTo(rect.left() + rect.width() * 0.23, rect.center().y())
        path.lineTo(
            rect.left() + rect.width() * 0.43,
            rect.top() + rect.height() * 0.70,
        )
        path.lineTo(
            rect.left() + rect.width() * 0.79,
            rect.top() + rect.height() * 0.29,
        )
        pen = QPen(color, max(2.0, rect.width() * 0.14))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def drawPrimitive(self, element, option, painter, widget=None) -> None:
        if element not in (
            QStyle.PrimitiveElement.PE_IndicatorCheckBox,
            QStyle.PrimitiveElement.PE_IndicatorRadioButton,
        ):
            super().drawPrimitive(element, option, painter, widget)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self._indicator_rect(option.rect).adjusted(1, 1, -1, -1)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        checked = bool(option.state & QStyle.StateFlag.State_On)
        partial = bool(option.state & QStyle.StateFlag.State_NoChange)
        accent = QColor(CHECK_ACCENT_COLOR if enabled else "#8B8B8B")
        if hovered and enabled:
            accent = accent.lighter(110)
        normal_fill = option.palette.color(
            QPalette.ColorRole.Base if enabled else QPalette.ColorRole.Button
        )
        border = accent if checked or partial or hovered else option.palette.color(
            QPalette.ColorRole.Mid
        )
        painter.setPen(QPen(border, 1.5))

        if element == QStyle.PrimitiveElement.PE_IndicatorRadioButton:
            painter.setBrush(normal_fill)
            painter.drawEllipse(rect)
            if checked or partial:
                dot_rect = rect.adjusted(
                    rect.width() * 0.25,
                    rect.height() * 0.25,
                    -rect.width() * 0.25,
                    -rect.height() * 0.25,
                )
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(accent)
                painter.drawEllipse(dot_rect)
        else:
            painter.setBrush(accent if checked or partial else normal_fill)
            painter.drawRoundedRect(rect, 3, 3)
            if checked:
                self._draw_checkmark(painter, rect, QColor("#FFFFFF"))
            elif partial:
                pen = QPen(QColor("#FFFFFF"), max(2.0, rect.width() * 0.14))
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(QLineF(
                    rect.left() + rect.width() * 0.24,
                    rect.center().y(),
                    rect.right() - rect.width() * 0.24,
                    rect.center().y(),
                ))

        if focused:
            focus_rect = rect.adjusted(-2, -2, 2, 2)
            focus_pen = QPen(accent, 1)
            focus_pen.setStyle(Qt.PenStyle.DotLine)
            painter.setPen(focus_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if element == QStyle.PrimitiveElement.PE_IndicatorRadioButton:
                painter.drawEllipse(focus_rect)
            else:
                painter.drawRoundedRect(focus_rect, 4, 4)
        painter.restore()


    def drawControl(self, element, option, painter, widget=None) -> None:
        super().drawControl(element, option, painter, widget)
        if element != QStyle.ControlElement.CE_MenuItem:
            return
        if not isinstance(option, QStyleOptionMenuItem):
            return
        if (
            option.checkType == QStyleOptionMenuItem.CheckType.NotCheckable
            or not option.checked
        ):
            return

        indicator_size = 16
        if option.direction == Qt.LayoutDirection.RightToLeft:
            indicator_x = option.rect.right() - indicator_size - 7
        else:
            indicator_x = option.rect.left() + 7
        indicator_rect = QRectF(
            indicator_x,
            option.rect.y() + (option.rect.height() - indicator_size) / 2,
            indicator_size,
            indicator_size,
        )
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        accent = QColor(CHECK_ACCENT_COLOR if enabled else "#8B8B8B")
        painter.setPen(QPen(accent.darker(115), 1))
        painter.setBrush(accent)
        painter.drawRoundedRect(indicator_rect, 3, 3)
        self._draw_checkmark(painter, indicator_rect, QColor("#FFFFFF"))
        painter.restore()


class ComboPopupItemDelegate(QStyledItemDelegate):
    """Prevents menu check indicators from leaking into combobox popups."""

    def paint(self, painter, option, index) -> None:
        view_option = QStyleOptionViewItem(option)
        view_option.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        super().paint(painter, view_option, index)


def configure_plain_combo_popup(combo: QComboBox, object_name: str) -> None:
    combo.setObjectName(object_name)
    combo.view().setItemDelegate(ComboPopupItemDelegate(combo.view()))
    model = combo.model()
    for row in range(combo.count()):
        model.setData(model.index(row, 0), None, Qt.ItemDataRole.CheckStateRole)


def install_selection_accent_style(application: QApplication) -> None:
    application.setStyle(SelectionAccentStyle(application.style()))


def selection_menu_stylesheet() -> str:
    checked_icon = resource_path("assets/selection-menu-checked.svg").as_posix()
    disabled_icon = resource_path(
        "assets/selection-menu-checked-disabled.svg"
    ).as_posix()
    return f"""
QMenu::indicator:checked {{
    width: 18px; height: 18px;
    image: url("{checked_icon}");
}}
QMenu::indicator:checked:disabled {{
    image: url("{disabled_icon}");
}}
"""


def interface_polish_stylesheet() -> str:
    """Keep the browser-like main window calm across all color schemes."""
    return """
QWidget#centralwidget QWidget#directoryPanel {
    border-right: 1px solid palette(mid);
}
QWidget#centralwidget QLabel#computerLabel {
    font-size: 13px; font-weight: 650;
    padding: 11px 12px 3px 12px;
}
QWidget#centralwidget QLabel#directoryPathLabel {
    padding: 0 12px 7px 12px;
}
QWidget#centralwidget QTreeView {
    border: none; padding: 4px 6px;
}
QWidget#centralwidget QTreeView::item {
    min-height: 24px; border-radius: 5px; padding: 1px 5px;
}
QWidget#centralwidget QListWidget {
    border: none; padding: 8px;
}
QWidget#centralwidget QListWidget::item {
    border-radius: 9px; margin: 2px; padding: 4px;
}
QWidget#centralwidget QPushButton {
    min-height: 26px; border-radius: 6px; padding: 4px 11px;
}
QWidget#centralwidget QToolButton {
    min-height: 22px; border-radius: 5px; padding: 2px 6px;
}
QWidget#centralwidget QWidget#thumbnailSizeControls QToolButton {
    min-height: 16px; max-height: 16px;
    min-width: 18px; max-width: 18px;
    padding: 0;
}
QWidget#centralwidget QWidget#thumbnailSizeControls QPushButton {
    min-height: 18px; max-height: 18px;
    min-width: 22px; max-width: 22px;
    padding: 0; border-radius: 5px;
}
QWidget#centralwidget QWidget#thumbnailSizeControls QLabel#fileNameLabel {
    font-size: 12px; padding: 0 5px;
}
QWidget#centralwidget QWidget#pdfPageNavigation QPushButton {
    min-height: 20px; max-height: 20px;
    min-width: 22px; max-width: 22px;
    padding: 0; border-radius: 5px;
}
QWidget#centralwidget QLabel#pdfPageLabel { padding: 0 4px; }
QMainWindow#MainWindow QStatusBar {
    min-height: 24px; padding: 0 7px;
}
QWidget#centralwidget QSplitter::handle:horizontal { width: 1px; }
QWidget#centralwidget QSplitter::handle:vertical { height: 1px; }
"""


def color_scheme_stylesheet(colors: dict[str, str] | None) -> str:
    if colors is None:
        return selection_menu_stylesheet() + interface_polish_stylesheet()
    return selection_menu_stylesheet() + interface_polish_stylesheet() + f"""
QMainWindow, QWidget#centralwidget {{
    background-color: {colors['window']}; color: {colors['text']};
}}
QWidget#directoryPanel, QWidget#previewPanel {{
    background-color: {colors['panel']}; color: {colors['text']};
}}
QLabel#directoryPathLabel {{ color: {colors['muted']}; }}
QTreeView, QListWidget {{
    background-color: {colors['panel']}; color: {colors['text']};
    border: 1px solid {colors['border']}; outline: 0;
}}
QListWidget#thumbnailList {{ background-color: {colors['preview']}; }}
QTreeView::item:hover, QListWidget::item:hover {{ background-color: {colors['hover']}; }}
QTreeView::item:selected, QListWidget::item:selected,
QTreeView::item:selected:active, QListWidget::item:selected:active,
QTreeView::item:selected:!active, QListWidget::item:selected:!active {{
    background-color: {colors['selection']}; color: {colors['selection_text']};
}}
QScrollArea#imageScrollArea, QLabel#imageLabel {{
    background-color: {colors['image']}; color: {colors['muted']}; border: none;
}}
QLabel {{ color: {colors['text']}; }}
QMenuBar, QMenu {{
    background-color: {colors['panel']}; color: {colors['text']};
    border-color: {colors['border']};
}}
QMenuBar::item:selected, QMenu::item:selected {{
    background-color: {colors['selection']}; color: {colors['selection_text']};
}}
QMenu::item:disabled {{ color: {colors['muted']}; }}
QPushButton {{
    background-color: {colors['button']}; color: {colors['text']};
    border: 1px solid {colors['border']}; border-radius: 4px; padding: 5px 12px;
}}
QPushButton:hover {{ background-color: {colors['hover']}; }}
QPushButton:pressed {{ background-color: {colors['selection']}; color: {colors['selection_text']}; }}
QPushButton:disabled {{ color: {colors['muted']}; }}
QToolButton {{
    background-color: {colors['button']}; color: {colors['text']};
    border: 1px solid {colors['border']}; border-radius: 4px; padding: 2px 6px;
}}
QToolButton:hover {{ background-color: {colors['hover']}; }}
QToolButton:pressed {{
    background-color: {colors['selection']}; color: {colors['selection_text']};
}}
QToolButton:disabled {{ color: {colors['muted']}; }}
QSplitter::handle {{ background-color: {colors['border']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QScrollBar {{ background-color: {colors['panel']}; }}
QStatusBar {{
    background-color: {colors['panel']}; color: {colors['text']};
    border-top: 1px solid {colors['border']};
}}
QStatusBar::item {{ border: none; }}
QToolTip {{
    background-color: {colors['tooltip']}; color: {colors['tooltip_text']};
    border: 1px solid {colors['border']}; padding: 4px;
}}
"""


def message_box_stylesheet(colors: dict[str, str] | None) -> str:
    if colors is None:
        return ""
    return f"""
QMessageBox, QDialog {{
    background-color: {colors['panel']}; color: {colors['text']};
}}
QMessageBox QLabel, QDialog QLabel {{
    background-color: transparent; color: {colors['text']};
}}
QMessageBox QCheckBox, QDialog QCheckBox,
QMessageBox QRadioButton, QDialog QRadioButton {{ color: {colors['text']}; }}
QMessageBox QPushButton, QDialog QPushButton {{
    background-color: {colors['button']}; color: {colors['text']};
    border: 1px solid {colors['border']}; border-radius: 4px;
    min-width: 80px; padding: 5px 12px;
}}
QMessageBox QPushButton:hover, QDialog QPushButton:hover {{
    background-color: {colors['hover']};
}}
QMessageBox QPushButton:pressed, QDialog QPushButton:pressed {{
    background-color: {colors['selection']}; color: {colors['selection_text']};
}}
QMessageBox QPushButton:focus, QDialog QPushButton:focus {{
    border: 2px solid {colors['selection']};
}}
"""


def resource_path(file_name: str) -> Path:
    bundle_directory = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)
    return Path(bundle_directory) / file_name


def fitted_size(source: QSize, target: QSize) -> QSize:
    if not source.isValid() or source.isEmpty():
        return target
    return source.scaled(target, Qt.AspectRatioMode.KeepAspectRatio)


def image_fit_zoom_factor(image: QImage, viewport_size: QSize) -> float:
    return min(
        viewport_size.width() / image.width(),
        viewport_size.height() / image.height(),
    )


def image_size_at_zoom(image: QImage, zoom_factor: float) -> QSize:
    return QSize(
        max(1, round(image.width() * zoom_factor)),
        max(1, round(image.height() * zoom_factor)),
    )


def rotated_display_image(image: QImage, clockwise_degrees: int) -> QImage:
    normalized_degrees = clockwise_degrees % 360
    if normalized_degrees == 0:
        return QImage(image)
    return image.transformed(
        QTransform().rotate(normalized_degrees),
        Qt.TransformationMode.SmoothTransformation,
    )


@dataclass
class PrintLayout:
    target_rect: QRectF
    source_rect: QRectF
    scaled_down: bool
    outside_page: bool
    fills_page: bool


def calculate_print_layout(
    image_size: QSize,
    drawable_rect: QRectF,
    mode: str,
    printer_resolution: int,
    image_dpi: float,
    centered: bool,
) -> PrintLayout:
    width, height = image_size.width(), image_size.height()
    fills_page = mode == "fill"
    if mode == "fill":
        scale = max(drawable_rect.width() / width, drawable_rect.height() / height)
    elif mode == "original":
        scale = printer_resolution / image_dpi
    elif mode in {"10x15", "13x18"}:
        short_side, long_side = (10.0, 15.0) if mode == "10x15" else (13.0, 18.0)
        format_width, format_height = (
            (long_side, short_side)
            if drawable_rect.width() > drawable_rect.height()
            else (short_side, long_side)
        )
        max_width = format_width / 2.54 * printer_resolution
        max_height = format_height / 2.54 * printer_resolution
        scale = min(max_width / width, max_height / height)
    else:
        scale = min(drawable_rect.width() / width, drawable_rect.height() / height)
    target_width, target_height = width * scale, height * scale
    outside_page = target_width > drawable_rect.width() or target_height > drawable_rect.height()
    if mode in {"10x15", "13x18"} and outside_page:
        scale *= min(drawable_rect.width() / target_width, drawable_rect.height() / target_height)
        target_width, target_height = width * scale, height * scale
    x = drawable_rect.x() + (drawable_rect.width() - target_width) / 2.0 if centered else drawable_rect.x()
    y = drawable_rect.y() + (drawable_rect.height() - target_height) / 2.0 if centered else drawable_rect.y()
    target_width = image_size.width() * scale
    target_height = image_size.height() * scale
    return PrintLayout(
        QRectF(x, y, target_width, target_height),
        QRectF(0.0, 0.0, width, height),
        mode in {"10x15", "13x18"} and outside_page,
        outside_page,
        fills_page,
    )


def draw_print_layout(
    painter: QPainter, image: QImage, drawable_rect: QRectF, layout: PrintLayout
) -> None:
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if layout.fills_page:
        painter.save()
        painter.setClipRect(drawable_rect)
        painter.drawImage(layout.target_rect, image)
        painter.restore()
    else:
        painter.drawImage(layout.target_rect, image)


def image_print_dpi(image_path: Path) -> float:
    try:
        with PillowImage.open(image_path) as image:
            dpi = image.info.get("dpi")
        if dpi and len(dpi) >= 2:
            value = (float(dpi[0]) + float(dpi[1])) / 2
            if 30 <= value <= 1200:
                return value
    except (OSError, ValueError, TypeError):
        pass
    return 300.0


def pathlib_name(path: Path) -> str:
    return path.name


def capture_date_text(path: Path) -> str:
    try:
        with PillowImage.open(path) as image:
            exif = image.getexif()
            value = next((exif.get(tag) for tag in (36867, 36868, 306) if exif.get(tag)), None)
        if value:
            for pattern in ("%Y:%m:%d %H:%M:%S", "%Y:%m:%d"):
                try:
                    return datetime.strptime(str(value), pattern).strftime("%d.%m.%Y %H:%M")
                except ValueError:
                    pass
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
    except (OSError, ValueError):
        return ""


def load_multi_print_image(
    path: Path, target_rect: QRectF, printer_resolution: int
) -> QImage:
    """Loads an image no larger than needed for its printed cell."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    original_size = reader.size()
    required_size = QSize(
        max(1, round(target_rect.width() / printer_resolution * MULTI_IMAGE_PRINT_TARGET_DPI)),
        max(1, round(target_rect.height() / printer_resolution * MULTI_IMAGE_PRINT_TARGET_DPI)),
    )
    if original_size.isValid():
        scaled_size = original_size.scaled(
            required_size, Qt.AspectRatioMode.KeepAspectRatio
        )
        if scaled_size.width() < original_size.width() or scaled_size.height() < original_size.height():
            reader.setScaledSize(scaled_size)
    image = reader.read()
    if image.isNull() or not required_size.isValid():
        return image
    if image.width() > required_size.width() or image.height() > required_size.height():
        image = image.scaled(
            required_size, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return image


class MultiImagePrintLayoutError(RuntimeError):
    pass


def normalized_thumbnail_pixels(value: int) -> int:
    bounded = min(THUMBNAIL_MAXIMUM, max(THUMBNAIL_MINIMUM, value))
    steps = round((bounded - THUMBNAIL_MINIMUM) / THUMBNAIL_STEP)
    return THUMBNAIL_MINIMUM + steps * THUMBNAIL_STEP


def is_hidden_path(path: Path) -> bool:
    """Return whether a directory entry is hidden by its own name."""
    return str(path) in (".", "..") or path.name.startswith(".")


def should_show_path(path: Path, show_hidden: bool) -> bool:
    return str(path) not in (".", "..") and (
        show_hidden or not is_hidden_path(path)
    )


def show_hidden_files_value(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def thumbnail_size_slider_maximum() -> int:
    return (THUMBNAIL_MAXIMUM - THUMBNAIL_MINIMUM) // THUMBNAIL_STEP


def thumbnail_size_slider_value(pixels: int) -> int:
    return (normalized_thumbnail_pixels(pixels) - THUMBNAIL_MINIMUM) // THUMBNAIL_STEP


def thumbnail_pixels_from_slider_value(value: int) -> int:
    bounded = min(thumbnail_size_slider_maximum(), max(0, value))
    return THUMBNAIL_MINIMUM + bounded * THUMBNAIL_STEP


def thumbnail_size_for_pixels(pixels: int) -> QSize:
    return QSize(pixels, round(pixels * 0.75))


def thumbnail_grid_size_for_pixels(pixels: int) -> QSize:
    return QSize(pixels + 30, round(pixels * 0.75) + 55)


def thumbnail_cache_name(path: Path, thumbnail_size: QSize = THUMBNAIL_SIZE) -> str:
    file_info = path.stat()
    key_data = "\0".join(
        (
            str(path.resolve(strict=False)),
            str(file_info.st_size),
            str(file_info.st_mtime_ns),
            f"{thumbnail_size.width()}x{thumbnail_size.height()}",
        )
    )
    return hashlib.sha256(key_data.encode("utf-8")).hexdigest() + ".png"


def format_file_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1000 or unit == "TB":
            if unit == "B":
                return f"{size} B"
            return f"{value:.1f} {unit}".replace(".", ",")
        value /= 1000
    return f"{size} B"


def format_date(value: object) -> str | None:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str):
        return None
    try:
        parsed_date = datetime.strptime(value.strip(" \0"), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    return parsed_date.strftime("%d.%m.%Y, %H:%M")


def format_status_date(value: object) -> str | None:
    formatted = format_date(value)
    return formatted.replace(",", "", 1) if formatted is not None else None


def exif_text(value: object) -> str | None:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.strip(" \0").split())
    return cleaned or None


def rational_float(value: object) -> float | None:
    try:
        if isinstance(value, (tuple, list)) and len(value) == 2:
            denominator = float(value[1])
            return float(value[0]) / denominator if denominator else None
        number = float(value)
    except (TypeError, ValueError, OverflowError, ZeroDivisionError):
        return None
    return number if number >= 0 else None


def format_decimal(value: float, maximum_decimals: int = 1) -> str:
    text = f"{value:.{maximum_decimals}f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def format_exposure(value: object) -> str | None:
    seconds = rational_float(value)
    if seconds is None or seconds <= 0:
        return None
    if seconds < 1:
        denominator = max(1, round(1 / seconds))
        if abs(seconds - 1 / denominator) <= max(0.000001, seconds * 0.02):
            return f"1/{denominator} s"
    return f"{format_decimal(seconds, 2)} s"


def compact_camera_name(make_value: object, model_value: object) -> str | None:
    make = exif_text(make_value)
    model = exif_text(model_value)
    if make is not None:
        make = re.sub(
            r"\s+(camera\s+ag|corporation|corp\.?|inc\.?|co\.?\s*,?\s*ltd\.?)$",
            "",
            make,
            flags=re.IGNORECASE,
        ).strip()
        if make.isupper():
            make = make.title()
    if model is not None and model.isupper():
        model = model.title()
    if model is None:
        return make
    if make is None or model.casefold().startswith(make.casefold()):
        return model
    return f"{make} {model}"


def format_lens_specification(value: object) -> str | None:
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        return None
    numbers = [rational_float(entry) for entry in value]
    if numbers[0] is None or numbers[1] is None:
        return None
    focal = format_decimal(numbers[0])
    if abs(numbers[0] - numbers[1]) > 0.01:
        focal += f"–{format_decimal(numbers[1])}"
    result = f"{focal} mm"
    if len(numbers) >= 4 and numbers[2] and numbers[3]:
        aperture = format_decimal(numbers[2])
        if abs(numbers[2] - numbers[3]) > 0.01:
            aperture += f"–{format_decimal(numbers[3])}"
        result += f" f/{aperture}"
    return result


def gps_coordinate(value: object, reference: object) -> float | None:
    if not isinstance(value, (tuple, list)) or len(value) < 3:
        return None
    components = [rational_float(entry) for entry in value[:3]]
    if any(component is None for component in components):
        return None
    coordinate = components[0] + components[1] / 60 + components[2] / 3600
    ref = exif_text(reference)
    if ref is not None and ref.upper() in ("S", "W"):
        coordinate = -coordinate
    return coordinate


def extract_gps(exif) -> tuple[str | None, str | None]:
    try:
        gps = exif.get_ifd(0x8825)
    except Exception:
        gps = {}
    latitude = gps_coordinate(gps.get(2), gps.get(1))
    longitude = gps_coordinate(gps.get(4), gps.get(3))
    if latitude is None or longitude is None:
        return None, None
    latitude_compact = f"{latitude:.5f}".rstrip("0").rstrip(".").replace(".", ",")
    longitude_compact = (
        f"{longitude:.5f}".rstrip("0").rstrip(".").replace(".", ",")
    )
    compact = f"GPS {latitude_compact} / {longitude_compact}"
    latitude_detail = f"{latitude:.6f}".replace(".", ",")
    longitude_detail = f"{longitude:.6f}".replace(".", ",")
    detail = (
        f"Breitengrad: {latitude_detail}°\n"
        f"Längengrad: {longitude_detail}°"
    )
    return compact, detail


def format_iso_value(value: object) -> str | None:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, (list, tuple)):
        for entry in value:
            formatted = format_iso_value(entry)
            if formatted is not None:
                return formatted
        return None
    if isinstance(value, str):
        cleaned = value.strip(" \0")
        if cleaned.casefold().startswith("iso"):
            cleaned = cleaned[3:].lstrip(" :")
        try:
            numeric = float(cleaned.replace(",", "."))
        except ValueError:
            return None
    else:
        try:
            numeric = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
    if not numeric > 0:
        return None
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:g}".replace(".", ",")


def extract_iso_value(exif) -> str | None:
    try:
        exif_ifd = exif.get_ifd(0x8769)
    except Exception:
        exif_ifd = {}
    for metadata in (exif_ifd, exif):
        for tag in (34855, 34865, 34866, 34867):
            try:
                iso_value = format_iso_value(metadata.get(tag))
            except Exception:
                iso_value = None
            if iso_value is not None:
                return iso_value
    return None


def build_image_metadata(path: Path) -> tuple[str, dict[str, str]]:
    lines = [path.name]
    file_info = None
    dimensions = None
    recording_date = None
    iso_value = None
    status_metadata: dict[str, str] = {}

    try:
        file_info = path.stat()
    except OSError:
        pass

    try:
        with PillowImage.open(path) as image:
            dimensions = image.size
            exif = image.getexif()
            try:
                exif_ifd = exif.get_ifd(0x8769)
            except Exception:
                exif_ifd = {}

            def metadata_value(tag: int):
                value = exif_ifd.get(tag)
                return exif.get(tag) if value is None else value

            for tag in (36867, 36868, 306):
                tag_value = metadata_value(tag)
                recording_date = format_date(tag_value)
                if recording_date is not None:
                    status_metadata["recording_time"] = format_status_date(
                        tag_value
                    ) or recording_date.replace(",", "", 1)
                    break
            iso_value = extract_iso_value(exif)
            camera = compact_camera_name(exif.get(271), exif.get(272))
            if camera:
                status_metadata["camera"] = camera
            lens = exif_text(metadata_value(42036))
            if lens is None:
                lens = format_lens_specification(metadata_value(42034))
            if lens is None:
                lens = exif_text(metadata_value(42035))
            if lens:
                status_metadata["lens"] = lens
            exposure = format_exposure(metadata_value(33434))
            if exposure:
                status_metadata["exposure"] = exposure
            aperture = rational_float(metadata_value(33437))
            if aperture and aperture > 0:
                status_metadata["aperture"] = f"f/{format_decimal(aperture)}"
            focal_length = rational_float(metadata_value(37386))
            if focal_length and focal_length > 0:
                status_metadata["focal_length"] = (
                    f"{format_decimal(focal_length)} mm"
                )
            gps_compact, gps_detail = extract_gps(exif)
            if gps_compact:
                status_metadata["gps"] = gps_compact
                status_metadata["gps_detail"] = gps_detail or gps_compact
    except Exception:
        reader_size = QImageReader(str(path)).size()
        if reader_size.isValid():
            dimensions = (reader_size.width(), reader_size.height())

    if dimensions is not None:
        lines.append(f"{dimensions[0]} × {dimensions[1]} Pixel")
    if file_info is not None:
        lines.append(format_file_size(file_info.st_size))
    if recording_date is not None:
        lines.append(f"Aufgenommen: {recording_date}")
    elif file_info is not None:
        changed_date = datetime.fromtimestamp(file_info.st_mtime).strftime(
            "%d.%m.%Y, %H:%M"
        )
        lines.append(f"Geändert: {changed_date}")
    if iso_value is not None:
        lines.append(f"ISO: {iso_value}")
        status_metadata["iso"] = iso_value
    return "\n".join(lines), status_metadata


def build_image_tooltip(path: Path) -> str:
    return build_image_metadata(path)[0]


class ThumbnailSignals(QObject):
    ready = Signal(int, int, QImage, str, object, object)


class ThumbnailTask(QRunnable):
    def __init__(
        self,
        path: Path,
        index: int,
        generation: int,
        metadata_key: tuple[str, int, int, int],
        cached_tooltip: str | None,
        cached_metadata: dict[str, str] | None,
        thumbnail_size: QSize = THUMBNAIL_SIZE,
    ) -> None:
        super().__init__()
        self.path = path
        self.index = index
        self.generation = generation
        self.metadata_key = metadata_key
        self.cached_tooltip = cached_tooltip
        self.cached_metadata = cached_metadata
        self.thumbnail_size = QSize(thumbnail_size)
        self.signals = ThumbnailSignals()

    def run(self) -> None:
        image = QImage()
        tooltip = self.path.name
        metadata: dict[str, str] = {}
        try:
            if self.cached_tooltip is not None and self.cached_metadata is not None:
                tooltip = self.cached_tooltip
                metadata = self.cached_metadata
            else:
                tooltip, metadata = build_image_metadata(self.path)
        except Exception:
            pass
        try:
            image = self._load_or_create_thumbnail()
        except Exception:
            pass
        try:
            self.signals.ready.emit(
                self.generation,
                self.index,
                image,
                tooltip,
                self.metadata_key,
                metadata,
            )
        except RuntimeError:
            pass

    def _load_or_create_thumbnail(self) -> QImage:
        if self.path.suffix.lower() in PDF_EXTENSIONS:
            result = load_pdf(self.path)
            if result.document is None:
                return QImage()
            return render_pdf_page(result.document, 0, self.thumbnail_size)
        cache_name = thumbnail_cache_name(self.path, self.thumbnail_size)
        cache_file = CACHE_DIRECTORY / cache_name

        cached_file = cache_file
        if not cached_file.is_file():
            legacy_cache_file = LEGACY_CACHE_DIRECTORY / cache_name
            if legacy_cache_file.is_file():
                cached_file = legacy_cache_file
        if cached_file.is_file():
            cached_image = QImage(str(cached_file))
            if not cached_image.isNull():
                return cached_image

        reader = QImageReader(str(self.path))
        reader.setAutoTransform(True)
        reader.setScaledSize(fitted_size(reader.size(), self.thumbnail_size))
        image = reader.read()
        if image.isNull():
            return image
        image = image.scaled(
            self.thumbnail_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        temporary_file = None
        try:
            CACHE_DIRECTORY.mkdir(parents=True, exist_ok=True)
            temporary_file = cache_file.with_name(
                f"{cache_file.name}.{threading.get_ident()}.tmp"
            )
            if image.save(str(temporary_file), "PNG"):
                os.replace(temporary_file, cache_file)
        except OSError:
            pass
        finally:
            if temporary_file is not None:
                try:
                    temporary_file.unlink(missing_ok=True)
                except OSError:
                    pass
        return image


def export_target_size(
    source_size: tuple[int, int],
    maximum_width: int,
    maximum_height: int,
    enlarge_smaller: bool,
) -> tuple[int, int]:
    width, height = source_size
    if width <= 0 or height <= 0:
        raise ValueError("Das Bild hat ungültige Abmessungen.")
    scale = min(maximum_width / width, maximum_height / height)
    if not enlarge_smaller:
        scale = min(1.0, scale)
    return max(1, round(width * scale)), max(1, round(height * scale))


def prepare_jpeg_export(
    image_path: Path,
    rotation: int,
    maximum_width: int,
    maximum_height: int,
    enlarge_smaller: bool,
    keep_metadata: bool,
    remove_gps: bool,
) -> tuple[object, dict[str, object]]:
    with PillowImage.open(image_path) as source:
        if bool(getattr(source, "is_animated", False)):
            raise ValueError("Animierte Bilder werden nicht unterstützt.")
        source.load()
        exif = source.getexif() if keep_metadata else None
        icc_profile = source.info.get("icc_profile") if keep_metadata else None
        dpi = source.info.get("dpi") if keep_metadata else None
        image = ImageOps.exif_transpose(source)
        if rotation % 360:
            image = image.rotate(-(rotation % 360), expand=True)
        target_size = export_target_size(
            image.size, maximum_width, maximum_height, enlarge_smaller
        )
        if image.size != target_size:
            image = image.resize(target_size, PillowImage.Resampling.LANCZOS)

        if image.mode in ("RGBA", "LA") or (
            image.mode == "P" and "transparency" in image.info
        ):
            rgba_image = image.convert("RGBA")
            white_background = PillowImage.new("RGB", rgba_image.size, "white")
            white_background.paste(rgba_image, mask=rgba_image.getchannel("A"))
            image = white_background
        elif image.mode != "RGB":
            image = image.convert("RGB")
        else:
            image = image.copy()

    metadata: dict[str, object] = {}
    export_exif = exif if keep_metadata and exif is not None else PillowImage.Exif()
    try:
        export_exif[274] = 1
        if remove_gps and 34853 in export_exif:
            del export_exif[34853]
        metadata["exif"] = export_exif.tobytes()
    except Exception:
        try:
            orientation_exif = PillowImage.Exif()
            orientation_exif[274] = 1
            metadata["exif"] = orientation_exif.tobytes()
        except Exception:
            pass
    if keep_metadata:
        if icc_profile:
            metadata["icc_profile"] = icc_profile
        if dpi:
            metadata["dpi"] = dpi
    return image, metadata


def jpeg_export_options(quality: int) -> dict[str, object]:
    return {
        "format": "JPEG",
        "quality": quality,
        "optimize": True,
        "progressive": True,
    }


class ExportEstimateSignals(QObject):
    finished = Signal(int, object, str)


class ExportEstimateTask(QRunnable):
    def __init__(
        self,
        generation: int,
        paths: list[Path],
        rotations: dict[str, int],
        options: dict[str, object],
    ) -> None:
        super().__init__()
        self.generation = generation
        self.paths = paths
        self.rotations = rotations
        self.options = options
        self.signals = ExportEstimateSignals()

    def run(self) -> None:
        try:
            sample_count = min(10, len(self.paths))
            if sample_count == 0:
                self.signals.finished.emit(self.generation, 0, "")
                return
            if sample_count == 1:
                sample_indices = [0]
            else:
                sample_indices = sorted(
                    {
                        round(index * (len(self.paths) - 1) / (sample_count - 1))
                        for index in range(sample_count)
                    }
                )
            sampled_bytes = 0
            sampled_pixels = 0
            total_pixels = 0
            for index, path in enumerate(self.paths):
                rotation = self.rotations.get(str(path.resolve(strict=False)), 0)
                if index in sample_indices:
                    try:
                        image, metadata = prepare_jpeg_export(
                            path,
                            rotation,
                            int(self.options["width"]),
                            int(self.options["height"]),
                            bool(self.options["enlarge"]),
                            bool(self.options["metadata"]),
                            bool(self.options["remove_gps"]),
                        )
                        buffer = BytesIO()
                        image.save(
                            buffer,
                            **jpeg_export_options(int(self.options["quality"])),
                            **metadata,
                        )
                        pixels = image.width * image.height
                        sampled_pixels += pixels
                        sampled_bytes += buffer.tell()
                        total_pixels += pixels
                    except Exception:
                        continue
                else:
                    try:
                        with PillowImage.open(path) as source:
                            if bool(getattr(source, "is_animated", False)):
                                continue
                            oriented = ImageOps.exif_transpose(source)
                            width, height = oriented.size
                            if rotation % 180:
                                width, height = height, width
                            target_width, target_height = export_target_size(
                                (width, height),
                                int(self.options["width"]),
                                int(self.options["height"]),
                                bool(self.options["enlarge"]),
                            )
                            total_pixels += target_width * target_height
                    except Exception:
                        continue
            estimate = (
                round(total_pixels * sampled_bytes / sampled_pixels)
                if sampled_pixels
                else 0
            )
            self.signals.finished.emit(self.generation, estimate, "")
        except Exception as error:
            self.signals.finished.emit(self.generation, None, str(error))


class ImageExportSignals(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)


class ImageExportTask(QRunnable):
    def __init__(
        self,
        paths: list[Path],
        rotations: dict[str, int],
        destination: Path,
        suffix: str,
        options: dict[str, object],
    ) -> None:
        super().__init__()
        self.paths = paths
        self.rotations = rotations
        self.destination = destination
        self.suffix = suffix
        self.options = options
        self.cancel_event = threading.Event()
        self.signals = ImageExportSignals()

    def cancel(self) -> None:
        self.cancel_event.set()

    def _available_destination(self, source: Path, reserved: set[str]) -> Path:
        base_name = f"{source.stem}{self.suffix}"
        counter = 0
        while True:
            extra = "" if counter == 0 else f"-{counter}"
            candidate = self.destination / f"{base_name}{extra}.jpg"
            candidate_key = candidate.name.casefold()
            if candidate_key not in reserved and not candidate.exists():
                reserved.add(candidate_key)
                return candidate
            counter += 1

    def run(self) -> None:
        successful: list[str] = []
        skipped: list[str] = []
        failures: list[str] = []
        total_size = 0
        try:
            self.destination.mkdir(parents=True, exist_ok=True)
            if not os.access(self.destination, os.W_OK | os.X_OK):
                raise OSError("Der Zielordner ist nicht beschreibbar.")
        except OSError as error:
            self.signals.finished.emit(
                {
                    "successful": successful,
                    "skipped": skipped,
                    "failures": [str(error)],
                    "total_size": 0,
                    "cancelled": False,
                    "destination": str(self.destination),
                }
            )
            return

        reserved: set[str] = set()
        for index, path in enumerate(self.paths, start=1):
            if self.cancel_event.is_set():
                break
            self.signals.progress.emit(index, len(self.paths), path.name)
            temporary_path: Path | None = None
            try:
                rotation = self.rotations.get(str(path.resolve(strict=False)), 0)
                image, metadata = prepare_jpeg_export(
                    path,
                    rotation,
                    int(self.options["width"]),
                    int(self.options["height"]),
                    bool(self.options["enlarge"]),
                    bool(self.options["metadata"]),
                    bool(self.options["remove_gps"]),
                )
                target = self._available_destination(path, reserved)
                with tempfile.NamedTemporaryFile(
                    prefix=f".{target.stem}-",
                    suffix=".jpg",
                    dir=self.destination,
                    delete=False,
                ) as temporary_file:
                    temporary_path = Path(temporary_file.name)
                image.save(
                    temporary_path,
                    **jpeg_export_options(int(self.options["quality"])),
                    **metadata,
                )
                if not temporary_path.is_file() or temporary_path.stat().st_size <= 0:
                    raise OSError("Die temporäre Exportdatei ist leer.")
                if not QFile.rename(str(temporary_path), str(target)):
                    raise OSError(
                        "Die fertige Exportdatei konnte nicht sicher benannt werden."
                    )
                temporary_path = None
                total_size += target.stat().st_size
                successful.append(str(target))
            except ValueError as error:
                skipped.append(f"{path.name}: {error}")
            except Exception as error:
                failures.append(f"{path.name}: {error}")
            finally:
                if temporary_path is not None:
                    try:
                        temporary_path.unlink(missing_ok=True)
                    except OSError:
                        pass
        self.signals.finished.emit(
            {
                "successful": successful,
                "skipped": skipped,
                "failures": failures,
                "total_size": total_size,
                "cancelled": self.cancel_event.is_set(),
                "destination": str(self.destination),
            }
        )


class ImageExportDialog(QDialog):
    PRESETS = (
        ("Benutzerdefiniert", None),
        ("1280 × 720", (1280, 720)),
        ("1600 × 1200", (1600, 1200)),
        ("1920 × 1080", (1920, 1080)),
        ("2560 × 1440", (2560, 1440)),
        ("3840 × 2160", (3840, 2160)),
    )

    def __init__(
        self,
        paths: list[Path],
        rotations: dict[str, int],
        settings: QSettings,
        default_directory: Path,
        colors: dict[str, str],
        open_folder_callback,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.paths = paths
        self.rotations = rotations
        self.settings = settings
        self.default_directory = default_directory
        self.open_folder_callback = open_folder_callback
        self._estimate_generation = 0
        self._updating_preset = False
        self._export_running = False
        self.estimate_task = None
        self.export_task = None
        self.worker_pool = QThreadPool(self)
        self.worker_pool.setMaxThreadCount(2)

        self.setWindowTitle("Bilder verkleinert exportieren")
        self.setMinimumSize(590, 650)
        self.resize(670, 720)
        self.setStyleSheet(message_box_stylesheet(colors))
        main_layout = QVBoxLayout(self)
        heading = QLabel(f"{len(paths)} Bilder ausgewählt", self)
        heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        main_layout.addWidget(heading)

        size_group = QGroupBox("Zielgröße", self)
        size_form = QFormLayout(size_group)
        self.preset_combo = QComboBox(size_group)
        for label, _size in self.PRESETS:
            self.preset_combo.addItem(label)
        size_form.addRow("Voreinstellung:", self.preset_combo)
        size_row = QHBoxLayout()
        self.width_spin = QSpinBox(size_group)
        self.height_spin = QSpinBox(size_group)
        for spin in (self.width_spin, self.height_spin):
            spin.setRange(100, 20000)
            spin.setSuffix(" Pixel")
        self.width_spin.setValue(
            settings.value(EXPORT_WIDTH_KEY, 1920, type=int)
        )
        self.height_spin.setValue(
            settings.value(EXPORT_HEIGHT_KEY, 1080, type=int)
        )
        size_row.addWidget(self.width_spin)
        size_row.addWidget(QLabel("×", size_group))
        size_row.addWidget(self.height_spin)
        size_form.addRow("Maximale Breite × Höhe:", size_row)
        self.enlarge_checkbox = QCheckBox("Kleinere Bilder vergrößern", size_group)
        self.enlarge_checkbox.setChecked(
            settings.value(EXPORT_ENLARGE_KEY, False, type=bool)
        )
        size_form.addRow("", self.enlarge_checkbox)
        main_layout.addWidget(size_group)

        quality_group = QGroupBox("JPEG-Qualität", self)
        quality_layout = QVBoxLayout(quality_group)
        self.quality_label = QLabel(quality_group)
        self.quality_slider = QSlider(Qt.Orientation.Horizontal, quality_group)
        self.quality_slider.setRange(40, 100)
        self.quality_slider.setValue(
            settings.value(EXPORT_QUALITY_KEY, 90, type=int)
        )
        quality_layout.addWidget(self.quality_label)
        quality_layout.addWidget(self.quality_slider)
        quality_layout.addWidget(
            QLabel(
                "70: kleine Dateien · 85: gute Qualität · 90: sehr gute "
                "Qualität · 95: sehr hohe Qualität",
                quality_group,
            )
        )
        main_layout.addWidget(quality_group)

        naming_group = QGroupBox("Dateinamen und Zielordner", self)
        naming_form = QFormLayout(naming_group)
        self.suffix_edit = QLineEdit(
            settings.value(EXPORT_SUFFIX_KEY, "-klein", type=str), naming_group
        )
        naming_form.addRow("Dateinamen-Zusatz:", self.suffix_edit)
        destination_row = QHBoxLayout()
        saved_directory = settings.value(EXPORT_DIRECTORY_KEY, "", type=str)
        suggested_directory = (
            Path(saved_directory).expanduser()
            if saved_directory
            else default_directory / "Export"
        )
        self.destination_edit = QLineEdit(str(suggested_directory), naming_group)
        browse_button = QPushButton("Durchsuchen …", naming_group)
        browse_button.clicked.connect(self._browse_destination)
        destination_row.addWidget(self.destination_edit, 1)
        destination_row.addWidget(browse_button)
        naming_form.addRow("Zielordner:", destination_row)
        main_layout.addWidget(naming_group)

        metadata_group = QGroupBox("Metadaten", self)
        metadata_layout = QVBoxLayout(metadata_group)
        self.metadata_checkbox = QCheckBox(
            "Aufnahmedaten übernehmen", metadata_group
        )
        self.metadata_checkbox.setChecked(
            settings.value(EXPORT_METADATA_KEY, True, type=bool)
        )
        self.gps_checkbox = QCheckBox("GPS-Daten entfernen", metadata_group)
        self.gps_checkbox.setChecked(
            settings.value(EXPORT_REMOVE_GPS_KEY, True, type=bool)
        )
        metadata_layout.addWidget(self.metadata_checkbox)
        metadata_layout.addWidget(self.gps_checkbox)
        main_layout.addWidget(metadata_group)

        estimate_group = QGroupBox("Größenabschätzung", self)
        estimate_layout = QVBoxLayout(estimate_group)
        self.estimate_label = QLabel("Dateigröße wird geschätzt …", estimate_group)
        self.average_label = QLabel("", estimate_group)
        estimate_layout.addWidget(self.estimate_label)
        estimate_layout.addWidget(self.average_label)
        main_layout.addWidget(estimate_group)

        progress_group = QGroupBox("Exportfortschritt", self)
        progress_layout = QVBoxLayout(progress_group)
        self.progress_bar = QProgressBar(progress_group)
        self.progress_bar.setRange(0, len(paths))
        self.progress_label = QLabel("Bereit zum Exportieren", progress_group)
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.progress_label)
        main_layout.addWidget(progress_group)

        buttons = QDialogButtonBox(self)
        self.export_button = buttons.addButton(
            "Exportieren", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.cancel_button = buttons.addButton(
            "Abbrechen", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.cancel_button.setDefault(True)
        self.cancel_button.setFocus()
        self.export_button.clicked.connect(self._start_export)
        self.cancel_button.clicked.connect(self._cancel_or_close)
        main_layout.addWidget(buttons)

        self.estimate_timer = QTimer(self)
        self.estimate_timer.setSingleShot(True)
        self.estimate_timer.setInterval(400)
        self.estimate_timer.timeout.connect(self._start_estimate)
        self.preset_combo.currentIndexChanged.connect(self._preset_changed)
        self.width_spin.valueChanged.connect(self._manual_size_changed)
        self.height_spin.valueChanged.connect(self._manual_size_changed)
        self.quality_slider.valueChanged.connect(self._options_changed)
        self.enlarge_checkbox.toggled.connect(self._options_changed)
        self.metadata_checkbox.toggled.connect(self._options_changed)
        self.gps_checkbox.toggled.connect(self._options_changed)
        self._update_quality_label()
        self._select_matching_preset()
        self._schedule_estimate()

    def _options(self) -> dict[str, object]:
        return {
            "width": self.width_spin.value(),
            "height": self.height_spin.value(),
            "quality": self.quality_slider.value(),
            "enlarge": self.enlarge_checkbox.isChecked(),
            "metadata": self.metadata_checkbox.isChecked(),
            "remove_gps": self.gps_checkbox.isChecked(),
        }

    def _select_matching_preset(self) -> None:
        selected_index = 0
        size = (self.width_spin.value(), self.height_spin.value())
        for index, (_label, preset_size) in enumerate(self.PRESETS):
            if preset_size == size:
                selected_index = index
                break
        self._updating_preset = True
        self.preset_combo.setCurrentIndex(selected_index)
        self._updating_preset = False

    def _preset_changed(self, index: int) -> None:
        if self._updating_preset:
            return
        preset_size = self.PRESETS[index][1]
        if preset_size is None:
            return
        self._updating_preset = True
        self.width_spin.setValue(preset_size[0])
        self.height_spin.setValue(preset_size[1])
        self._updating_preset = False
        self._schedule_estimate()

    def _manual_size_changed(self) -> None:
        if not self._updating_preset:
            self._updating_preset = True
            self.preset_combo.setCurrentIndex(0)
            self._updating_preset = False
        self._schedule_estimate()

    def _options_changed(self) -> None:
        self._update_quality_label()
        self._schedule_estimate()

    def _update_quality_label(self) -> None:
        self.quality_label.setText(
            f"JPEG-Qualität: {self.quality_slider.value()} %"
        )

    def _schedule_estimate(self) -> None:
        self._estimate_generation += 1
        self.estimate_label.setText("Dateigröße wird geschätzt …")
        self.average_label.clear()
        self.estimate_timer.start()

    def _start_estimate(self) -> None:
        generation = self._estimate_generation
        task = ExportEstimateTask(
            generation, self.paths, self.rotations, self._options()
        )
        self.estimate_task = task
        task.signals.finished.connect(self._estimate_finished)
        self.worker_pool.start(task)

    def _estimate_finished(
        self, generation: int, estimated_size: object, error: str
    ) -> None:
        if generation != self._estimate_generation:
            return
        if estimated_size is None:
            self.estimate_label.setText("Größe konnte nicht geschätzt werden.")
            self.estimate_label.setToolTip(error)
            self.average_label.clear()
            return
        size = int(estimated_size)
        self.estimate_label.setText(
            f"Geschätzte Gesamtgröße: ca. {format_file_size(size)}"
        )
        average = round(size / len(self.paths)) if self.paths else 0
        self.average_label.setText(
            f"Durchschnittlich ca. {format_file_size(average)} pro Bild"
        )

    def _browse_destination(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Zielordner auswählen",
            self.destination_edit.text() or str(self.default_directory),
        )
        if directory:
            self.destination_edit.setText(directory)

    def _start_export(self) -> None:
        destination_text = self.destination_edit.text().strip()
        suffix = self.suffix_edit.text().strip()
        if not destination_text:
            self._show_input_error("Bitte wähle einen Zielordner aus.")
            return
        if "/" in suffix or "\0" in suffix:
            self._show_input_error(
                "Der Dateinamen-Zusatz darf weder „/“ noch Nullzeichen enthalten."
            )
            return
        destination = Path(destination_text).expanduser()
        existing_parent = destination
        while not existing_parent.exists() and existing_parent != existing_parent.parent:
            existing_parent = existing_parent.parent
        if not existing_parent.is_dir() or not os.access(
            existing_parent, os.W_OK | os.X_OK
        ):
            self._show_input_error(
                "Der Zielordner kann nicht angelegt oder beschrieben werden."
            )
            return

        self.settings.setValue(EXPORT_WIDTH_KEY, self.width_spin.value())
        self.settings.setValue(EXPORT_HEIGHT_KEY, self.height_spin.value())
        self.settings.setValue(EXPORT_QUALITY_KEY, self.quality_slider.value())
        self.settings.setValue(EXPORT_ENLARGE_KEY, self.enlarge_checkbox.isChecked())
        self.settings.setValue(EXPORT_SUFFIX_KEY, suffix)
        self.settings.setValue(EXPORT_DIRECTORY_KEY, str(destination))
        self.settings.setValue(EXPORT_METADATA_KEY, self.metadata_checkbox.isChecked())
        self.settings.setValue(EXPORT_REMOVE_GPS_KEY, self.gps_checkbox.isChecked())
        self.settings.sync()

        self._export_running = True
        self.export_button.setEnabled(False)
        self.cancel_button.setText("Abbrechen")
        self.progress_bar.setValue(0)
        task = ImageExportTask(
            self.paths,
            self.rotations,
            destination,
            suffix,
            self._options(),
        )
        self.export_task = task
        task.signals.progress.connect(self._export_progress)
        task.signals.finished.connect(self._export_finished)
        self.worker_pool.start(task)

    def _export_progress(self, current: int, total: int, filename: str) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current - 1)
        self.progress_label.setText(f"Bild {current} von {total}: {filename}")

    def _cancel_or_close(self) -> None:
        if self._export_running and self.export_task is not None:
            self.export_task.cancel()
            self.cancel_button.setEnabled(False)
            self.progress_label.setText("Export wird abgebrochen …")
            return
        self.reject()

    def reject(self) -> None:
        if self._export_running:
            self._cancel_or_close()
            return
        super().reject()

    def _export_finished(self, result: dict[str, object]) -> None:
        self._export_running = False
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("Schließen")
        self.export_button.setEnabled(True)
        successful = list(result["successful"])
        skipped = list(result["skipped"])
        failures = list(result["failures"])
        if result["cancelled"]:
            self.progress_label.setText("Export abgebrochen")
        else:
            self.progress_bar.setValue(self.progress_bar.maximum())
            self.progress_label.setText("Export abgeschlossen")
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Bilder verkleinert exportieren")
        dialog.setIcon(QMessageBox.Icon.Information if not failures else QMessageBox.Icon.Warning)
        dialog.setText(
            f"{len(successful)} Bilder wurden erfolgreich exportiert."
        )
        dialog.setInformativeText(
            f"Zielordner: {result['destination']}\n"
            f"Tatsächliche Gesamtgröße: {format_file_size(int(result['total_size']))}\n"
            f"Übersprungen: {len(skipped)}\n"
            f"Fehlgeschlagen: {len(failures)}"
            + ("\nDer Export wurde abgebrochen." if result["cancelled"] else "")
        )
        details = skipped + failures
        if details:
            dialog.setDetailedText("\n".join(details))
        open_button = dialog.addButton(
            "Zielordner öffnen", QMessageBox.ButtonRole.ActionRole
        )
        close_button = dialog.addButton(
            "Schließen", QMessageBox.ButtonRole.RejectRole
        )
        dialog.setDefaultButton(close_button)
        dialog.exec()
        if dialog.clickedButton() is open_button:
            self.open_folder_callback(Path(str(result["destination"])))

    def _show_input_error(self, message: str) -> None:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Bilder verkleinert exportieren")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(message)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.button(QMessageBox.StandardButton.Ok).setText("OK")
        dialog.exec()


class ComparisonImageView(QWidget):
    zoom_changed = Signal(float, float, float)
    pan_changed = Signal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path: Path | None = None
        self.original_image = QImage()
        self._zoom_mode = "fit"
        self._zoom_factor = 1.0
        self._mouse_press_position = None
        self._pan_last_position = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("comparisonScrollArea")
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setWidgetResizable(False)
        self.image_label = QLabel()
        self.image_label.setObjectName("comparisonImageLabel")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.image_label.setMinimumSize(1, 1)
        self.scroll_area.setWidget(self.image_label)
        layout.addWidget(self.scroll_area, 1)

        self.info_label = QLabel()
        self.info_label.setObjectName("comparisonInfoLabel")
        self.info_label.setWordWrap(True)
        self.info_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.info_label)

        self.zoom_indicator = QLabel(self.scroll_area.viewport())
        self.zoom_indicator.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self.zoom_indicator.setStyleSheet(ZOOM_INDICATOR_STYLESHEET)
        self.zoom_indicator.hide()
        self.zoom_indicator_timer = QTimer(self)
        self.zoom_indicator_timer.setSingleShot(True)
        self.zoom_indicator_timer.timeout.connect(self.zoom_indicator.hide)

        self.image_label.installEventFilter(self)
        self.scroll_area.viewport().installEventFilter(self)

    def set_image(self, path: Path) -> bool:
        self.zoom_indicator_timer.stop()
        self.zoom_indicator.hide()
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            return False
        self.path = path
        self.original_image = image
        self._zoom_mode = "fit"
        self.info_label.setText(self._image_information(path))
        self.info_label.setToolTip(str(path))
        self._render_image()
        return True

    def _image_information(self, path: Path) -> str:
        lines = [path.name]
        lines.append(
            f"{self.original_image.width()} × {self.original_image.height()} Pixel"
        )
        try:
            lines.append(format_file_size(path.stat().st_size))
        except OSError:
            pass
        try:
            with PillowImage.open(path) as image:
                exif = image.getexif()
                for tag in (36867, 36868, 306):
                    recording_date = format_date(exif.get(tag))
                    if recording_date is not None:
                        lines.append(f"Aufgenommen: {recording_date}")
                        break
                iso_value = extract_iso_value(exif)
                if iso_value is not None:
                    lines.append(f"ISO: {iso_value}")
        except Exception:
            pass
        return "\n".join(lines)

    def _render_image(self) -> None:
        if self.original_image.isNull():
            return
        viewport_size = self.scroll_area.viewport().size()
        if viewport_size.width() <= 1 or viewport_size.height() <= 1:
            return
        if self._zoom_mode == "fit":
            self._zoom_factor = image_fit_zoom_factor(
                self.original_image, viewport_size
            )
        scaled_size = image_size_at_zoom(
            self.original_image, self._zoom_factor
        )
        scaled_image = self.original_image.scaled(
            scaled_size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.resize(scaled_size)
        self.image_label.setPixmap(QPixmap.fromImage(scaled_image))
        if self._zoom_mode == "fit":
            self.scroll_area.horizontalScrollBar().setValue(0)
            self.scroll_area.verticalScrollBar().setValue(0)

    def fit_image(self, show_overlay: bool = True) -> None:
        self._zoom_mode = "fit"
        self._render_image()
        if show_overlay:
            self._show_zoom_indicator()

    def show_actual_size(self, show_overlay: bool = True) -> None:
        self.set_zoom_factor(1.0, 0.5, 0.5, show_overlay)

    def set_zoom_factor(
        self,
        factor: float,
        relative_x: float = 0.5,
        relative_y: float = 0.5,
        show_overlay: bool = True,
    ) -> None:
        self._zoom_mode = "manual"
        self._zoom_factor = min(MAX_ZOOM, max(MIN_ZOOM, factor))
        self._render_image()
        self.set_relative_scroll(relative_x, relative_y)
        if show_overlay:
            self._show_zoom_indicator()

    def _zoom_at(self, viewport_position, factor: float) -> None:
        old_size = self.image_label.size()
        label_position = self.image_label.pos()
        relative_x = min(
            1.0,
            max(0.0, (viewport_position.x() - label_position.x()) / old_size.width()),
        )
        relative_y = min(
            1.0,
            max(0.0, (viewport_position.y() - label_position.y()) / old_size.height()),
        )
        self._zoom_mode = "manual"
        self._zoom_factor = min(
            MAX_ZOOM, max(MIN_ZOOM, self._zoom_factor * factor)
        )
        self._render_image()
        horizontal_bar = self.scroll_area.horizontalScrollBar()
        vertical_bar = self.scroll_area.verticalScrollBar()
        horizontal_bar.setValue(
            round(relative_x * self.image_label.width() - viewport_position.x())
        )
        vertical_bar.setValue(
            round(relative_y * self.image_label.height() - viewport_position.y())
        )
        self._show_zoom_indicator()
        scroll_x, scroll_y = self.relative_scroll()
        self.zoom_changed.emit(self._zoom_factor, scroll_x, scroll_y)

    def relative_scroll(self) -> tuple[float, float]:
        horizontal_bar = self.scroll_area.horizontalScrollBar()
        vertical_bar = self.scroll_area.verticalScrollBar()
        horizontal = (
            horizontal_bar.value() / horizontal_bar.maximum()
            if horizontal_bar.maximum()
            else 0.5
        )
        vertical = (
            vertical_bar.value() / vertical_bar.maximum()
            if vertical_bar.maximum()
            else 0.5
        )
        return horizontal, vertical

    def set_relative_scroll(self, horizontal: float, vertical: float) -> None:
        horizontal_bar = self.scroll_area.horizontalScrollBar()
        vertical_bar = self.scroll_area.verticalScrollBar()
        horizontal_bar.setValue(round(horizontal * horizontal_bar.maximum()))
        vertical_bar.setValue(round(vertical * vertical_bar.maximum()))

    def _show_zoom_indicator(self) -> None:
        prefix = "Eingepasst · " if self._zoom_mode == "fit" else ""
        self.zoom_indicator.setText(f"{prefix}{round(self._zoom_factor * 100)} %")
        self.zoom_indicator.adjustSize()
        self.zoom_indicator.show()
        self.zoom_indicator.raise_()
        self._position_zoom_indicator()
        self.zoom_indicator_timer.start(ZOOM_INDICATOR_DURATION)

    def _position_zoom_indicator(self) -> None:
        if not self.zoom_indicator.isVisible():
            return
        viewport = self.scroll_area.viewport()
        margin = 16
        self.zoom_indicator.move(
            max(margin, viewport.width() - self.zoom_indicator.width() - margin),
            max(margin, viewport.height() - self.zoom_indicator.height() - margin),
        )

    def eventFilter(self, watched, event) -> bool:
        image_widgets = (self.image_label, self.scroll_area.viewport())
        if watched is self.scroll_area.viewport() and event.type() == QEvent.Type.Resize:
            self._position_zoom_indicator()
            if self._zoom_mode == "fit":
                QTimer.singleShot(0, self._render_image)
        elif watched in image_widgets and event.type() == QEvent.Type.Wheel:
            wheel_steps = event.angleDelta().y() / 120
            if wheel_steps and not self.original_image.isNull():
                viewport_position = self.scroll_area.viewport().mapFromGlobal(
                    event.globalPosition().toPoint()
                )
                self._zoom_at(viewport_position, ZOOM_STEP**wheel_steps)
                return True
        elif (
            watched in image_widgets
            and event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._mouse_press_position = event.globalPosition().toPoint()
            self._pan_last_position = self._mouse_press_position
            return True
        elif (
            watched in image_widgets
            and event.type() == QEvent.Type.MouseMove
            and self._mouse_press_position is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            current_position = event.globalPosition().toPoint()
            movement = current_position - self._pan_last_position
            horizontal_bar = self.scroll_area.horizontalScrollBar()
            vertical_bar = self.scroll_area.verticalScrollBar()
            horizontal_bar.setValue(horizontal_bar.value() - movement.x())
            vertical_bar.setValue(vertical_bar.value() - movement.y())
            self._pan_last_position = current_position
            self.pan_changed.emit(*self.relative_scroll())
            return True
        elif (
            watched in image_widgets
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._mouse_press_position = None
            self._pan_last_position = None
            return True
        return super().eventFilter(watched, event)


class ImageComparisonDialog(QDialog):
    def __init__(
        self,
        left_path: Path,
        right_path: Path,
        colors: dict[str, str] | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bilder vergleichen")
        self.setModal(True)
        self.resize(1200, 760)
        self.setMinimumSize(800, 500)
        self._paths = [left_path, right_path]

        layout = QVBoxLayout(self)
        self.coupling_checkbox = QCheckBox("Zoom und Verschieben koppeln")
        self.coupling_checkbox.setChecked(True)
        layout.addWidget(self.coupling_checkbox)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.left_view = ComparisonImageView()
        self.right_view = ComparisonImageView()
        self.splitter.addWidget(self.left_view)
        self.splitter.addWidget(self.right_view)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([600, 600])
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter, 1)

        button_row = QHBoxLayout()
        self.fit_button = QPushButton("Einpassen")
        self.actual_size_button = QPushButton("100 %")
        self.swap_button = QPushButton("Bilder tauschen")
        self.close_button = QPushButton("Schließen")
        button_row.addWidget(self.fit_button)
        button_row.addWidget(self.actual_size_button)
        button_row.addWidget(self.swap_button)
        button_row.addStretch(1)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

        self.fit_button.clicked.connect(self.fit_both)
        self.actual_size_button.clicked.connect(self.show_both_actual_size)
        self.swap_button.clicked.connect(self.swap_images)
        self.close_button.clicked.connect(self.accept)
        self.left_view.zoom_changed.connect(
            lambda factor, x, y: self._mirror_zoom(self.left_view, factor, x, y)
        )
        self.right_view.zoom_changed.connect(
            lambda factor, x, y: self._mirror_zoom(self.right_view, factor, x, y)
        )
        self.left_view.pan_changed.connect(
            lambda x, y: self._mirror_pan(self.left_view, x, y)
        )
        self.right_view.pan_changed.connect(
            lambda x, y: self._mirror_pan(self.right_view, x, y)
        )

        self._add_shortcut("0", self.fit_both)
        self._add_shortcut("1", self.show_both_actual_size)
        self._add_shortcut("L", self.coupling_checkbox.toggle)
        self._add_shortcut("Escape", self.reject)
        self._apply_colors(colors)
        self.left_view.set_image(left_path)
        self.right_view.set_image(right_path)

    def _add_shortcut(self, key: str, handler) -> None:
        action = QAction(self)
        action.setShortcut(QKeySequence(key))
        action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        action.triggered.connect(handler)
        self.addAction(action)

    def _other_view(self, source: ComparisonImageView) -> ComparisonImageView:
        return self.right_view if source is self.left_view else self.left_view

    def _mirror_zoom(
        self,
        source: ComparisonImageView,
        factor: float,
        horizontal: float,
        vertical: float,
    ) -> None:
        if self.coupling_checkbox.isChecked():
            self._other_view(source).set_zoom_factor(
                factor, horizontal, vertical
            )

    def _mirror_pan(
        self,
        source: ComparisonImageView,
        horizontal: float,
        vertical: float,
    ) -> None:
        if self.coupling_checkbox.isChecked():
            self._other_view(source).set_relative_scroll(horizontal, vertical)

    def fit_both(self) -> None:
        self.left_view.fit_image()
        self.right_view.fit_image()

    def show_both_actual_size(self) -> None:
        self.left_view.show_actual_size()
        self.right_view.show_actual_size()

    def swap_images(self) -> None:
        self._paths.reverse()
        self.left_view.set_image(self._paths[0])
        self.right_view.set_image(self._paths[1])

    def _apply_colors(self, colors: dict[str, str] | None) -> None:
        if colors is None:
            return
        self.setStyleSheet(
            message_box_stylesheet(colors)
            + f"""
QDialog {{ background-color: {colors['window']}; color: {colors['text']}; }}
QScrollArea#comparisonScrollArea, QLabel#comparisonImageLabel {{
    background-color: {colors['image']}; border: none;
}}
QLabel#comparisonInfoLabel {{
    background-color: {colors['panel']}; color: {colors['text']};
    border: 1px solid {colors['border']}; border-radius: 4px; padding: 6px;
}}
QSplitter::handle {{ background-color: {colors['border']}; width: 3px; }}
"""
        )


class PrintPreviewWidget(QWidget):
    def __init__(self, image: QImage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.image = image
        self.orientation = QPageLayout.Orientation.Portrait
        self.additional_rotation = 0
        self.size_mode = "fit"
        self.centered = True
        self.image_dpi = 300.0
        self.setMinimumSize(360, 360)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

    def set_print_options(
        self,
        orientation: QPageLayout.Orientation,
        additional_rotation: int,
        size_mode: str,
        centered: bool,
        image_dpi: float,
    ) -> None:
        self.orientation = orientation
        self.additional_rotation = additional_rotation
        self.size_mode = size_mode
        self.centered = centered
        self.image_dpi = image_dpi
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())
        available = QRectF(self.rect()).adjusted(18, 18, -18, -18)
        paper_width, paper_height = (210.0, 297.0)
        if self.orientation == QPageLayout.Orientation.Landscape:
            paper_width, paper_height = paper_height, paper_width
        paper_scale = min(
            available.width() / paper_width,
            available.height() / paper_height,
        )
        paper_rect = QRectF(
            available.center().x() - paper_width * paper_scale / 2,
            available.center().y() - paper_height * paper_scale / 2,
            paper_width * paper_scale,
            paper_height * paper_scale,
        )
        painter.fillRect(paper_rect.translated(4, 4), QColor(0, 0, 0, 45))
        painter.fillRect(paper_rect, Qt.GlobalColor.white)
        painter.setPen(QPen(QColor("#b8b8b8"), 1))
        painter.drawRect(paper_rect)
        printable_rect = paper_rect.adjusted(
            paper_rect.width() * 0.06,
            paper_rect.height() * 0.06,
            -paper_rect.width() * 0.06,
            -paper_rect.height() * 0.06,
        )
        preview_image = rotated_display_image(
            self.image, self.additional_rotation
        )
        layout = calculate_print_layout(
            preview_image.size(), printable_rect, self.size_mode, 100,
            self.image_dpi, self.centered,
        )
        painter.setPen(QPen(QColor("#999999"), 1, Qt.PenStyle.DashLine))
        painter.drawRect(printable_rect)
        draw_print_layout(painter, preview_image, printable_rect, layout)


class PrintSettingsDialog(QDialog):
    ORIENTATIONS = (
        ("Automatisch", "automatic"),
        ("Hochformat", "portrait"),
        ("Querformat", "landscape"),
    )
    ROTATIONS = (
        ("Keine zusätzliche Drehung", 0),
        ("90° nach links", -90),
        ("90° nach rechts", 90),
        ("180°", 180),
    )
    SIZE_MODES = (
        ("Einpassen", "fit"), ("Seite füllen", "fill"),
        ("Originalgröße (100 %)", "original"), ("10 × 15 cm", "10x15"),
        ("13 × 18 cm", "13x18"), ("A4", "a4"),
    )

    def __init__(
        self,
        image: QImage,
        image_dpi: float,
        settings: QSettings,
        colors: dict[str, str] | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.image = image
        self.image_dpi = image_dpi
        self.settings = settings
        self.setWindowTitle("Druckeinstellungen")
        self.setMinimumSize(520, 600)
        self.resize(600, 700)
        self.setStyleSheet(message_box_stylesheet(colors))

        main_layout = QVBoxLayout(self)
        self.preview = PrintPreviewWidget(image, self)
        main_layout.addWidget(self.preview, 1)

        options_group = QGroupBox("Druckeinstellungen", self)
        options_form = QFormLayout(options_group)
        self.orientation_combo = QComboBox(options_group)
        for label, value in self.ORIENTATIONS:
            self.orientation_combo.addItem(label, value)
        self.rotation_combo = QComboBox(options_group)
        for label, value in self.ROTATIONS:
            self.rotation_combo.addItem(label, value)
        options_form.addRow("Papierausrichtung:", self.orientation_combo)
        options_form.addRow("Bilddrehung:", self.rotation_combo)
        self.size_combo = QComboBox(options_group)
        for label, value in self.SIZE_MODES:
            self.size_combo.addItem(label, value)
        self.centered_check = QCheckBox("Bild zentrieren", options_group)
        options_form.addRow("Bildgröße:", self.size_combo)
        options_form.addRow("", self.centered_check)
        main_layout.addWidget(options_group)
        self.hint_label = QLabel(self)
        self.hint_label.setWordWrap(True)
        main_layout.addWidget(self.hint_label)

        saved_orientation = settings.value(
            PRINT_ORIENTATION_KEY, "automatic", type=str
        )
        orientation_index = self.orientation_combo.findData(saved_orientation)
        self.orientation_combo.setCurrentIndex(max(0, orientation_index))
        saved_rotation = settings.value(PRINT_ROTATION_KEY, 0, type=int)
        rotation_index = self.rotation_combo.findData(saved_rotation)
        self.rotation_combo.setCurrentIndex(max(0, rotation_index))
        size_index = self.size_combo.findData(
            settings.value(PRINT_SIZE_MODE_KEY, "fit", type=str)
        )
        self.size_combo.setCurrentIndex(max(0, size_index))
        self.centered_check.setChecked(
            settings.value(PRINT_CENTERED_KEY, True, type=bool)
        )

        buttons = QDialogButtonBox(self)
        continue_button = buttons.addButton(
            "Weiter zum Druckdialog …",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        cancel_button = buttons.addButton(
            "Abbrechen", QDialogButtonBox.ButtonRole.RejectRole
        )
        continue_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

        self.orientation_combo.currentIndexChanged.connect(
            self._update_preview
        )
        self.rotation_combo.currentIndexChanged.connect(self._update_preview)
        self.size_combo.currentIndexChanged.connect(self._update_preview)
        self.centered_check.toggled.connect(self._update_preview)
        self._update_preview()

    def selected_orientation(self) -> QPageLayout.Orientation:
        selection = self.orientation_combo.currentData()
        if selection == "portrait":
            return QPageLayout.Orientation.Portrait
        if selection == "landscape":
            return QPageLayout.Orientation.Landscape
        rotated_image = rotated_display_image(
            self.image, self.additional_rotation()
        )
        if rotated_image.width() > rotated_image.height():
            return QPageLayout.Orientation.Landscape
        return QPageLayout.Orientation.Portrait

    def additional_rotation(self) -> int:
        return int(self.rotation_combo.currentData())

    def size_mode(self) -> str:
        return str(self.size_combo.currentData())

    def centered(self) -> bool:
        return self.centered_check.isChecked()

    def _update_preview(self) -> None:
        self.preview.set_print_options(
            self.selected_orientation(), self.additional_rotation(),
            self.size_mode(), self.centered(), self.image_dpi,
        )
        hints = {
            "fit": "Das gesamte Bild wird proportional auf die Seite eingepasst.",
            "fill": "Die Seite wird vollständig gefüllt. Bildbereiche können abgeschnitten werden.",
            "original": "Das Bild wird entsprechend seiner DPI-Angabe in Originalgröße gedruckt.",
            "10x15": "Das Bild wird in einer maximalen Größe von 10 × 15 cm gedruckt.",
            "13x18": "Das Bild wird in einer maximalen Größe von 13 × 18 cm gedruckt.",
            "a4": "Das Papierformat wird auf A4 gesetzt und das Bild passend eingepasst.",
        }
        hint = hints[self.size_mode()]
        if self.size_mode() in {"10x15", "13x18"}:
            paper_width, paper_height = (210.0, 297.0)
            if self.selected_orientation() == QPageLayout.Orientation.Landscape:
                paper_width, paper_height = paper_height, paper_width
            preview_rect = QRectF(
                0.0, 0.0,
                paper_width / 2.54 * 100 * 0.88,
                paper_height / 2.54 * 100 * 0.88,
            )
            preview_image = rotated_display_image(
                self.image, self.additional_rotation()
            )
            layout = calculate_print_layout(
                preview_image.size(), preview_rect, self.size_mode(), 100,
                self.image_dpi, self.centered(),
            )
            if layout.scaled_down:
                hint += " Das gewählte Fotoformat ist für die bedruckbare Fläche zu groß und wird verkleinert."
        self.hint_label.setText(hint)

    def accept(self) -> None:
        self.settings.setValue(
            PRINT_ORIENTATION_KEY, self.orientation_combo.currentData()
        )
        self.settings.setValue(PRINT_ROTATION_KEY, self.additional_rotation())
        self.settings.setValue(PRINT_SIZE_MODE_KEY, self.size_mode())
        self.settings.setValue(PRINT_CENTERED_KEY, self.centered())
        super().accept()


class MultiImagePrintPreview(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.paths: list[Path] = []
        self.images_per_page = 4
        self.print_settings = MultiImagePrintSettings()
        self.landscape = False
        self.page_index = 0
        self.contact_sheet = False
        self.show_filename = False
        self.show_capture_date = False
        self.show_page_number = False
        self.print_date_text = ""
        self.capture_dates: dict[Path, str] = {}
        self.setMinimumSize(420, 420)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

    def set_options(
        self, paths: list[Path], print_settings: MultiImagePrintSettings, landscape: bool,
        page_index: int, print_date_text: str,
    ) -> None:
        self.paths = paths
        self.print_settings = print_settings
        self.images_per_page = print_settings.effective_images_per_page
        self.landscape = landscape
        self.page_index = page_index
        self.contact_sheet = print_settings.contact_sheet
        self.show_filename = print_settings.show_filename
        self.show_capture_date = print_settings.show_capture_date
        self.show_page_number = print_settings.show_page_number
        self.print_date_text = print_date_text
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#d7d7d7"))
        available = QRectF(self.rect()).adjusted(16, 16, -16, -16)
        page_size = QSize(297, 210) if self.landscape else QSize(210, 297)
        paper_size = page_size.scaled(
            available.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio
        )
        paper_width = paper_size.width()
        paper_height = paper_size.height()
        paper_rect = QRectF(
            available.center().x() - paper_width / 2,
            available.center().y() - paper_height / 2,
            paper_width, paper_height,
        )
        painter.fillRect(paper_rect.translated(3, 3), QColor(0, 0, 0, 45))
        painter.fillRect(paper_rect, Qt.GlobalColor.white)
        printable_rect = paper_rect.adjusted(
            paper_rect.width() * 0.04, paper_rect.height() * 0.04,
            -paper_rect.width() * 0.04, -paper_rect.height() * 0.04,
        )
        painter.setPen(QPen(QColor("#999999"), 1, Qt.PenStyle.DashLine))
        painter.drawRect(printable_rect)
        if not self.paths:
            return
        sizes: list[QSize] = []
        for path in self.paths:
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            image_size = reader.size()
            sizes.append(image_size if image_size.isValid() else QSize(1, 1))
        resolution = max(1, round(paper_rect.width() / ((297 if self.landscape else 210) / 25.4)))
        page = calculate_multi_image_page(
            sizes, printable_rect, self.images_per_page, resolution,
            self.landscape, self.page_index, self.contact_sheet,
            self.show_filename, self.show_capture_date, self.show_page_number,
            settings=self.print_settings,
        )
        draw_multi_print_header(painter, page, self.print_settings)
        for cell in page.cells:
            painter.fillRect(cell.rect, Qt.GlobalColor.white)
            image = load_multi_print_image(
                self.paths[cell.image_index], cell.image_rect, resolution
            )
            if image.isNull():
                painter.setPen(QColor("#777777"))
                painter.drawText(cell.rect, Qt.AlignmentFlag.AlignCenter, "Bild konnte nicht geladen werden")
            else:
                painter.drawImage(cell.image_rect, image)
            painter.setPen(Qt.GlobalColor.black)
            font = painter.font(); font.setPointSizeF(max(5, 10 - self.images_per_page / 4)); painter.setFont(font)
            if self.show_filename and not cell.filename_rect.isEmpty():
                text = painter.fontMetrics().elidedText(pathlib_name(self.paths[cell.image_index]), Qt.TextElideMode.ElideMiddle, int(cell.filename_rect.width()))
                painter.drawText(cell.filename_rect, Qt.AlignmentFlag.AlignCenter, text)
            if self.show_capture_date and not cell.date_rect.isEmpty():
                path = self.paths[cell.image_index]
                date = self.capture_dates.setdefault(path, capture_date_text(path))
                painter.drawText(cell.date_rect, Qt.AlignmentFlag.AlignCenter, date)
        draw_multi_print_footer(
            painter,
            page,
            self.print_settings,
            page.page_index + 1,
            page.page_count,
            self.print_date_text,
        )


class ImageViewer(QObject):
    folder_changed = Signal(object)

    def __init__(
        self,
        startup_directory: Path | None = None,
        startup_image: Path | None = None,
    ) -> None:
        super().__init__()
        self.settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)
        self._migrate_legacy_settings()
        self.start_directory = startup_directory or self._start_directory()
        self.startup_image = startup_image
        saved_interval = self.settings.value(SLIDESHOW_INTERVAL_KEY, 5, type=int)
        self._slideshow_interval = (
            saved_interval if saved_interval in SLIDESHOW_INTERVALS else 5
        )
        self._slideshow_repeat = self.settings.value(
            SLIDESHOW_REPEAT_KEY, False, type=bool
        )
        self._slideshow_fullscreen = self.settings.value(
            SLIDESHOW_FULLSCREEN_KEY, False, type=bool
        )
        self._slideshow_selected_only = self.settings.value(
            SLIDESHOW_SELECTED_ONLY_KEY, False, type=bool
        )
        self._slideshow_random = self.settings.value(
            SLIDESHOW_RANDOM_KEY, False, type=bool
        )
        self._slideshow_show_metadata = self.settings.value(
            SLIDESHOW_METADATA_KEY, False, type=bool
        )
        self._slideshow_soft_fade = self.settings.value(
            SLIDESHOW_FADE_KEY, True, type=bool
        )
        saved_color_scheme = self.settings.value(
            COLOR_SCHEME_KEY, "System", type=str
        )
        self._color_scheme = (
            saved_color_scheme if saved_color_scheme in COLOR_SCHEMES else "System"
        )
        saved_thumbnail_size = self.settings.value(
            THUMBNAIL_SIZE_KEY, THUMBNAIL_DEFAULT, type=int
        )
        self._thumbnail_pixels = normalized_thumbnail_pixels(saved_thumbnail_size)
        if saved_thumbnail_size != self._thumbnail_pixels:
            self.settings.setValue(THUMBNAIL_SIZE_KEY, self._thumbnail_pixels)
            self.settings.sync()
        self._thumbnail_size = thumbnail_size_for_pixels(self._thumbnail_pixels)
        self._thumbnail_grid_size = thumbnail_grid_size_for_pixels(
            self._thumbnail_pixels
        )
        self._show_hidden_files = show_hidden_files_value(
            self.settings.value(SHOW_HIDDEN_FILES_KEY, False)
        )
        saved_sort_criterion = self.settings.value(
            SORT_CRITERION_KEY, "name", type=str
        )
        self._sort_criterion = (
            saved_sort_criterion
            if saved_sort_criterion in SORT_CRITERIA
            else "name"
        )
        self._sort_ascending = self.settings.value(
            SORT_ASCENDING_KEY, True, type=bool
        )
        self._name_collator = QCollator()
        self._name_collator.setCaseSensitivity(
            Qt.CaseSensitivity.CaseInsensitive
        )
        self._name_collator.setNumericMode(True)
        self.window = self._load_ui()
        self.window.setWindowTitle(APP_NAME)
        self.status_bar = self.window.statusBar()
        self.status_bar.setSizeGripEnabled(False)
        self.status_bar.setContentsMargins(4, 0, 4, 0)
        self.status_info_label = QLabel("Kein Bild ausgewählt", self.status_bar)
        self.status_info_label.setObjectName("statusInfoLabel")
        self.status_info_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.status_info_label.installEventFilter(self)
        self.status_zoom_label = QLabel("", self.status_bar)
        self.status_zoom_label.setObjectName("statusZoomLabel")
        self.status_zoom_label.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred
        )
        self.status_bar.addWidget(self.status_info_label, 1)
        self.status_bar.addPermanentWidget(self.status_zoom_label)
        self._status_full_text = "Kein Bild ausgewählt"
        self.directory_tree = self._widget(QTreeView, "directoryTreeView")
        self.directory_heading_label = self._widget(QLabel, "computerLabel")
        self.thumbnail_list = self._widget(QListWidget, "thumbnailList")
        self.image_scroll_area = self._widget(QScrollArea, "imageScrollArea")
        self.image_label = self._widget(QLabel, "imageLabel")
        self.previous_button = self._widget(QPushButton, "previousButton")
        self.next_button = self._widget(QPushButton, "nextButton")
        self.previous_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.next_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.previous_button.setText("‹")
        self.previous_button.setToolTip("Vorheriges Bild")
        self.previous_button.setAccessibleName("Vorheriges Bild")
        self.next_button.setText("›")
        self.next_button.setToolTip("Nächstes Bild")
        self.next_button.setAccessibleName("Nächstes Bild")
        self.file_name_label = self._widget(QLabel, "fileNameLabel")
        self.previous_button.setFixedSize(22, 18)
        self.next_button.setFixedSize(22, 18)
        self._file_name_text = ""
        self._directory_path_text = ""
        self.splitter = self._widget(QSplitter, "mainSplitter")
        self.right_splitter = self._widget(QSplitter, "rightSplitter")
        self.directory_panel = self.directory_tree.parentWidget()
        self.preview_panel = self.image_scroll_area.parentWidget()
        self._install_pdf_page_navigation()
        self._install_thumbnail_size_controls()
        self.current_directory: Path | None = None
        self.current_image: Path | None = None
        self._pdf_document = None
        self._pdf_page = 0
        self._pdf_render_size = QSize()
        self._pdf_quality_refresh_pending = False
        self._folder_history: list[Path] = []
        self._folder_history_index = -1
        self._current_file_size: int | None = None
        self._pending_selection_paths: set[Path] = set()
        self._pending_primary_path: Path | None = None
        self._clipboard_operation: str | None = None
        self._clipboard_source_paths: list[Path] = []
        self._handling_clipboard_change = False
        self.clipboard = QApplication.clipboard()
        self.original_image = QImage()
        self._exif_oriented_image = QImage()
        self._display_rotation_by_path: dict[str, int] = {}
        self._rotation_context_path: Path | None = None
        self._file_manager_context_path: Path | None = None
        self._rename_context_path: Path | None = None
        self._export_context_path: Path | None = None
        self._zoom_mode = "fit"
        self._zoom_factor = 1.0
        self._mouse_press_position = None
        self._pan_last_position = None
        self._dragging_image = False
        self._thumbnail_drag_start_position = None
        self._thumbnail_drag_pressed_path: Path | None = None
        self._thumbnail_drag_selected_paths_snapshot: list[Path] = []
        self._slideshow_running = False
        self._slideshow_paused = False
        self._slideshow_entered_fullscreen = False
        self._slideshow_paths: list[Path] = []
        self._slideshow_index = -1
        self._slideshow_fade_animation: QPropertyAnimation | None = None
        self._slideshow_opacity_effect: QGraphicsOpacityEffect | None = None
        self._image_render_pending = False
        self._fullscreen_mode = False
        self._pdf_preview_mode = False
        self._pdf_preview_main_splitter_sizes: list[int] = []
        self._pdf_preview_right_splitter_sizes: list[int] = []
        self._normal_geometry = None
        self._normal_was_maximized = False
        self._normal_main_splitter_sizes = []
        self._normal_right_splitter_sizes = []
        self._normal_window_style = ""
        self._normal_image_style = ""
        self._normal_central_margins = None
        self._load_generation = 0
        self._pending_images: list[Path] = []
        self._next_job_index = 0
        self._prepare_index = 0
        self._completed_jobs = 0
        self._active_jobs = 0
        self._directory_iterator = None
        self._metadata_cache: dict[tuple[str, int, int, int], str] = {}
        self._image_metadata_cache: dict[
            tuple[str, int, int, int], dict[str, str]
        ] = {}
        self._image_metadata_by_path: dict[str, dict[str, str]] = {}
        self._file_sort_metadata: dict[str, tuple[int, int]] = {}
        self._recording_date_cache: dict[str, datetime | None] = {}
        self._resolved_sort_path_cache: dict[str, str] = {}
        self._capture_sort_waiting = False
        self.thread_pool = QThreadPool(self)
        self.thread_pool.setMaxThreadCount(3)
        self.slideshow_timer = QTimer(self)
        self.slideshow_timer.setSingleShot(True)
        self.slideshow_timer.timeout.connect(self._advance_slideshow)
        self.slideshow_message_timer = QTimer(self)
        self.slideshow_message_timer.setSingleShot(True)
        self.slideshow_message_timer.timeout.connect(
            lambda: self.slideshow_message_label.hide()
        )
        self.slideshow_cursor_timer = QTimer(self)
        self.slideshow_cursor_timer.setSingleShot(True)
        self.slideshow_cursor_timer.setInterval(2000)
        self.slideshow_cursor_timer.timeout.connect(
            self._hide_slideshow_cursor
        )
        self.fullscreen_tooltip_timer = QTimer(self)
        self.fullscreen_tooltip_timer.setSingleShot(True)
        self.fullscreen_tooltip_timer.timeout.connect(
            self._hide_fullscreen_tooltip
        )
        self._fullscreen_tooltip_visible = False
        self.zoom_indicator_timer = QTimer(self)
        self.zoom_indicator_timer.setSingleShot(True)
        self.zoom_indicator_timer.timeout.connect(self._hide_zoom_indicator)

        self.thumbnail_list.setViewMode(QListView.ViewMode.IconMode)
        self.thumbnail_list.setMovement(QListView.Movement.Static)
        self.thumbnail_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.thumbnail_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.thumbnail_list.setWrapping(True)
        self.thumbnail_list.setWordWrap(True)
        self.thumbnail_list.setIconSize(self._thumbnail_size)
        self.thumbnail_list.setGridSize(self._thumbnail_grid_size)
        self.thumbnail_list.setSpacing(THUMBNAIL_SPACING)
        self.thumbnail_list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.thumbnail_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.thumbnail_list.setAcceptDrops(True)
        self.thumbnail_list.viewport().setAcceptDrops(True)
        self.image_scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_scroll_area.setWidgetResizable(False)
        self.window.setAcceptDrops(True)
        self.image_scroll_area.viewport().setAcceptDrops(True)
        self.image_label.setAcceptDrops(True)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.image_label.setMinimumSize(1, 1)
        self.image_label.setScaledContents(False)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setWordWrap(True)
        self.image_label.setMouseTracking(True)
        self.image_scroll_area.viewport().setMouseTracking(True)
        self.image_label.setText("Bild anklicken, um es anzuzeigen")
        self.image_label.resize(self.image_scroll_area.viewport().size())
        image_tooltip = """🖱 Bedienung

• Mausrad: Zoomen
• Linke Maustaste ziehen: Bild verschieben
• Klick: Vollbild ein/aus
• 0: Bild einpassen
• 1: Originalgröße
• F11: Vollbild"""
        self.image_label.setToolTip(image_tooltip)
        self.image_scroll_area.viewport().setToolTip(image_tooltip)
        self.zoom_indicator = QLabel(self.image_scroll_area.viewport())
        self.zoom_indicator.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self.zoom_indicator.setStyleSheet(ZOOM_INDICATOR_STYLESHEET)
        self.zoom_indicator.hide()

        self.drop_hint_label = QLabel(self.image_scroll_area.viewport())
        self.drop_hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_hint_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self.drop_hint_label.setStyleSheet(
            "QLabel { background-color: rgba(25, 85, 145, 210); color: white;"
            " border: 2px dashed rgba(255, 255, 255, 210); border-radius: 10px;"
            " font-size: 18px; font-weight: 600; margin: 16px; }"
        )
        self.drop_hint_label.hide()

        self.slideshow_message_label = QLabel(
            self.image_scroll_area.viewport()
        )
        self.slideshow_message_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self.slideshow_message_label.setStyleSheet(ZOOM_INDICATOR_STYLESHEET)
        self.slideshow_message_label.hide()
        self.slideshow_metadata_label = QLabel(
            self.image_scroll_area.viewport()
        )
        self.slideshow_metadata_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self.slideshow_metadata_label.setStyleSheet(
            "QLabel { background-color: rgba(20, 20, 20, 205); color: #F7F7F7;"
            " border: 1px solid rgba(255, 255, 255, 40); border-radius: 6px;"
            " padding: 8px 11px; font-size: 13px; }"
        )
        self.slideshow_metadata_label.hide()

        self.directory_model = QFileSystemModel(self.window)
        self._set_directory_model_filter()
        self.directory_model.setReadOnly(True)
        root_index = self.directory_model.setRootPath(str(ROOT_DIRECTORY))
        self.directory_tree.setModel(self.directory_model)
        self.directory_tree.setRootIndex(root_index)
        for column in range(1, self.directory_model.columnCount()):
            self.directory_tree.hideColumn(column)

        self.splitter.setSizes([300, 900])
        self.right_splitter.setSizes([210, 490])
        self.directory_tree.clicked.connect(self._directory_selected)
        self.thumbnail_list.currentItemChanged.connect(self._thumbnail_selected)
        self.thumbnail_list.itemSelectionChanged.connect(self._selection_changed)
        self.thumbnail_list.customContextMenuRequested.connect(
            self._show_thumbnail_context_menu
        )
        self.previous_button.clicked.connect(lambda: self._select_relative_image(-1))
        self.next_button.clicked.connect(lambda: self._select_relative_image(1))
        self.splitter.splitterMoved.connect(self._schedule_image_render)
        self.right_splitter.splitterMoved.connect(self._schedule_image_render)
        self.image_label.installEventFilter(self)
        self.image_scroll_area.viewport().installEventFilter(self)
        self.thumbnail_list.viewport().installEventFilter(self)
        self.file_name_label.installEventFilter(self)
        self.window.installEventFilter(self)
        self.escape_shortcut = QShortcut(QKeySequence("Escape"), self.window)
        self.escape_shortcut.activated.connect(self._handle_escape)
        self._create_application_menus()
        self._create_directory_navigation_buttons()
        self.clipboard.dataChanged.connect(self._clipboard_changed)
        self._clipboard_changed()
        self._update_navigation_buttons()
        self._expand_initial_path(self.start_directory)
        if self.start_directory.is_dir():
            self._show_directory(
                self.start_directory,
                [self.startup_image] if self.startup_image is not None else None,
            )
        if should_auto_enter_pdf_preview(self.startup_image):
            QTimer.singleShot(0, self._enter_pdf_preview)

    def _install_pdf_page_navigation(self) -> None:
        """Add compact PDF-only page controls below the preview."""
        self.pdf_page_navigation = QWidget(self.preview_panel)
        self.pdf_page_navigation.setObjectName("pdfPageNavigation")
        layout = QHBoxLayout(self.pdf_page_navigation)
        layout.setContentsMargins(6, 1, 6, 2)
        layout.setSpacing(6)
        self.previous_pdf_page_button = QPushButton("‹", self.pdf_page_navigation)
        self.previous_pdf_page_button.setObjectName("previousPdfPageButton")
        self.previous_pdf_page_button.setToolTip("Vorherige PDF-Seite")
        self.previous_pdf_page_button.setAccessibleName("Vorherige PDF-Seite")
        self.pdf_page_label = QLabel("", self.pdf_page_navigation)
        self.pdf_page_label.setObjectName("pdfPageLabel")
        self.pdf_page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_pdf_page_button = QPushButton("›", self.pdf_page_navigation)
        self.next_pdf_page_button.setObjectName("nextPdfPageButton")
        self.next_pdf_page_button.setToolTip("Nächste PDF-Seite")
        self.next_pdf_page_button.setAccessibleName("Nächste PDF-Seite")
        for button in (self.previous_pdf_page_button, self.next_pdf_page_button):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setFixedSize(22, 20)
        layout.addStretch(1)
        layout.addWidget(self.previous_pdf_page_button)
        layout.addWidget(self.pdf_page_label)
        layout.addWidget(self.next_pdf_page_button)
        layout.addStretch(1)
        self.pdf_page_navigation.hide()

    def _install_thumbnail_size_controls(self) -> None:
        thumbnail_index = self.right_splitter.indexOf(self.thumbnail_list)
        thumbnail_panel = QWidget(self.right_splitter)
        thumbnail_panel.setObjectName("thumbnailPanel")
        self.thumbnail_panel = thumbnail_panel
        thumbnail_layout = QVBoxLayout(thumbnail_panel)
        thumbnail_layout.setContentsMargins(0, 0, 0, 0)
        thumbnail_layout.setSpacing(2)

        self.thumbnail_list.setParent(thumbnail_panel)
        thumbnail_layout.addWidget(self.thumbnail_list, 1)

        controls = QWidget(thumbnail_panel)
        controls.setObjectName("thumbnailSizeControls")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(6, 1, 6, 2)
        controls_layout.setSpacing(6)

        navigation_layout = self.window.findChild(QHBoxLayout, "navigationLayout")
        if navigation_layout is None:
            raise RuntimeError("Die untere Navigationsleiste wurde nicht gefunden.")
        for widget in (
            self.previous_button,
            self.file_name_label,
            self.next_button,
        ):
            navigation_layout.removeWidget(widget)

        self.thumbnail_size_decrease_button = QToolButton(controls)
        self.thumbnail_size_decrease_button.setObjectName(
            "thumbnailSizeDecreaseButton"
        )
        self.thumbnail_size_decrease_button.setText("−")
        self.thumbnail_size_decrease_button.setToolTip("Vorschaubilder verkleinern")
        self.thumbnail_size_decrease_button.setAutoRaise(True)
        self.thumbnail_size_decrease_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.thumbnail_size_slider = QSlider(Qt.Orientation.Horizontal, controls)
        self.thumbnail_size_slider.setObjectName("thumbnailSizeSlider")
        self.thumbnail_size_slider.setToolTip("Größe der Vorschaubilder")
        self.thumbnail_size_slider.setRange(0, thumbnail_size_slider_maximum())
        self.thumbnail_size_slider.setSingleStep(1)
        self.thumbnail_size_slider.setPageStep(1)
        self.thumbnail_size_slider.setFixedWidth(132)
        self.thumbnail_size_slider.setFixedHeight(14)
        self.thumbnail_size_slider.setValue(
            thumbnail_size_slider_value(self._thumbnail_pixels)
        )

        self.thumbnail_size_increase_button = QToolButton(controls)
        self.thumbnail_size_increase_button.setObjectName(
            "thumbnailSizeIncreaseButton"
        )
        self.thumbnail_size_increase_button.setText("+")
        self.thumbnail_size_increase_button.setToolTip("Vorschaubilder vergrößern")
        self.thumbnail_size_increase_button.setAutoRaise(True)
        self.thumbnail_size_increase_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        controls_layout.addWidget(self.thumbnail_size_decrease_button)
        controls_layout.addWidget(self.thumbnail_size_slider)
        controls_layout.addWidget(self.thumbnail_size_increase_button)
        controls_layout.addSpacing(8)
        controls_layout.addWidget(self.previous_button)
        controls_layout.addWidget(self.file_name_label, 1)
        controls_layout.addWidget(self.next_button)
        thumbnail_layout.addWidget(controls)
        self.right_splitter.insertWidget(thumbnail_index, thumbnail_panel)

        preview_layout = self.preview_panel.layout()
        if isinstance(preview_layout, QVBoxLayout):
            preview_layout.removeItem(navigation_layout)
            preview_layout.addWidget(self.pdf_page_navigation)

        self.thumbnail_size_decrease_button.clicked.connect(
            lambda: self._change_thumbnail_size(-THUMBNAIL_STEP)
        )
        self.thumbnail_size_increase_button.clicked.connect(
            lambda: self._change_thumbnail_size(THUMBNAIL_STEP)
        )
        self.thumbnail_size_slider.valueChanged.connect(
            lambda value: self._apply_thumbnail_size(
                thumbnail_pixels_from_slider_value(value)
            )
        )

    def _migrate_legacy_settings(self) -> None:
        legacy_settings = QSettings(
            LEGACY_SETTINGS_ORGANIZATION,
            LEGACY_SETTINGS_APPLICATION,
        )
        migrated = False
        for key in (
            LAST_DIRECTORY_KEY,
            SLIDESHOW_INTERVAL_KEY,
            SLIDESHOW_REPEAT_KEY,
            SLIDESHOW_FULLSCREEN_KEY,
        ):
            if not self.settings.contains(key) and legacy_settings.contains(key):
                self.settings.setValue(key, legacy_settings.value(key))
                migrated = True
        if migrated:
            self.settings.sync()

    def _set_directory_model_filter(self) -> None:
        filter_flags = (
            QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives
        )
        if self._show_hidden_files:
            filter_flags |= QDir.Filter.Hidden
        self.directory_model.setFilter(filter_flags)

    def _set_show_hidden_files(self, checked: bool) -> None:
        self._show_hidden_files = checked
        self.settings.setValue(SHOW_HIDDEN_FILES_KEY, checked)
        self.settings.sync()
        self._set_directory_model_filter()
        if self.current_directory is None:
            return
        selection = [
            path
            for path in self._selected_image_paths()
            if should_show_path(path, checked)
        ]
        if self.current_image is not None and should_show_path(
            self.current_image, checked
        ):
            selection.insert(0, self.current_image)
        self._show_directory(self.current_directory, selection)

    def _start_directory(self) -> Path:
        saved_value = self.settings.value(LAST_DIRECTORY_KEY, "", type=str)
        if saved_value:
            saved_directory = Path(saved_value).expanduser()
            if saved_directory.is_dir():
                return saved_directory
        return START_DIRECTORY

    def _create_application_menus(self) -> None:
        self.file_menu = self.window.menuBar().addMenu("Datei")
        self.rename_image_action = QAction("Umbenennen …", self.window)
        self.rename_image_action.setShortcut(QKeySequence("F2"))
        self.rename_image_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.rename_image_action.triggered.connect(
            lambda: self._rename_image(self._rename_context_path)
        )
        self.file_menu.addAction(self.rename_image_action)
        self.export_resized_action = QAction(
            "Ausgewählte Bilder verkleinert exportieren …", self.window
        )
        self.export_resized_action.triggered.connect(
            lambda: self._show_resized_export_dialog(self._export_context_path)
        )
        self.file_menu.addAction(self.export_resized_action)
        self.print_action = QAction("Drucken …", self.window)
        self.print_action.setShortcut(QKeySequence("Ctrl+P"))
        self.print_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.print_action.triggered.connect(self._print_current_image)
        self.file_menu.addAction(self.print_action)
        self.multi_print_action = QAction("Mehrere Bilder drucken …", self.window)
        self.multi_print_action.triggered.connect(self._show_multi_print_dialog)
        self.file_menu.addAction(self.multi_print_action)
        self.contact_sheet_action = QAction("Kontaktabzug …", self.window)
        self.contact_sheet_action.triggered.connect(
            lambda: self._show_multi_print_dialog(True)
        )
        self.file_menu.addAction(self.contact_sheet_action)
        self.file_menu.addSeparator()
        self.window.addAction(self.rename_image_action)

        self.quit_action = QAction("Beenden", self.window)
        self.quit_action.setShortcut(QKeySequence("Alt+F4"))
        self.quit_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.quit_action.triggered.connect(self.window.close)
        self.file_menu.addAction(self.quit_action)

        self.edit_menu = self.window.menuBar().addMenu("Bearbeiten")
        self.select_all_action = QAction("Alles auswählen", self.window)
        self.select_all_action.setShortcut(QKeySequence("Ctrl+A"))
        self.select_all_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.select_all_action.triggered.connect(self._select_all_images)
        self.edit_menu.addAction(self.select_all_action)

        self.copy_image_action = QAction("Kopieren", self.window)
        self.copy_image_action.setShortcut(QKeySequence("Ctrl+C"))
        self.copy_image_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.copy_image_action.triggered.connect(
            lambda: self._put_current_image_on_clipboard("copy")
        )
        self.edit_menu.addAction(self.copy_image_action)

        self.cut_image_action = QAction("Ausschneiden", self.window)
        self.cut_image_action.setShortcut(QKeySequence("Ctrl+X"))
        self.cut_image_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.cut_image_action.triggered.connect(
            lambda: self._put_current_image_on_clipboard("cut")
        )
        self.edit_menu.addAction(self.cut_image_action)

        self.paste_image_action = QAction("Einfügen", self.window)
        self.paste_image_action.setShortcut(QKeySequence("Ctrl+V"))
        self.paste_image_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.paste_image_action.triggered.connect(self._paste_image_from_clipboard)
        self.edit_menu.addAction(self.paste_image_action)
        for action in (
            self.select_all_action,
            self.copy_image_action,
            self.cut_image_action,
            self.paste_image_action,
        ):
            self.window.addAction(action)

        self.image_menu = self.window.menuBar().addMenu("Bild")
        self.trash_image_action = QAction(
            "In den Papierkorb verschieben", self.window
        )
        self.trash_image_action.setShortcut(QKeySequence("Delete"))
        self.trash_image_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.trash_image_action.triggered.connect(self._move_current_image_to_trash)
        self.image_menu.addAction(self.trash_image_action)
        self.window.addAction(self.trash_image_action)
        self.edit_menu.addSeparator()
        self.edit_menu.addAction(self.trash_image_action)

        self.show_in_file_manager_action = QAction(
            "Im Dateimanager anzeigen", self.window
        )
        self.show_in_file_manager_action.triggered.connect(
            lambda: self.show_in_file_manager(
                self._file_manager_context_path
            )
        )
        self.image_menu.addSeparator()
        self.image_menu.addAction(self.show_in_file_manager_action)

        display_rotation_tooltip = (
            "Dreht nur die Anzeige. Die Originaldatei bleibt unverändert."
        )
        self.rotate_left_action = QAction("Nach links drehen", self.window)
        self.rotate_left_action.setShortcut(QKeySequence("Ctrl+Left"))
        self.rotate_left_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.rotate_left_action.setToolTip(display_rotation_tooltip)
        self.rotate_left_action.triggered.connect(
            lambda: self._rotate_current_image(
                -90, self._rotation_context_path
            )
        )

        self.rotate_right_action = QAction("Nach rechts drehen", self.window)
        self.rotate_right_action.setShortcut(QKeySequence("Ctrl+Right"))
        self.rotate_right_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.rotate_right_action.setToolTip(display_rotation_tooltip)
        self.rotate_right_action.triggered.connect(
            lambda: self._rotate_current_image(
                90, self._rotation_context_path
            )
        )

        self.reset_rotation_action = QAction(
            "Drehung zurücksetzen", self.window
        )
        self.reset_rotation_action.setToolTip(display_rotation_tooltip)
        self.reset_rotation_action.triggered.connect(
            lambda: self._reset_current_rotation(self._rotation_context_path)
        )

        self.image_menu.addSeparator()
        for action in (
            self.rotate_left_action,
            self.rotate_right_action,
            self.reset_rotation_action,
        ):
            self.image_menu.addAction(action)
            self.window.addAction(action)

        self.image_menu.addSeparator()
        self.save_rotated_copy_action = QAction(
            "Gedrehte Kopie speichern …", self.window
        )
        self.save_rotated_copy_action.triggered.connect(
            lambda: self._save_rotated_copy(self._rotation_context_path)
        )
        self.image_menu.addAction(self.save_rotated_copy_action)

        self.save_rotation_to_original_action = QAction(
            "Drehung im Original speichern …", self.window
        )
        self.save_rotation_to_original_action.triggered.connect(
            lambda: self._save_rotation_to_original(
                self._rotation_context_path
            )
        )
        self.image_menu.addAction(self.save_rotation_to_original_action)

        self.compare_images_action = QAction(
            "Bilder vergleichen …", self.window
        )
        self.compare_images_action.triggered.connect(self._compare_selected_images)
        self.image_menu.addSeparator()
        image_placeholder_action = QAction("Weitere Bildfunktionen folgen …", self.window)
        image_placeholder_action.setEnabled(False)
        self.image_menu.addAction(image_placeholder_action)

        self.view_menu = self.window.menuBar().addMenu("Ansicht")
        self.fullscreen_action = QAction("Vollbild", self.window)
        self.fullscreen_action.setCheckable(True)
        self.fullscreen_action.setShortcut(QKeySequence("F11"))
        self.fullscreen_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.fullscreen_action.triggered.connect(self._toggle_fullscreen)
        self.view_menu.addAction(self.fullscreen_action)

        self.leave_pdf_preview_action = QAction(
            "PDF-Vorschau verlassen", self.window
        )
        self.leave_pdf_preview_action.triggered.connect(self._leave_pdf_preview)
        self.leave_pdf_preview_action.setEnabled(False)
        self.view_menu.addAction(self.leave_pdf_preview_action)

        self.previous_pdf_page_action = QAction("PDF-Seite zurück", self.window)
        self.previous_pdf_page_action.setShortcut(QKeySequence(Qt.Key.Key_PageUp))
        self.previous_pdf_page_action.triggered.connect(lambda: self._change_pdf_page(-1))
        self.next_pdf_page_action = QAction("PDF-Seite weiter", self.window)
        self.next_pdf_page_action.setShortcut(QKeySequence(Qt.Key.Key_PageDown))
        self.next_pdf_page_action.triggered.connect(lambda: self._change_pdf_page(1))
        self.view_menu.addAction(self.previous_pdf_page_action)
        self.view_menu.addAction(self.next_pdf_page_action)
        self.previous_pdf_page_button.clicked.connect(
            lambda: self._change_pdf_page(-1)
        )
        self.next_pdf_page_button.clicked.connect(lambda: self._change_pdf_page(1))
        self._update_pdf_page_navigation()

        self.show_hidden_action = QAction(
            "Versteckte Dateien und Ordner anzeigen", self.window
        )
        self.show_hidden_action.setCheckable(True)
        self.show_hidden_action.setToolTip(
            "Versteckte Dateien und Ordner in der Dateiansicht anzeigen"
        )
        self.show_hidden_action.setStatusTip(
            "Versteckte Dateien und Ordner in der Dateiansicht anzeigen"
        )
        self.show_hidden_action.setChecked(self._show_hidden_files)
        self.show_hidden_action.toggled.connect(self._set_show_hidden_files)
        self.view_menu.addAction(self.show_hidden_action)

        self.view_menu.addSeparator()
        self.fit_image_action = QAction("Bild einpassen", self.window)
        self.fit_image_action.setShortcut(QKeySequence("0"))
        self.fit_image_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.fit_image_action.triggered.connect(self._fit_image_to_window)
        self.view_menu.addAction(self.fit_image_action)

        self.actual_size_action = QAction("Originalgröße", self.window)
        self.actual_size_action.setShortcut(QKeySequence("1"))
        self.actual_size_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.actual_size_action.triggered.connect(self._show_image_at_actual_size)
        self.view_menu.addAction(self.actual_size_action)

        self.view_menu.addSeparator()
        self.thumbnail_size_action = QAction(
            "Größe der Vorschaubilder …", self.window
        )
        self.thumbnail_size_action.triggered.connect(
            self._show_thumbnail_size_dialog
        )
        self.view_menu.addAction(self.thumbnail_size_action)

        self.increase_thumbnail_size_action = QAction(
            "Vorschaubilder vergrößern", self.window
        )
        self.increase_thumbnail_size_action.setShortcut(QKeySequence("Ctrl++"))
        self.increase_thumbnail_size_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.increase_thumbnail_size_action.triggered.connect(
            lambda: self._change_thumbnail_size(THUMBNAIL_STEP)
        )
        self.view_menu.addAction(self.increase_thumbnail_size_action)

        self.decrease_thumbnail_size_action = QAction(
            "Vorschaubilder verkleinern", self.window
        )
        self.decrease_thumbnail_size_action.setShortcut(QKeySequence("Ctrl+-"))
        self.decrease_thumbnail_size_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.decrease_thumbnail_size_action.triggered.connect(
            lambda: self._change_thumbnail_size(-THUMBNAIL_STEP)
        )
        self.view_menu.addAction(self.decrease_thumbnail_size_action)

        self.reset_thumbnail_size_action = QAction(
            "Vorschaubildgröße zurücksetzen", self.window
        )
        self.reset_thumbnail_size_action.setShortcut(QKeySequence("Ctrl+0"))
        self.reset_thumbnail_size_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.reset_thumbnail_size_action.triggered.connect(
            lambda: self._apply_thumbnail_size(THUMBNAIL_DEFAULT)
        )
        self.view_menu.addAction(self.reset_thumbnail_size_action)
        self._set_thumbnail_size_actions_enabled(True)

        self.view_menu.addSeparator()
        self.sort_menu = self.view_menu.addMenu("Sortieren nach")
        self.sort_criterion_action_group = QActionGroup(self.window)
        self.sort_criterion_action_group.setExclusive(True)
        for criterion, label in (
            ("name", "Dateiname"),
            ("recording_date", "Aufnahmedatum"),
            ("modified", "Änderungsdatum"),
            ("size", "Dateigröße"),
        ):
            action = QAction(label, self.window)
            action.setCheckable(True)
            action.setData(criterion)
            action.setChecked(criterion == self._sort_criterion)
            self.sort_criterion_action_group.addAction(action)
            self.sort_menu.addAction(action)
        self.sort_criterion_action_group.triggered.connect(
            self._set_sort_criterion
        )
        self.sort_menu.addSeparator()
        self.sort_direction_action_group = QActionGroup(self.window)
        self.sort_direction_action_group.setExclusive(True)
        for ascending, label in (
            (True, "Aufsteigend"),
            (False, "Absteigend"),
        ):
            action = QAction(label, self.window)
            action.setCheckable(True)
            action.setData(ascending)
            action.setChecked(ascending == self._sort_ascending)
            self.sort_direction_action_group.addAction(action)
            self.sort_menu.addAction(action)

        self.sort_direction_action_group.triggered.connect(
            self._set_sort_direction
        )

        self.view_menu.addSeparator()
        self.color_scheme_menu = self.view_menu.addMenu("Farbschema")
        self.color_scheme_action_group = QActionGroup(self.window)
        self.color_scheme_action_group.setExclusive(True)
        for scheme_name in COLOR_SCHEMES:
            action = QAction(scheme_name, self.window)
            action.setCheckable(True)
            action.setData(scheme_name)
            action.setChecked(scheme_name == self._color_scheme)
            self.color_scheme_action_group.addAction(action)
            self.color_scheme_menu.addAction(action)
        self.color_scheme_action_group.triggered.connect(self._set_color_scheme)
        self._apply_color_scheme()
        self._update_view_actions()

        self.navigation_menu = self.window.menuBar().addMenu("Navigation")
        self.previous_folder_action = QAction("Vorheriger Ordner", self.window)
        self.previous_folder_action.setShortcut(QKeySequence("Alt+Left"))
        self.previous_folder_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.previous_folder_action.setToolTip("Vorheriger Ordner (Alt+Links)")
        self.previous_folder_action.triggered.connect(self._go_to_previous_folder)
        self.navigation_menu.addAction(self.previous_folder_action)

        self.next_folder_action = QAction("Nächster Ordner", self.window)
        self.next_folder_action.setShortcut(QKeySequence("Alt+Right"))
        self.next_folder_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.next_folder_action.setToolTip("Nächster Ordner (Alt+Rechts)")
        self.next_folder_action.triggered.connect(self._go_to_next_folder)
        self.navigation_menu.addAction(self.next_folder_action)

        self.parent_folder_action = QAction("Übergeordneter Ordner", self.window)
        self.parent_folder_action.setShortcut(QKeySequence("Alt+Up"))
        self.parent_folder_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.parent_folder_action.setToolTip("Übergeordneter Ordner (Alt+Oben)")
        self.parent_folder_action.triggered.connect(self._go_to_parent_folder)
        self.navigation_menu.addAction(self.parent_folder_action)
        self.navigation_menu.addSeparator()

        self.first_image_action = QAction("Erstes Bild", self.window)
        self.first_image_action.setShortcut(QKeySequence("Home"))
        self.first_image_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.first_image_action.triggered.connect(
            lambda: self._select_slideshow_endpoint(False)
            if self._slideshow_running
            else self._select_image(0)
        )
        self.navigation_menu.addAction(self.first_image_action)

        self.previous_image_action = QAction("Vorheriges Bild", self.window)
        self.previous_image_action.setShortcut(QKeySequence("Left"))
        self.previous_image_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.previous_image_action.triggered.connect(
            lambda: self._select_relative_image(-1)
        )
        self.navigation_menu.addAction(self.previous_image_action)

        self.next_image_action = QAction("Nächstes Bild", self.window)
        self.next_image_action.setShortcut(QKeySequence("Right"))
        self.next_image_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.next_image_action.triggered.connect(lambda: self._select_relative_image(1))
        self.navigation_menu.addAction(self.next_image_action)

        self.last_image_action = QAction("Letztes Bild", self.window)
        self.last_image_action.setShortcut(QKeySequence("End"))
        self.last_image_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.last_image_action.triggered.connect(
            lambda: self._select_slideshow_endpoint(True)
            if self._slideshow_running
            else self._select_image(self.thumbnail_list.count() - 1)
        )
        self.navigation_menu.addAction(self.last_image_action)
        for action in (
            self.previous_folder_action,
            self.next_folder_action,
            self.parent_folder_action,
            self.first_image_action,
            self.previous_image_action,
            self.next_image_action,
            self.last_image_action,
        ):
            self.window.addAction(action)

        self._create_slideshow_menu()

        self.tools_menu = self.window.menuBar().addMenu("Werkzeuge")
        self.tools_menu.addAction(self.compare_images_action)
        self.tools_menu.addSeparator()
        self.find_duplicates_action = QAction(
            "Doppelte Bilder finden …", self.window
        )
        self.find_duplicates_action.triggered.connect(
            self._show_duplicate_finder
        )
        self.tools_menu.addAction(self.find_duplicates_action)

        self.help_menu = self.window.menuBar().addMenu("Hilfe")
        self.controls_help_action = QAction(
            "Bedienung und Tastenkürzel", self.window
        )
        self.controls_help_action.setShortcut(QKeySequence("F1"))
        self.controls_help_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.controls_help_action.triggered.connect(self._show_controls_help)
        self.help_menu.addAction(self.controls_help_action)

        self.about_action = QAction(f"Über {APP_NAME} …", self.window)
        self.about_action.triggered.connect(self._show_about)
        self.help_menu.addAction(self.about_action)

    def _update_view_actions(self) -> None:
        image_loaded = not self.original_image.isNull()
        self.fit_image_action.setEnabled(image_loaded)
        self.actual_size_action.setEnabled(image_loaded)
        self._set_file_manager_action_state(
            self.current_image if image_loaded else None
        )
        self._set_rename_action_state(
            self.current_image if image_loaded else None
        )
        self._set_rotation_action_states(
            self.current_image if image_loaded else None
        )
        has_selection = bool(self.thumbnail_list.selectedItems())
        self.trash_image_action.setEnabled(has_selection)
        self.copy_image_action.setEnabled(has_selection)
        self.cut_image_action.setEnabled(has_selection)
        self.export_resized_action.setEnabled(has_selection or image_loaded)
        self._update_print_action_state()
        self.multi_print_action.setEnabled(bool(self._all_thumbnail_image_paths()))
        self.contact_sheet_action.setEnabled(bool(self._all_thumbnail_image_paths()))
        self.compare_images_action.setEnabled(True)
        self.select_all_action.setEnabled(self.thumbnail_list.count() > 0)

    def _update_print_action_state(self) -> None:
        self.print_action.setEnabled(
            self.current_image is not None
            and self.current_image.is_file()
            and not self.original_image.isNull()
        )

    def _all_thumbnail_image_paths(self) -> list[Path]:
        return [
            Path(self.thumbnail_list.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self.thumbnail_list.count())
            if Path(self.thumbnail_list.item(row).data(Qt.ItemDataRole.UserRole)).is_file()
        ]

    def _show_multi_print_dialog(self, contact_sheet_default: bool = False) -> None:
        selected = [path for path in self._selected_image_paths() if path.is_file()]
        all_paths = self._all_thumbnail_image_paths()
        current = self.current_image if self.current_image and self.current_image.is_file() else None
        dialog = QDialog(self.window)
        dialog.setWindowTitle("Mehrere Bilder drucken — BildBlick")
        dialog.setMinimumSize(700, 560)
        main_layout = QVBoxLayout(dialog)
        dialog.setStyleSheet(dialog.styleSheet() + """
QLabel#multiPrintSourceLabel, QLabel#multiPrintOrientationLabel,
QLabel#multiPrintImagesPerPageLabel, QLabel#multiPrintRowsLabel,
QLabel#multiPrintColumnsLabel, QLabel#multiPrintPageMarginLabel,
QLabel#multiPrintImageSpacingLabel, QLabel#multiPrintHeaderTextLabel {
    color: #202020;
}
QLabel#multiPrintHeaderTextLabel:disabled { color: #777777; }
QLineEdit#multiPrintHeaderTextEdit { color: #202020; background: white; }
QLabel#multiPrintHelpLabel { color: #666666; font-size: 11px; }
""")
        splitter = QSplitter(Qt.Orientation.Horizontal, dialog)
        settings_scroll = QScrollArea(splitter)
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        settings_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        settings_scroll.setMinimumWidth(400)
        settings_widget = QWidget(settings_scroll)
        layout = QVBoxLayout(settings_widget)
        settings_scroll.setWidget(settings_widget)
        preview_panel = QWidget(splitter)
        preview_panel.setMinimumWidth(520)
        preview_layout = QVBoxLayout(preview_panel)
        main_layout.addWidget(splitter, 1)
        profile_group = QGroupBox("Profil", settings_widget)
        profile_form = QFormLayout(profile_group)
        profile_combo = QComboBox(profile_group)
        profile_definitions = (
            ("Standard", "standard", 4, False),
            ("4 Bilder", "4", 4, False),
            ("9 Bilder", "9", 9, False),
            ("16 Bilder", "16", 16, False),
            ("32 Bilder", "32", 32, False),
            ("Kontaktabzug 9", "contact-9", 9, True),
            ("Kontaktabzug 16", "contact-16", 16, True),
            ("Kontaktabzug 32", "contact-32", 32, True),
            ("Benutzerdefiniert", "custom", 0, False),
        )
        built_in_profiles = [
            MultiImagePrintProfile(
                profile_id,
                label,
                MultiImagePrintSettings(
                    orientation="automatic",
                    images_per_page=images_per_page,
                    custom_rows=4,
                    custom_columns=3,
                    page_margin_mm=5.0,
                    cell_spacing_mm=4.0,
                    contact_sheet=contact_sheet,
                    show_filename=True,
                    show_capture_date=False,
                    show_page_number=True,
                    show_header=False,
                    header_text="",
                    use_folder_name_as_title=False,
                    show_print_date=False,
                    show_folder_in_footer=False,
                ),
                built_in=True,
            )
            for label, profile_id, images_per_page, contact_sheet
            in profile_definitions[:-1]
        ]
        user_profiles_by_id = {}

        def rebuild_profile_combo(
            selected_profile_id: str | None = None,
        ) -> None:
            previous_data = profile_combo.currentData()
            blocker = QSignalBlocker(profile_combo)
            profile_combo.clear()
            for label, profile_id, images_per_page, contact_sheet in profile_definitions[:-1]:
                profile_combo.addItem(
                    label, (profile_id, images_per_page, contact_sheet)
                )
            user_profiles = load_user_profiles(self.settings)
            user_profiles_by_id.clear()
            user_profiles_by_id.update(
                {profile.profile_id: profile for profile in user_profiles}
            )
            selected_index = -1
            for profile in user_profiles:
                profile_combo.addItem(
                    profile.display_name, ("user", profile.profile_id)
                )
                if profile.profile_id == selected_profile_id:
                    selected_index = profile_combo.count() - 1
            profile_combo.addItem(
                profile_definitions[-1][0], profile_definitions[-1][1:]
            )
            if selected_index < 0 and previous_data is not None:
                selected_index = profile_combo.findData(previous_data)
            profile_combo.setCurrentIndex(max(0, selected_index))
            del blocker

        rebuild_profile_combo()
        profile_form.addRow("Profil:", profile_combo)
        save_profile_button = QPushButton("Speichern …", profile_group)
        delete_profile_button = QPushButton("Löschen", profile_group)
        delete_profile_button.setEnabled(False)
        profile_buttons = QHBoxLayout()
        profile_buttons.addWidget(save_profile_button)
        profile_buttons.addWidget(delete_profile_button)
        profile_form.addRow("", profile_buttons)
        layout.addWidget(profile_group)
        source_group = QGroupBox("Zu druckende Bilder", dialog)
        source_form = QFormLayout(source_group)
        source_combo = QComboBox(source_group)
        source_combo.addItem("Aktuelles Bild", "current")
        source_combo.addItem(f"Markierte Bilder ({len(selected)})", "selected")
        source_combo.addItem(f"Alle Bilder im Ordner ({len(all_paths)})", "all")
        configure_plain_combo_popup(source_combo, "multiPrintSourceCombo")
        source_label = QLabel("Quelle:", source_group); source_label.setObjectName("multiPrintSourceLabel")
        source_form.addRow(source_label, source_combo)
        layout.addWidget(source_group)
        options = QGroupBox("Layout", dialog)
        form = QFormLayout(options)
        orientation_combo = QComboBox(options)
        for label, value in (("Automatisch", "automatic"), ("Hochformat", "portrait"), ("Querformat", "landscape")):
            orientation_combo.addItem(label, value)
        configure_plain_combo_popup(orientation_combo, "multiPrintOrientationCombo")
        count_combo = QComboBox(options)
        for value in (1, 2, 4, 6, 9, 16, 32):
            count_combo.addItem(f"{value} Bild" if value == 1 else f"{value} Bilder", value)
        count_combo.addItem("Benutzerdefiniert …", 0)
        configure_plain_combo_popup(count_combo, "imagesPerPageCombo")
        orientation_label = QLabel("Papierausrichtung:", options); orientation_label.setObjectName("multiPrintOrientationLabel")
        count_label = QLabel("Bilder pro Seite:", options); count_label.setObjectName("multiPrintImagesPerPageLabel")
        form.addRow(orientation_label, orientation_combo)
        form.addRow(count_label, count_combo)
        custom_rows = QSpinBox(options); custom_rows.setRange(1, 12)
        custom_columns = QSpinBox(options); custom_columns.setRange(1, 12)
        page_margin = QDoubleSpinBox(options); page_margin.setRange(0, 30); page_margin.setSingleStep(0.5); page_margin.setDecimals(1); page_margin.setSuffix(" mm")
        cell_spacing = QDoubleSpinBox(options); cell_spacing.setRange(0, 20); cell_spacing.setSingleStep(0.5); cell_spacing.setDecimals(1); cell_spacing.setSuffix(" mm")
        rows_label = QLabel("Zeilen (vertikal):", options); rows_label.setObjectName("multiPrintRowsLabel")
        columns_label = QLabel("Spalten (horizontal):", options); columns_label.setObjectName("multiPrintColumnsLabel")
        form.addRow(rows_label, custom_rows); form.addRow(columns_label, custom_columns)
        page_margin_label = QLabel("Seitenrand:", dialog); page_margin_label.setObjectName("multiPrintPageMarginLabel")
        cell_spacing_label = QLabel("Bildabstand:", dialog); cell_spacing_label.setObjectName("multiPrintImageSpacingLabel")
        custom_hint = QLabel(options)
        margin_hint = QLabel("Abstand zwischen Druckbereich und äußerem Bild.", options)
        spacing_hint = QLabel("Abstand zwischen den einzelnen Bildern.", options)
        for hint in (custom_hint, margin_hint, spacing_hint):
            hint.setWordWrap(True)
            hint.setObjectName("multiPrintHelpLabel")
        form.addRow("", custom_hint)
        spacing_group = QGroupBox("Abstände", settings_widget)
        spacing_form = QFormLayout(spacing_group)
        spacing_form.addRow(page_margin_label, page_margin)
        spacing_form.addRow("", margin_hint)
        spacing_form.addRow(cell_spacing_label, cell_spacing)
        spacing_form.addRow("", spacing_hint)
        layout.addWidget(options)
        layout.addWidget(spacing_group)
        warning_group = QGroupBox("Hinweise", settings_widget)
        warning_layout = QVBoxLayout(warning_group)
        layout_warning = QLabel(warning_group); layout_warning.setWordWrap(True); layout_warning.hide()
        warning_layout.addWidget(layout_warning)
        warning_group.hide()
        caption_group = QGroupBox("Beschriftung (nur im Kontaktabzug)", dialog)
        caption_layout = QVBoxLayout(caption_group)
        contact_check = QCheckBox("Kontaktabzug", caption_group)
        filename_check = QCheckBox("Dateiname", caption_group)
        date_check = QCheckBox("Aufnahmedatum", caption_group)
        for check in (contact_check, filename_check, date_check):
            caption_layout.addWidget(check)
        layout.addWidget(caption_group)
        header_group = QGroupBox("Kopfzeile", settings_widget)
        header_form = QFormLayout(header_group)
        show_header_check = QCheckBox("Kopfzeile anzeigen", header_group)
        show_header_check.setObjectName("multiPrintShowHeaderCheckBox")
        header_text_label = QLabel("Überschrift:", header_group)
        header_text_label.setObjectName("multiPrintHeaderTextLabel")
        header_text_edit = QLineEdit(header_group)
        header_text_edit.setObjectName("multiPrintHeaderTextEdit")
        header_text_edit.setMaxLength(200)
        header_text_edit.setToolTip(
            "Diese Überschrift wird oben auf jeder gedruckten Seite angezeigt."
        )
        header_form.addRow(show_header_check)
        header_form.addRow(header_text_label, header_text_edit)
        use_folder_name_button = QPushButton(
            "Ordnername übernehmen", header_group
        )
        use_folder_name_button.setObjectName("multiPrintUseFolderNameButton")
        auto_folder_title_check = QCheckBox(
            "Ordnername automatisch verwenden", header_group
        )
        auto_folder_title_check.setObjectName(
            "multiPrintAutoFolderTitleCheckBox"
        )
        header_form.addRow("", use_folder_name_button)
        header_form.addRow("", auto_folder_title_check)
        layout.addWidget(header_group)
        footer_group = QGroupBox("Fußzeile", settings_widget)
        footer_layout = QVBoxLayout(footer_group)
        footer_folder_check = QCheckBox("Ordnername", footer_group)
        footer_folder_check.setObjectName("multiPrintFooterFolderCheckBox")
        footer_folder_check.setToolTip(
            "Zeigt den aktuellen Bildordner links in der Fußzeile."
        )
        page_number_check = QCheckBox("Seitenzahl", footer_group)
        page_number_check.setObjectName("multiPrintFooterPageNumberCheckBox")
        page_number_check.setToolTip("Zeigt die Seitenzahl in der Mitte.")
        print_date_check = QCheckBox("Druckdatum", footer_group)
        print_date_check.setObjectName("multiPrintFooterPrintDateCheckBox")
        print_date_check.setToolTip("Zeigt das Druckdatum rechts.")
        for check in (footer_folder_check, page_number_check, print_date_check):
            footer_layout.addWidget(check)
        layout.addWidget(footer_group)
        layout.addWidget(warning_group)
        preview = MultiImagePrintPreview(preview_panel)
        preview_layout.addWidget(preview, 1)
        navigation = QHBoxLayout()
        previous_button = QPushButton("◀", dialog)
        next_button = QPushButton("▶", dialog)
        page_label = QLabel(dialog)
        navigation.addStretch(1)
        navigation.addWidget(previous_button)
        navigation.addWidget(page_label)
        navigation.addWidget(next_button)
        navigation.addStretch(1)
        preview_layout.addLayout(navigation)
        buttons = QDialogButtonBox(dialog)
        buttons.addButton("Abbrechen", QDialogButtonBox.ButtonRole.RejectRole)
        continue_button = buttons.addButton("Weiter zum Druckdialog …", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        reset_button = QPushButton("Zurücksetzen", dialog)
        button_row = QHBoxLayout()
        button_row.addWidget(reset_button)
        button_row.addStretch(1)
        button_row.addWidget(buttons)
        main_layout.addLayout(button_row)

        def apply_initial_dialog_size() -> None:
            screen = dialog.screen() or QApplication.primaryScreen()
            available = screen.availableGeometry() if screen is not None else QRectF(
                0, 0, 1600, 1000
            ).toRect()
            maximum_width = max(640, int(available.width() * 0.94))
            maximum_height = max(480, int(available.height() * 0.94))
            margins = main_layout.contentsMargins()
            horizontal_extra = (
                margins.left() + margins.right() + splitter.handleWidth() + 24
            )
            vertical_extra = (
                margins.top() + margins.bottom() + main_layout.spacing() * 2 + 24
            )
            left_hint = settings_widget.sizeHint()
            left_width = max(400, left_hint.width() + 16)
            preview_width = max(520, preview.minimumWidth())
            available_content_width = max(1, maximum_width - horizontal_extra)
            if left_width + preview_width > available_content_width:
                left_width = min(
                    left_width, max(300, int(available_content_width * 0.45))
                )
                preview_width = max(280, available_content_width - left_width)
            settings_scroll.setMinimumWidth(left_width)
            preview_panel.setMinimumWidth(preview_width)
            navigation_height = navigation.sizeHint().height()
            button_height = button_row.sizeHint().height()
            desired_width = left_width + preview_width + horizontal_extra
            desired_height = max(
                left_hint.height(), preview.minimumHeight() + navigation_height
            ) + button_height + vertical_extra
            minimum_size = QSize(
                min(700, maximum_width), min(560, maximum_height)
            )
            dialog.setMinimumSize(minimum_size)
            saved_size = self.settings.value(MULTI_PRINT_DIALOG_SIZE_KEY, QSize())
            if (
                isinstance(saved_size, QSize)
                and saved_size.isValid()
                and saved_size.width() >= minimum_size.width()
                and saved_size.height() >= minimum_size.height()
            ):
                desired_size = saved_size.expandedTo(minimum_size)
            else:
                desired_size = QSize(desired_width, desired_height).expandedTo(
                    minimum_size
                )
            dialog.resize(
                min(desired_size.width(), maximum_width),
                min(desired_size.height(), maximum_height),
            )
            main_layout.activate()
            splitter_width = max(1, splitter.width() - splitter.handleWidth())
            saved_sizes = self.settings.value(MULTI_PRINT_SPLITTER_SIZES_KEY, [])
            if (
                isinstance(saved_sizes, list)
                and len(saved_sizes) == 2
                and all(isinstance(size, int) and size >= 200 for size in saved_sizes)
                and sum(saved_sizes) > 0
            ):
                left_ratio = saved_sizes[0] / sum(saved_sizes)
                if not 0.25 <= left_ratio <= 0.70:
                    left_ratio = left_width / max(1, left_width + preview_width)
            else:
                left_ratio = left_width / max(1, left_width + preview_width)
            splitter.setSizes([
                int(splitter_width * left_ratio),
                int(splitter_width * (1.0 - left_ratio)),
            ])

        apply_initial_dialog_size()
        default_source = "selected" if len(selected) > 1 else "current" if current else "all"
        source_combo.setCurrentIndex(max(0, source_combo.findData(self.settings.value(MULTI_PRINT_SOURCE_KEY, default_source, type=str))))
        orientation_combo.setCurrentIndex(max(0, orientation_combo.findData(self.settings.value(MULTI_PRINT_ORIENTATION_KEY, "automatic", type=str))))
        count_combo.setCurrentIndex(max(0, count_combo.findData(self.settings.value(MULTI_PRINT_IMAGES_PER_PAGE_KEY, 4, type=int))))
        custom_rows.setValue(min(12, max(1, self.settings.value(MULTI_PRINT_CUSTOM_ROWS_KEY, 4, type=int))))
        custom_columns.setValue(min(12, max(1, self.settings.value(MULTI_PRINT_CUSTOM_COLUMNS_KEY, 3, type=int))))
        page_margin.setValue(min(30, max(0, self.settings.value(MULTI_PRINT_PAGE_MARGIN_KEY, 5.0, type=float))))
        cell_spacing.setValue(min(20, max(0, self.settings.value(MULTI_PRINT_CELL_SPACING_KEY, 4.0, type=float))))
        contact_check.setChecked(contact_sheet_default or self.settings.value(MULTI_PRINT_CONTACT_SHEET_KEY, False, type=bool))
        filename_check.setChecked(self.settings.value(MULTI_PRINT_SHOW_FILENAME_KEY, True, type=bool))
        date_check.setChecked(self.settings.value(MULTI_PRINT_SHOW_CAPTURE_DATE_KEY, False, type=bool))
        page_number_check.setChecked(self.settings.value(MULTI_PRINT_SHOW_PAGE_NUMBER_KEY, True, type=bool))
        footer_folder_check.setChecked(
            self.settings.value(
                MULTI_PRINT_SHOW_FOLDER_IN_FOOTER_KEY, False, type=bool
            )
        )
        print_date_check.setChecked(
            self.settings.value(MULTI_PRINT_SHOW_PRINT_DATE_KEY, False, type=bool)
        )
        show_header_check.setChecked(
            self.settings.value(MULTI_PRINT_SHOW_HEADER_KEY, False, type=bool)
        )
        header_text_edit.setText(
            self.settings.value(MULTI_PRINT_HEADER_TEXT_KEY, "", type=str)
        )
        auto_folder_title_check.setChecked(
            self.settings.value(
                MULTI_PRINT_USE_FOLDER_NAME_AS_TITLE_KEY, False, type=bool
            )
        )
        filename_check.setEnabled(contact_check.isChecked())
        date_check.setEnabled(contact_check.isChecked())
        preview_page = [0]
        print_settings = MultiImagePrintSettings(
            show_header=self.settings.value(
                MULTI_PRINT_SHOW_HEADER_KEY, False, type=bool
            ),
            header_text=self.settings.value(
                MULTI_PRINT_HEADER_TEXT_KEY, "", type=str
            ),
            use_folder_name_as_title=self.settings.value(
                MULTI_PRINT_USE_FOLDER_NAME_AS_TITLE_KEY, False, type=bool
            ),
            show_print_date=self.settings.value(
                MULTI_PRINT_SHOW_PRINT_DATE_KEY, False, type=bool
            ),
            show_folder_in_footer=self.settings.value(
                MULTI_PRINT_SHOW_FOLDER_IN_FOOTER_KEY, False, type=bool
            ),
        )
        applying_profile = [False]
        profile_state_initialized = [False]

        def update_header_controls() -> None:
            enabled = show_header_check.isChecked()
            header_text_label.setEnabled(enabled)
            header_text_edit.setEnabled(enabled)
            use_folder_name_button.setEnabled(enabled)
            auto_folder_title_check.setEnabled(enabled)

        def current_folder_title() -> str:
            directory = self.current_directory
            if directory is None and self.current_image is not None:
                directory = self.current_image.parent
            return folder_title_from_path(directory)

        def set_folder_title(show_error: bool = False) -> bool:
            folder_title = current_folder_title()
            if not folder_title:
                if show_error:
                    run_without_application_stylesheet(
                        lambda: QMessageBox.information(
                            dialog,
                            "Kein Bildordner",
                            "Es ist derzeit kein Bildordner geöffnet.",
                        )
                    )
                return False
            blocker = QSignalBlocker(header_text_edit)
            header_text_edit.setText(folder_title)
            del blocker
            print_settings.header_text = folder_title
            return True

        update_header_controls()
        print_date_text = current_print_date_text()
        if print_settings.show_folder_in_footer:
            print_settings.footer_folder_name = current_folder_title()
        if auto_folder_title_check.isChecked():
            show_header_check.setChecked(True)
            set_folder_title()
            update_header_controls()

        def current_profile_id() -> str | None:
            profile_data = profile_combo.currentData()
            if not profile_data or profile_data[0] == "custom":
                return None
            return profile_data[1] if profile_data[0] == "user" else profile_data[0]

        def update_profile_state() -> None:
            if applying_profile[0]:
                return
            matching_profile = find_matching_profile(
                print_settings,
                built_in_profiles,
                list(user_profiles_by_id.values()),
                current_profile_id() if profile_state_initialized[0] else None,
            )
            if matching_profile is None:
                target_data = profile_definitions[-1][1:]
            elif matching_profile.built_in:
                definition = next(
                    item for item in profile_definitions
                    if item[1] == matching_profile.profile_id
                )
                target_data = definition[1:]
            else:
                target_data = ("user", matching_profile.profile_id)
            target_index = profile_combo.findData(target_data)
            if target_index >= 0 and target_index != profile_combo.currentIndex():
                blocker = QSignalBlocker(profile_combo)
                profile_combo.setCurrentIndex(target_index)
                del blocker
            delete_profile_button.setEnabled(
                matching_profile is not None and not matching_profile.built_in
            )
            profile_state_initialized[0] = True

        def preview_paths() -> list[Path]:
            source = source_combo.currentData()
            if source == "current":
                return [current] if current else []
            return selected if source == "selected" else all_paths

        def refresh_preview(reset_page: bool = True) -> None:
            if reset_page:
                preview_page[0] = 0
            paths = [path for path in preview_paths() if path.is_file()]
            print_settings.images_per_page = int(count_combo.currentData())
            print_settings.source = str(source_combo.currentData())
            print_settings.orientation = str(orientation_combo.currentData())
            print_settings.custom_rows = custom_rows.value()
            print_settings.custom_columns = custom_columns.value()
            print_settings.page_margin_mm = page_margin.value()
            print_settings.cell_spacing_mm = cell_spacing.value()
            print_settings.contact_sheet = contact_check.isChecked()
            print_settings.show_filename = filename_check.isChecked()
            print_settings.show_capture_date = date_check.isChecked()
            print_settings.show_page_number = page_number_check.isChecked()
            print_settings.show_print_date = print_date_check.isChecked()
            print_settings.show_folder_in_footer = footer_folder_check.isChecked()
            if not print_settings.show_folder_in_footer:
                print_settings.footer_folder_name = ""
            elif not print_settings.footer_folder_name:
                print_settings.footer_folder_name = current_folder_title()
            print_settings.show_header = show_header_check.isChecked()
            print_settings.header_text = header_text_edit.text()
            print_settings.use_folder_name_as_title = (
                auto_folder_title_check.isChecked()
            )
            images_per_page = print_settings.effective_images_per_page
            is_custom = print_settings.is_custom
            custom_rows.setVisible(is_custom); custom_columns.setVisible(is_custom)
            rows_label.setVisible(is_custom); columns_label.setVisible(is_custom)
            custom_hint.setVisible(is_custom)
            custom_hint.setText(f"{custom_rows.value()} × {custom_columns.value()} ergibt {images_per_page} Bilder pro Seite.")
            page_margin_label.setEnabled(True); cell_spacing_label.setEnabled(True)
            page_count = (len(paths) + images_per_page - 1) // images_per_page
            if page_count:
                preview_page[0] = min(preview_page[0], page_count - 1)
                page_label.setText(f"Seite {preview_page[0] + 1} von {page_count}")
            else:
                preview_page[0] = 0
                page_label.setText("Seite 0 von 0")
            orientation_value = orientation_combo.currentData()
            landscape = orientation_value == "landscape" or (
                orientation_value == "automatic" and images_per_page == 1
                and bool(paths) and QImageReader(str(paths[0])).size().width()
                > QImageReader(str(paths[0])).size().height()
            )
            preview.set_options(
                paths, print_settings, landscape, preview_page[0], print_date_text
            )
            sample = calculate_multi_image_page([QSize(1, 1)], QRectF(0, 0, 600, 800), images_per_page, 100, landscape, 0, settings=print_settings)
            messages = []
            if not sample.valid: messages.append("Mit diesen Einstellungen steht nicht genügend Platz für die Bilder zur Verfügung.")
            elif images_per_page > 32: messages.append("Bei diesem Raster können Bilder und Beschriftungen sehr klein werden.")
            if images_per_page > 64 and contact_check.isChecked(): messages.append("Für dieses Raster empfehlen wir nur den Dateinamen.")
            layout_warning.setText("\n".join(messages)); layout_warning.setVisible(bool(messages)); warning_group.setVisible(bool(messages))
            continue_button.setEnabled(sample.valid)
            previous_button.setEnabled(preview_page[0] > 0)
            next_button.setEnabled(preview_page[0] + 1 < page_count)
            update_profile_state()

        def apply_profile(index: int) -> None:
            profile_data = profile_combo.itemData(index)
            delete_profile_button.setEnabled(
                bool(profile_data) and profile_data[0] == "user"
            )
            if profile_data[0] == "user":
                profile = user_profiles_by_id[profile_data[1]]
                profile_values = profile.settings
                applying_profile[0] = True
                try:
                    blockers = [
                        QSignalBlocker(widget) for widget in (
                            orientation_combo, count_combo, custom_rows,
                            custom_columns, page_margin, cell_spacing,
                            contact_check, filename_check, date_check,
                            page_number_check, show_header_check,
                            header_text_edit, auto_folder_title_check,
                            footer_folder_check, print_date_check,
                        )
                    ]
                    orientation_combo.setCurrentIndex(max(0, orientation_combo.findData(profile_values.orientation)))
                    count_combo.setCurrentIndex(max(0, count_combo.findData(profile_values.images_per_page)))
                    custom_rows.setValue(profile_values.custom_rows); custom_columns.setValue(profile_values.custom_columns)
                    page_margin.setValue(profile_values.page_margin_mm); cell_spacing.setValue(profile_values.cell_spacing_mm)
                    contact_check.setChecked(profile_values.contact_sheet); filename_check.setChecked(profile_values.show_filename)
                    date_check.setChecked(profile_values.show_capture_date); page_number_check.setChecked(profile_values.show_page_number)
                    footer_folder_check.setChecked(
                        profile_values.show_folder_in_footer
                    )
                    print_date_check.setChecked(profile_values.show_print_date)
                    show_header_check.setChecked(
                        profile_values.show_header
                        or profile_values.use_folder_name_as_title
                    )
                    header_text_edit.setText(profile_values.header_text)
                    auto_folder_title_check.setChecked(
                        profile_values.use_folder_name_as_title
                    )
                    if profile_values.use_folder_name_as_title:
                        set_folder_title()
                    print_settings.show_print_date = profile_values.show_print_date
                    print_settings.show_folder_in_footer = (
                        profile_values.show_folder_in_footer
                    )
                    print_settings.footer_folder_name = (
                        current_folder_title()
                        if profile_values.show_folder_in_footer else ""
                    )
                    update_header_controls()
                    del blockers
                    refresh_preview()
                finally:
                    applying_profile[0] = False
                update_profile_state()
                return
            profile_id, images_per_page, contact_sheet = profile_data
            if profile_id == "custom":
                return
            applying_profile[0] = True
            try:
                blockers = [
                    QSignalBlocker(widget) for widget in (
                        orientation_combo, count_combo, custom_rows,
                        custom_columns, page_margin, cell_spacing,
                        contact_check, filename_check, date_check,
                        page_number_check, show_header_check,
                        header_text_edit, auto_folder_title_check,
                        footer_folder_check, print_date_check,
                    )
                ]
                orientation_combo.setCurrentIndex(0)
                count_combo.setCurrentIndex(
                    max(0, count_combo.findData(images_per_page))
                )
                custom_rows.setValue(4)
                custom_columns.setValue(3)
                page_margin.setValue(5.0)
                cell_spacing.setValue(4.0)
                contact_check.setChecked(contact_sheet)
                filename_check.setChecked(True)
                date_check.setChecked(False)
                page_number_check.setChecked(True)
                show_header_check.setChecked(False)
                header_text_edit.clear()
                auto_folder_title_check.setChecked(False)
                footer_folder_check.setChecked(False)
                print_date_check.setChecked(False)
                print_settings.show_print_date = False
                print_settings.show_folder_in_footer = False
                print_settings.footer_folder_name = ""
                update_header_controls()
                del blockers
                refresh_preview()
            finally:
                applying_profile[0] = False
            update_profile_state()

        source_combo.currentIndexChanged.connect(
            lambda _index: refresh_preview()
        )
        orientation_combo.currentIndexChanged.connect(
            lambda _index: refresh_preview()
        )
        count_combo.currentIndexChanged.connect(
            lambda _index: refresh_preview()
        )
        profile_combo.currentIndexChanged.connect(apply_profile)
        custom_rows.valueChanged.connect(lambda _value: refresh_preview())
        custom_columns.valueChanged.connect(lambda _value: refresh_preview())
        page_margin.valueChanged.connect(lambda _value: refresh_preview())
        cell_spacing.valueChanged.connect(lambda _value: refresh_preview())
        contact_check.toggled.connect(lambda checked: (filename_check.setEnabled(checked), date_check.setEnabled(checked), refresh_preview()))
        filename_check.toggled.connect(lambda _checked: refresh_preview())
        date_check.toggled.connect(lambda _checked: refresh_preview())
        page_number_check.toggled.connect(lambda _checked: refresh_preview())
        footer_folder_check.toggled.connect(lambda _checked: refresh_preview())
        print_date_check.toggled.connect(lambda _checked: refresh_preview())
        show_header_check.toggled.connect(
            lambda _checked: (update_header_controls(), refresh_preview())
        )
        def header_text_changed(_text: str) -> None:
            if auto_folder_title_check.isChecked():
                blocker = QSignalBlocker(auto_folder_title_check)
                auto_folder_title_check.setChecked(False)
                del blocker
            refresh_preview()

        def auto_folder_title_toggled(enabled: bool) -> None:
            if enabled:
                blockers = [
                    QSignalBlocker(widget) for widget in (
                        show_header_check, header_text_edit,
                    )
                ]
                show_header_check.setChecked(True)
                set_folder_title()
                del blockers
            update_header_controls()
            refresh_preview()

        def use_folder_name() -> None:
            if set_folder_title(show_error=True):
                refresh_preview()

        header_text_edit.textChanged.connect(header_text_changed)
        auto_folder_title_check.toggled.connect(auto_folder_title_toggled)
        use_folder_name_button.clicked.connect(use_folder_name)
        def reset_options() -> None:
            applying_profile[0] = True
            try:
                blockers = [
                    QSignalBlocker(widget) for widget in (
                        profile_combo, source_combo, orientation_combo,
                        count_combo, custom_rows, custom_columns, page_margin,
                        cell_spacing, contact_check, filename_check, date_check,
                        page_number_check, show_header_check,
                        header_text_edit, auto_folder_title_check,
                        footer_folder_check, print_date_check,
                    )
                ]
                profile_combo.setCurrentIndex(0)
                source_combo.setCurrentIndex(max(0, source_combo.findData(default_source)))
                orientation_combo.setCurrentIndex(0)
                count_combo.setCurrentIndex(max(0, count_combo.findData(4)))
                custom_rows.setValue(4); custom_columns.setValue(3)
                page_margin.setValue(5.0); cell_spacing.setValue(4.0)
                contact_check.setChecked(False); filename_check.setChecked(True)
                date_check.setChecked(False); page_number_check.setChecked(True)
                show_header_check.setChecked(False)
                header_text_edit.clear()
                auto_folder_title_check.setChecked(False)
                footer_folder_check.setChecked(False)
                print_date_check.setChecked(False)
                update_header_controls()
                del blockers
            finally:
                applying_profile[0] = False
            refresh_preview()
        reset_button.clicked.connect(reset_options)

        def save_current_profile() -> None:
            entered_name, accepted = run_without_application_stylesheet(
                lambda: QInputDialog.getText(
                    dialog,
                    "Druckprofil speichern",
                    "Name des Profils:",
                )
            )
            if not accepted:
                return
            profile_name = normalize_profile_name(entered_name)
            if not profile_name:
                run_without_application_stylesheet(
                    lambda: QMessageBox.warning(
                        dialog,
                        "Ungültiger Profilname",
                        "Bitte geben Sie einen Namen für das Druckprofil ein.",
                    )
                )
                return
            if is_reserved_profile_name(profile_name):
                run_without_application_stylesheet(
                    lambda: QMessageBox.warning(
                        dialog,
                        "Ungültiger Profilname",
                        "Dieser Name ist für ein eingebautes Druckprofil reserviert.\n"
                        "Bitte wählen Sie einen anderen Namen.",
                    )
                )
                return
            existing_profiles = load_user_profiles(self.settings)
            existing_profile = next(
                (
                    item for item in existing_profiles
                    if normalize_profile_name(item.display_name).casefold()
                    == profile_name.casefold()
                ),
                None,
            )
            updated = existing_profile is not None
            if existing_profile is not None:
                confirmation = QMessageBox(dialog)
                confirmation.setWindowTitle("Profil überschreiben")
                confirmation.setText(
                    "Ein Benutzerprofil mit diesem Namen existiert bereits.\n"
                    "Möchten Sie es überschreiben?"
                )
                confirmation.setStandardButtons(
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.Cancel
                )
                confirmation.button(QMessageBox.StandardButton.Yes).setText(
                    "Überschreiben"
                )
                confirmation.button(QMessageBox.StandardButton.Cancel).setText(
                    "Abbrechen"
                )
                if run_without_application_stylesheet(
                    confirmation.exec
                ) != QMessageBox.StandardButton.Yes:
                    return
            try:
                profile = (
                    overwrite_user_profile(
                        existing_profile, profile_name, print_settings
                    )
                    if existing_profile is not None
                    else create_user_profile(profile_name, print_settings)
                )
                save_user_profile(self.settings, profile)
                self.settings.sync()
                if self.settings.status() != QSettings.Status.NoError:
                    raise RuntimeError("QSettings konnte nicht geschrieben werden.")
                rebuild_profile_combo(profile.profile_id)
                delete_profile_button.setEnabled(True)
            except Exception:
                run_without_application_stylesheet(
                    lambda: QMessageBox.critical(
                        dialog,
                        "Druckprofil konnte nicht gespeichert werden",
                        "Das Druckprofil konnte nicht dauerhaft gespeichert werden.",
                    )
                )
                return
            run_without_application_stylesheet(
                lambda: QMessageBox.information(
                    dialog,
                    "Druckprofil gespeichert",
                    f"Das Druckprofil ‚{profile_name}‘ wurde "
                    f"{'aktualisiert' if updated else 'gespeichert'}.",
                )
            )

        save_profile_button.clicked.connect(save_current_profile)

        def delete_selected_profile() -> None:
            profile_data = profile_combo.currentData()
            if not profile_data or profile_data[0] != "user":
                return
            profile = user_profiles_by_id.get(profile_data[1])
            if profile is None:
                return
            confirmation = QMessageBox(dialog)
            confirmation.setWindowTitle("Druckprofil löschen")
            confirmation.setText(
                f"Möchten Sie das Profil ‚{profile.display_name}‘ wirklich löschen?"
            )
            confirmation.setStandardButtons(
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.Cancel
            )
            confirmation.button(QMessageBox.StandardButton.Yes).setText("Löschen")
            confirmation.button(QMessageBox.StandardButton.Cancel).setText(
                "Abbrechen"
            )
            if run_without_application_stylesheet(
                confirmation.exec
            ) != QMessageBox.StandardButton.Yes:
                return
            if not delete_user_profile(self.settings, profile.profile_id):
                run_without_application_stylesheet(
                    lambda: QMessageBox.critical(
                        dialog,
                        "Druckprofil konnte nicht gelöscht werden",
                        "Das Druckprofil konnte nicht dauerhaft gelöscht werden.",
                    )
                )
                return
            rebuild_profile_combo()
            profile_combo.setCurrentIndex(0)
            apply_profile(0)

        delete_profile_button.clicked.connect(delete_selected_profile)
        previous_button.clicked.connect(
            lambda: (preview_page.__setitem__(0, preview_page[0] - 1), refresh_preview(False))
        )
        next_button.clicked.connect(
            lambda: (preview_page.__setitem__(0, preview_page[0] + 1), refresh_preview(False))
        )
        QTimer.singleShot(0, refresh_preview)
        def update_automatic_folder_titles(_directory: Path) -> None:
            update_required = False
            if auto_folder_title_check.isChecked() and set_folder_title():
                update_required = True
            if footer_folder_check.isChecked():
                print_settings.footer_folder_name = current_folder_title()
                update_required = True
            if update_required:
                refresh_preview()

        self.folder_changed.connect(update_automatic_folder_titles)
        dialog_result = dialog.exec()
        self.folder_changed.disconnect(update_automatic_folder_titles)
        self.settings.setValue(MULTI_PRINT_SPLITTER_SIZES_KEY, splitter.sizes())
        self.settings.setValue(MULTI_PRINT_DIALOG_SIZE_KEY, dialog.size())
        if dialog_result != QDialog.DialogCode.Accepted:
            return
        source = source_combo.currentData()
        paths = [current] if source == "current" and current else selected if source == "selected" else all_paths
        paths = [path for path in paths if path is not None and path.is_file()]
        if not paths:
            QMessageBox.information(self.window, "Keine Bilder zum Drucken", "Es wurden keine gültigen Bilder zum Drucken gefunden.")
            return
        self.settings.setValue(MULTI_PRINT_SOURCE_KEY, source)
        self.settings.setValue(MULTI_PRINT_ORIENTATION_KEY, orientation_combo.currentData())
        self.settings.setValue(MULTI_PRINT_IMAGES_PER_PAGE_KEY, count_combo.currentData())
        self.settings.setValue(MULTI_PRINT_CUSTOM_ROWS_KEY, custom_rows.value())
        self.settings.setValue(MULTI_PRINT_CUSTOM_COLUMNS_KEY, custom_columns.value())
        self.settings.setValue(MULTI_PRINT_PAGE_MARGIN_KEY, page_margin.value())
        self.settings.setValue(MULTI_PRINT_CELL_SPACING_KEY, cell_spacing.value())
        self.settings.setValue(MULTI_PRINT_CONTACT_SHEET_KEY, contact_check.isChecked())
        self.settings.setValue(MULTI_PRINT_SHOW_FILENAME_KEY, filename_check.isChecked())
        self.settings.setValue(MULTI_PRINT_SHOW_CAPTURE_DATE_KEY, date_check.isChecked())
        self.settings.setValue(MULTI_PRINT_SHOW_PAGE_NUMBER_KEY, page_number_check.isChecked())
        self.settings.setValue(MULTI_PRINT_SHOW_HEADER_KEY, print_settings.show_header)
        self.settings.setValue(MULTI_PRINT_HEADER_TEXT_KEY, print_settings.header_text)
        self.settings.setValue(
            MULTI_PRINT_USE_FOLDER_NAME_AS_TITLE_KEY,
            print_settings.use_folder_name_as_title,
        )
        self.settings.setValue(
            MULTI_PRINT_SHOW_PRINT_DATE_KEY, print_settings.show_print_date
        )
        self.settings.setValue(
            MULTI_PRINT_SHOW_FOLDER_IN_FOOTER_KEY,
            print_settings.show_folder_in_footer,
        )
        self._print_multiple_images(paths, print_settings)

    def _print_multiple_images(self, paths: list[Path], print_settings: MultiImagePrintSettings) -> None:
        images_per_page = print_settings.effective_images_per_page
        first = QImageReader(str(paths[0])); first.setAutoTransform(True); first_image = first.read()
        orientation = QPageLayout.Orientation.Landscape if print_settings.orientation == "landscape" or (print_settings.orientation == "automatic" and images_per_page == 1 and first_image.width() > first_image.height()) else QPageLayout.Orientation.Portrait
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        page_layout = printer.pageLayout(); page_layout.setOrientation(orientation); printer.setPageLayout(page_layout)
        print_dialog = QPrintDialog(printer, self.window)
        accepted = run_without_application_stylesheet(
            print_dialog.exec
        ) == QDialog.DialogCode.Accepted
        if not accepted: return
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.critical(self.window, "Drucken fehlgeschlagen", "Der Druckauftrag konnte nicht gestartet werden."); return
        failures = []
        capture_dates: dict[Path, str] = {}
        print_date_text = current_print_date_text()
        try:
            sizes = []
            for path in paths:
                reader = QImageReader(str(path))
                reader.setAutoTransform(True)
                image_size = reader.size()
                sizes.append(image_size if image_size.isValid() else QSize(1, 1))
            viewport = painter.viewport(); drawable = QRectF(0, 0, viewport.width(), viewport.height())
            landscape = orientation == QPageLayout.Orientation.Landscape
            validation_layout = calculate_multi_image_page(
                sizes, drawable, images_per_page, printer.resolution(),
                landscape, 0, settings=print_settings,
            )
            if not validation_layout.valid:
                raise MultiImagePrintLayoutError()
            page_count = (len(paths) + images_per_page - 1) // images_per_page
            for page in range(page_count):
                page_layout_data = calculate_multi_image_page(sizes, drawable, images_per_page, printer.resolution(), landscape, page, settings=print_settings)
                draw_multi_print_header(painter, page_layout_data, print_settings)
                for cell in page_layout_data.cells:
                    image = load_multi_print_image(
                        paths[cell.image_index], cell.image_rect,
                        printer.resolution(),
                    )
                    if image.isNull(): failures.append(paths[cell.image_index].name); continue
                    painter.fillRect(cell.rect, Qt.GlobalColor.white); painter.drawImage(cell.image_rect, image)
                    font = QFont(painter.font()); font.setPointSizeF(max(5, 12 - images_per_page / 2)); painter.setFont(font); painter.setPen(Qt.GlobalColor.black)
                    if print_settings.show_filename and not cell.filename_rect.isEmpty():
                        text = painter.fontMetrics().elidedText(paths[cell.image_index].name, Qt.TextElideMode.ElideMiddle, int(cell.filename_rect.width()))
                        painter.drawText(cell.filename_rect, Qt.AlignmentFlag.AlignCenter, text)
                    if print_settings.show_capture_date and not cell.date_rect.isEmpty():
                        path = paths[cell.image_index]
                        date = capture_dates.setdefault(path, capture_date_text(path))
                        painter.drawText(cell.date_rect, Qt.AlignmentFlag.AlignCenter, date)
                draw_multi_print_footer(
                    painter,
                    page_layout_data,
                    print_settings,
                    page + 1,
                    page_count,
                    print_date_text,
                )
                if page < page_count - 1 and not printer.newPage(): raise RuntimeError("Eine neue Druckseite konnte nicht erzeugt werden.")
        except MultiImagePrintLayoutError:
            if painter.isActive():
                painter.end()
            printer.abort()
            QMessageBox.warning(
                self.window,
                "Drucklayout nicht möglich",
                "Mit den gewählten Seitenrändern, Bildabständen und dem aktuellen "
                "Papierformat steht nicht genügend Platz für die Bilder zur Verfügung.\n\n"
                "Bitte verringern Sie Seitenrand oder Bildabstand oder wählen Sie ein "
                "größeres Papierformat.",
            )
            return
        except Exception as error:
            QMessageBox.critical(self.window, "Drucken fehlgeschlagen", str(error))
        finally:
            if painter.isActive():
                painter.end()
        if failures:
            QMessageBox.warning(self.window, "Einige Bilder konnten nicht geladen werden", "\n".join(failures))

    def _print_current_image(self) -> None:
        if (
            self.current_image is None
            or not self.current_image.is_file()
            or self.original_image.isNull()
        ):
            self._update_print_action_state()
            QMessageBox.information(
                self.window, "Kein Bild geöffnet",
                "Bitte öffnen oder markieren Sie zuerst ein Bild.",
            )
            return

        try:
            reader = QImageReader(str(self.current_image))
            reader.setAutoTransform(True)
            image = reader.read()
            if image.isNull():
                detail = reader.errorString() or "Unbekannter Ladefehler"
                raise RuntimeError(detail)
            image = rotated_display_image(
                image, self._current_display_rotation()
            )
            if image.isNull():
                raise RuntimeError(
                    "Das gedrehte Druckbild konnte nicht erzeugt werden."
                )

            settings_dialog = PrintSettingsDialog(
                image,
                image_print_dpi(self.current_image),
                self.settings,
                COLOR_SCHEMES[self._color_scheme],
                self.window,
            )
            if settings_dialog.exec() != QDialog.DialogCode.Accepted:
                return
            orientation = settings_dialog.selected_orientation()
            size_mode = settings_dialog.size_mode()
            centered = settings_dialog.centered()
            image_dpi = settings_dialog.image_dpi
            image = rotated_display_image(
                image, settings_dialog.additional_rotation()
            )
            if image.isNull():
                raise RuntimeError(
                    "Das Druckbild konnte nicht erzeugt werden."
                )

            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            page_layout = printer.pageLayout()
            page_layout.setOrientation(orientation)
            if size_mode == "a4":
                page_layout.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            printer.setPageLayout(page_layout)

            layout_mode = "fit" if size_mode == "a4" else size_mode
            printable_size = printer.pageRect(QPrinter.Unit.DevicePixel).size()
            preflight_layout = calculate_print_layout(
                image.size(), QRectF(0.0, 0.0, printable_size.width(), printable_size.height()),
                layout_mode, printer.resolution(), image_dpi, centered,
            )
            if layout_mode == "original" and preflight_layout.outside_page:
                choice = QMessageBox.question(
                    self.window, "Originalgröße zu groß",
                    "Das Bild ist in Originalgröße größer als die bedruckbare Seite.\n"
                    "Soll es stattdessen passend verkleinert werden?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Yes,
                )
                if choice == QMessageBox.StandardButton.Cancel:
                    return
                if choice == QMessageBox.StandardButton.Yes:
                    layout_mode = "fit"
            print_dialog = QPrintDialog(printer, self.window)
            print_dialog.setWindowTitle("Bild drucken")
            print_result = run_without_application_stylesheet(
                print_dialog.exec
            )
            if print_result != QDialog.DialogCode.Accepted:
                return

            page_layout = printer.pageLayout()
            page_layout.setOrientation(orientation)
            if size_mode == "a4":
                page_layout.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            printer.setPageLayout(page_layout)

            painter = QPainter()
            if not painter.begin(printer):
                raise RuntimeError("Der Druckauftrag konnte nicht gestartet werden.")
            try:
                viewport = painter.viewport()
                drawable_rect = QRectF(
                    0.0,
                    0.0,
                    float(viewport.width()),
                    float(viewport.height()),
                )
                layout = calculate_print_layout(
                    image.size(), drawable_rect, layout_mode,
                    printer.resolution(), image_dpi, centered,
                )
                draw_print_layout(painter, image, drawable_rect, layout)
            finally:
                if painter.isActive() and not painter.end():
                    raise RuntimeError(
                        "Der Druckauftrag konnte nicht abgeschlossen werden."
                    )
        except Exception as error:
            dialog = QMessageBox(self.window)
            dialog.setWindowTitle("Drucken fehlgeschlagen")
            dialog.setIcon(QMessageBox.Icon.Critical)
            dialog.setText("Das aktuelle Bild konnte nicht gedruckt werden.")
            dialog.setInformativeText(str(error))
            dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
            dialog.button(QMessageBox.StandardButton.Ok).setText("OK")
            self._style_message_box(dialog)
            dialog.exec()

    def _set_file_manager_action_state(self, image_path: Path | None) -> None:
        self.show_in_file_manager_action.setEnabled(
            image_path is not None and image_path.is_file()
        )

    def _set_rename_action_state(self, image_path: Path | None) -> None:
        self.rename_image_action.setEnabled(
            image_path is not None
            and image_path.is_file()
            and image_path.suffix.lower() in IMAGE_EXTENSIONS
            and image_path.parent.is_dir()
            and os.access(image_path.parent, os.W_OK | os.X_OK)
        )

    def _set_rotation_action_states(self, image_path: Path | None) -> None:
        image_available = (
            image_path is not None
            and image_path.suffix.lower() in IMAGE_EXTENSIONS
            and image_path.is_file()
        )
        rotation = self._current_display_rotation(image_path)
        rotation_pending = image_available and rotation != 0
        self.rotate_left_action.setEnabled(image_available)
        self.rotate_right_action.setEnabled(image_available)
        self.reset_rotation_action.setEnabled(rotation_pending)
        self.save_rotated_copy_action.setEnabled(rotation_pending)
        original_format_supported = (
            image_path is not None
            and self._save_format_for_path(image_path) is not None
        )
        self.save_rotation_to_original_action.setEnabled(
            rotation_pending and original_format_supported
        )

    def _set_sort_criterion(self, action: QAction) -> None:
        self._sort_criterion = str(action.data())
        self.settings.setValue(SORT_CRITERION_KEY, self._sort_criterion)
        self.settings.sync()
        self._request_thumbnail_sort()

    def _set_sort_direction(self, action: QAction) -> None:
        self._sort_ascending = bool(action.data())
        self.settings.setValue(SORT_ASCENDING_KEY, self._sort_ascending)
        self.settings.sync()
        self._request_thumbnail_sort()

    def _resolved_sort_path(self, path: Path) -> str:
        raw_path = str(path)
        cached_path = self._resolved_sort_path_cache.get(raw_path)
        if cached_path is not None:
            return cached_path
        try:
            resolved_path = str(path.resolve(strict=False))
        except (OSError, RuntimeError):
            resolved_path = str(path.absolute())
        self._resolved_sort_path_cache[raw_path] = resolved_path
        return resolved_path

    @staticmethod
    def _recording_date_from_tooltip(tooltip: str) -> datetime | None:
        prefix = "Aufgenommen: "
        for line in tooltip.splitlines():
            if not line.startswith(prefix):
                continue
            try:
                return datetime.strptime(
                    line.removeprefix(prefix), "%d.%m.%Y, %H:%M"
                )
            except ValueError:
                return None
        return None

    def _compare_names(self, first: Path, second: Path) -> int:
        first_parts = re.split(r"(\d+)", first.name.casefold())
        second_parts = re.split(r"(\d+)", second.name.casefold())
        result = 0
        for first_part, second_part in zip(first_parts, second_parts):
            if first_part.isdigit() and second_part.isdigit():
                first_number = int(first_part)
                second_number = int(second_part)
                result = (first_number > second_number) - (
                    first_number < second_number
                )
            else:
                result = self._name_collator.compare(first_part, second_part)
            if result != 0:
                break
        if result == 0:
            result = (len(first_parts) > len(second_parts)) - (
                len(first_parts) < len(second_parts)
            )
        if result == 0:
            result = self._name_collator.compare(
                self._resolved_sort_path(first),
                self._resolved_sort_path(second),
            )
        return result

    def _compare_sort_paths(self, first: Path, second: Path) -> int:
        first_key = self._resolved_sort_path(first)
        second_key = self._resolved_sort_path(second)

        if self._sort_criterion == "name":
            result = self._compare_names(first, second)
        elif self._sort_criterion == "recording_date":
            first_value = self._recording_date_cache.get(first_key)
            second_value = self._recording_date_cache.get(second_key)
            if first_value is None and second_value is not None:
                return 1
            if first_value is not None and second_value is None:
                return -1
            if first_value is None:
                result = self._compare_names(first, second)
            else:
                result = (first_value > second_value) - (
                    first_value < second_value
                )
                if result == 0:
                    result = self._compare_names(first, second)
        else:
            metadata_index = 1 if self._sort_criterion == "modified" else 0
            first_metadata = self._file_sort_metadata.get(first_key)
            second_metadata = self._file_sort_metadata.get(second_key)
            if first_metadata is None and second_metadata is not None:
                return 1
            if first_metadata is not None and second_metadata is None:
                return -1
            if first_metadata is None:
                result = self._compare_names(first, second)
            else:
                first_value = first_metadata[metadata_index]
                second_value = second_metadata[metadata_index]
                result = (first_value > second_value) - (
                    first_value < second_value
                )
                if result == 0:
                    result = self._compare_names(first, second)

        return result if self._sort_ascending else -result

    def _sorted_paths(self, paths: list[Path]) -> list[Path]:
        return sorted(paths, key=cmp_to_key(self._compare_sort_paths))

    def _request_thumbnail_sort(self) -> None:
        self._capture_sort_waiting = (
            self._sort_criterion == "recording_date"
            and self._completed_jobs < len(self._pending_images)
        )
        if self._capture_sort_waiting:
            self._set_file_name_text("Aufnahmedaten werden gelesen …")
        self._sort_thumbnail_items()

    def _sort_thumbnail_items(self) -> None:
        if self.thumbnail_list.count() < 2:
            self._update_navigation_buttons()
            return

        selected_paths = {
            self._resolved_sort_path(
                Path(item.data(Qt.ItemDataRole.UserRole))
            )
            for item in self.thumbnail_list.selectedItems()
        }
        current_path = (
            self._resolved_sort_path(self.current_image)
            if self.current_image is not None
            else None
        )
        signals_were_blocked = self.thumbnail_list.blockSignals(True)
        current_item = None
        try:
            items = [
                self.thumbnail_list.takeItem(0)
                for _ in range(self.thumbnail_list.count())
            ]
            items.sort(
                key=cmp_to_key(
                    lambda first, second: self._compare_sort_paths(
                        Path(first.data(Qt.ItemDataRole.UserRole)),
                        Path(second.data(Qt.ItemDataRole.UserRole)),
                    )
                )
            )
            for index, item in enumerate(items):
                self.thumbnail_list.insertItem(index, item)
                item_path = self._resolved_sort_path(
                    Path(item.data(Qt.ItemDataRole.UserRole))
                )
                item.setSelected(item_path in selected_paths)
                if item_path == current_path:
                    current_item = item
            if current_item is not None:
                self.thumbnail_list.setCurrentItem(
                    current_item,
                    QItemSelectionModel.SelectionFlag.NoUpdate,
                )
        finally:
            self.thumbnail_list.blockSignals(signals_were_blocked)

        if current_item is not None:
            self.thumbnail_list.scrollToItem(current_item)
        self._update_navigation_buttons()
        self._update_view_actions()

    def _set_color_scheme(self, action: QAction) -> None:
        self._color_scheme = str(action.data())
        self.settings.setValue(COLOR_SCHEME_KEY, self._color_scheme)
        self.settings.sync()
        self._apply_color_scheme()

    def _apply_color_scheme(self) -> None:
        application = QApplication.instance()
        if application is not None:
            application.setStyleSheet(
                color_scheme_stylesheet(COLOR_SCHEMES[self._color_scheme])
            )

    def _style_message_box(self, dialog: QMessageBox) -> None:
        self._restore_slideshow_cursor()
        dialog.setStyleSheet(
            message_box_stylesheet(COLOR_SCHEMES[self._color_scheme])
        )
        dialog.finished.connect(
            lambda _result: QTimer.singleShot(
                0, self._restart_slideshow_cursor_timer
            )
        )

    def _show_thumbnail_size_dialog(self) -> None:
        dialog = QDialog(self.window)
        dialog.setWindowTitle("Größe der Vorschaubilder")
        dialog.setModal(True)
        dialog.setMinimumWidth(390)
        layout = QVBoxLayout(dialog)
        value_label = QLabel(f"{self._thumbnail_pixels} Pixel")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(value_label)

        slider_row = QHBoxLayout()
        slider_row.addWidget(QLabel("Klein"))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(
            0, (THUMBNAIL_MAXIMUM - THUMBNAIL_MINIMUM) // THUMBNAIL_STEP
        )
        slider.setSingleStep(1)
        slider.setPageStep(1)
        slider.setValue(
            (self._thumbnail_pixels - THUMBNAIL_MINIMUM) // THUMBNAIL_STEP
        )
        slider.valueChanged.connect(
            lambda step: value_label.setText(
                f"{THUMBNAIL_MINIMUM + step * THUMBNAIL_STEP} Pixel"
            )
        )
        slider_row.addWidget(slider, 1)
        slider_row.addWidget(QLabel("Groß"))
        layout.addLayout(slider_row)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        apply_button = QPushButton("Übernehmen")
        cancel_button = QPushButton("Abbrechen")
        cancel_button.setDefault(True)
        apply_button.clicked.connect(dialog.accept)
        cancel_button.clicked.connect(dialog.reject)
        button_row.addWidget(apply_button)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)
        dialog.setStyleSheet(
            message_box_stylesheet(COLOR_SCHEMES[self._color_scheme])
        )

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        pixels = THUMBNAIL_MINIMUM + slider.value() * THUMBNAIL_STEP
        self._apply_thumbnail_size(pixels)

    def _change_thumbnail_size(self, difference: int) -> None:
        self._apply_thumbnail_size(self._thumbnail_pixels + difference)

    def _set_thumbnail_size_actions_enabled(self, enabled: bool) -> None:
        self.thumbnail_size_action.setEnabled(enabled)
        self.increase_thumbnail_size_action.setEnabled(
            enabled and self._thumbnail_pixels < THUMBNAIL_MAXIMUM
        )
        self.decrease_thumbnail_size_action.setEnabled(
            enabled and self._thumbnail_pixels > THUMBNAIL_MINIMUM
        )
        self.reset_thumbnail_size_action.setEnabled(
            enabled and self._thumbnail_pixels != THUMBNAIL_DEFAULT
        )
        self.thumbnail_size_decrease_button.setEnabled(
            enabled and self._thumbnail_pixels > THUMBNAIL_MINIMUM
        )
        self.thumbnail_size_slider.setEnabled(enabled)
        self.thumbnail_size_increase_button.setEnabled(
            enabled and self._thumbnail_pixels < THUMBNAIL_MAXIMUM
        )

    def _sync_thumbnail_size_slider(self) -> None:
        blocker = QSignalBlocker(self.thumbnail_size_slider)
        self.thumbnail_size_slider.setValue(
            thumbnail_size_slider_value(self._thumbnail_pixels)
        )
        del blocker

    def _apply_thumbnail_size(self, pixels: int) -> None:
        pixels = normalized_thumbnail_pixels(pixels)
        if pixels == self._thumbnail_pixels:
            self._sync_thumbnail_size_slider()
            self._set_thumbnail_size_actions_enabled(True)
            return
        self._thumbnail_pixels = pixels
        self._thumbnail_size = thumbnail_size_for_pixels(pixels)
        self._thumbnail_grid_size = thumbnail_grid_size_for_pixels(pixels)
        self.settings.setValue(THUMBNAIL_SIZE_KEY, pixels)
        self.settings.sync()
        self._sync_thumbnail_size_slider()

        self.thread_pool.clear()
        self._load_generation += 1
        generation = self._load_generation
        self._pending_images = [
            Path(self.thumbnail_list.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self.thumbnail_list.count())
        ]
        self._next_job_index = 0
        self._completed_jobs = 0
        self._active_jobs = 0
        self.thumbnail_list.setIconSize(self._thumbnail_size)
        self.thumbnail_list.setGridSize(self._thumbnail_grid_size)
        for row in range(self.thumbnail_list.count()):
            item = self.thumbnail_list.item(row)
            item.setSizeHint(self._thumbnail_grid_size)
        current_item = self.thumbnail_list.currentItem()
        if current_item is not None:
            self.thumbnail_list.scrollToItem(current_item)
        self._update_loading_text()
        self._start_more_thumbnail_jobs(generation)

    def _show_duplicate_finder(self) -> None:
        initial_directory = self.current_directory or self.start_directory
        dialog = DuplicateFinderDialog(
            self.window,
            initial_directory,
            IMAGE_EXTENSIONS,
            self._refresh_after_duplicate_trash,
        )
        dialog.setStyleSheet(
            message_box_stylesheet(COLOR_SCHEMES[self._color_scheme])
        )
        dialog.exec()

    def _refresh_after_duplicate_trash(self, trashed_paths: list[Path]) -> None:
        if self.current_directory is None:
            return
        trashed = {path.resolve(strict=False) for path in trashed_paths}
        displayed = [
            Path(self.thumbnail_list.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self.thumbnail_list.count())
        ]
        affected_rows = [
            row
            for row, path in enumerate(displayed)
            if path.resolve(strict=False) in trashed
        ]
        if not affected_rows:
            return
        remaining = [
            path for path in displayed if path.resolve(strict=False) not in trashed
        ]
        selection = []
        if remaining:
            selection = [remaining[min(min(affected_rows), len(remaining) - 1)]]
        self._show_directory(self.current_directory, selection)

    def _thumbnail_item_for_path(self, path: Path):
        resolved_path = path.resolve(strict=False)
        for row in range(self.thumbnail_list.count()):
            item = self.thumbnail_list.item(row)
            item_path = Path(item.data(Qt.ItemDataRole.UserRole))
            if item_path.resolve(strict=False) == resolved_path:
                return item
        return None

    def _clear_internal_clipboard_state(self) -> None:
        if self._clipboard_operation == "cut":
            for source_path in self._clipboard_source_paths:
                item = self._thumbnail_item_for_path(source_path)
                if item is not None:
                    item.setData(Qt.ItemDataRole.ForegroundRole, None)
        self._clipboard_operation = None
        self._clipboard_source_paths = []

    def _clipboard_files(self) -> tuple[list[Path], str]:
        mime_data = self.clipboard.mimeData()
        operation = "copy"
        urls = []
        if mime_data is None:
            return [], operation
        if mime_data.hasFormat("x-special/gnome-copied-files"):
            clipboard_data = bytes(
                mime_data.data("x-special/gnome-copied-files")
            ).decode("utf-8", errors="replace")
            lines = [line.strip() for line in clipboard_data.splitlines() if line.strip()]
            if lines and lines[0] in ("copy", "cut"):
                operation = lines[0]
                urls = [QUrl(line) for line in lines[1:]]
        if not urls and mime_data.hasUrls():
            urls = mime_data.urls()
        paths = []
        for url in urls:
            if url.isLocalFile():
                paths.append(Path(url.toLocalFile()))
        return paths, operation

    @staticmethod
    def _is_suitable_clipboard_image(path: Path) -> bool:
        return (
            path.is_file()
            and os.access(path, os.R_OK)
            and path.suffix.lower() in IMAGE_EXTENSIONS
        )

    def _clipboard_changed(self) -> None:
        if self._handling_clipboard_change:
            return
        self._handling_clipboard_change = True
        try:
            clipboard_paths, operation = self._clipboard_files()
            clipboard_resolved = [
                path.resolve(strict=False) for path in clipboard_paths
            ]
            internal_resolved = [
                path.resolve(strict=False) for path in self._clipboard_source_paths
            ]
            if self._clipboard_source_paths and (
                clipboard_resolved != internal_resolved
                or operation != self._clipboard_operation
            ):
                self._clear_internal_clipboard_state()
            self.paste_image_action.setEnabled(
                any(
                    self._is_suitable_clipboard_image(path)
                    for path in clipboard_paths
                )
                and self.current_directory is not None
                and self.current_directory.is_dir()
            )
        finally:
            self._handling_clipboard_change = False

    def _selected_image_paths(self) -> list[Path]:
        return [
            Path(item.data(Qt.ItemDataRole.UserRole))
            for item in self.thumbnail_list.selectedItems()
        ]

    def _selected_thumbnail_paths_in_display_order(self) -> list[Path]:
        return [
            Path(self.thumbnail_list.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self.thumbnail_list.count())
            if self.thumbnail_list.item(row).isSelected()
        ]

    def _restore_thumbnail_selection(
        self, paths: list[Path], current_path: Path | None
    ) -> None:
        selected_paths = {path.resolve(strict=False) for path in paths}
        self.thumbnail_list.clearSelection()
        for row in range(self.thumbnail_list.count()):
            item = self.thumbnail_list.item(row)
            item_path = Path(item.data(Qt.ItemDataRole.UserRole))
            if item_path.resolve(strict=False) in selected_paths:
                item.setSelected(True)
            if (
                current_path is not None
                and item_path.resolve(strict=False) == current_path.resolve(strict=False)
            ):
                self.thumbnail_list.setCurrentItem(
                    item, QItemSelectionModel.SelectionFlag.NoUpdate
                )

    def _start_thumbnail_drag(self, source_paths: list[Path] | None = None) -> bool:
        paths = exportable_image_paths(
            source_paths
            if source_paths is not None
            else self._selected_thumbnail_paths_in_display_order()
        )
        if not paths:
            return False

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        drag = QDrag(self.thumbnail_list)
        drag.setMimeData(mime_data)
        first_item = self.thumbnail_list.currentItem()
        if first_item is not None:
            preview = first_item.icon().pixmap(self._thumbnail_size)
            if not preview.isNull():
                drag.setPixmap(preview)
        drag.exec(Qt.DropAction.CopyAction)
        return True

    def _show_resized_export_dialog(
        self, context_image_path: Path | None = None
    ) -> None:
        paths = [path for path in self._selected_image_paths() if path.is_file()]
        if context_image_path is not None and context_image_path.is_file():
            context_key = self._resolved_sort_path(context_image_path)
            if all(self._resolved_sort_path(path) != context_key for path in paths):
                paths.append(context_image_path)
        if not paths and self.current_image is not None and self.current_image.is_file():
            paths = [self.current_image]
        if not paths:
            return
        unique_paths = []
        seen_paths = set()
        for path in paths:
            key = self._resolved_sort_path(path)
            if key not in seen_paths:
                seen_paths.add(key)
                unique_paths.append(path)
        rotations = {
            key: self._display_rotation_by_path.get(key, 0)
            for key in seen_paths
        }
        default_directory = self.current_directory or unique_paths[0].parent
        dialog = ImageExportDialog(
            unique_paths,
            rotations,
            self.settings,
            default_directory,
            COLOR_SCHEMES[self._color_scheme],
            self._open_export_folder,
            self.window,
        )
        self._restore_slideshow_cursor()
        dialog.exec()
        self._restart_slideshow_cursor_timer()

    def _open_export_folder(self, directory: Path) -> None:
        if not directory.is_dir():
            return
        errors: list[str] = []
        if not self._start_file_manager_fallback(directory, errors):
            self._show_file_manager_error(
                directory,
                "Der Zielordner konnte nicht im Dateimanager geöffnet werden."
                + (f"\n\n{'\n'.join(errors)}" if errors else ""),
            )

    def _rename_image(self, image_path: Path | None = None) -> None:
        source_path = image_path or self.current_image
        if source_path is None:
            return
        source_path = Path(source_path)
        if not source_path.is_file():
            self._show_rename_error(
                "Die Bilddatei wurde nicht gefunden.", str(source_path)
            )
            return
        if source_path.suffix.lower() not in IMAGE_EXTENSIONS:
            self._show_rename_error(
                "Dieses Bildformat wird nicht unterstützt.", str(source_path)
            )
            return
        if not (
            source_path.parent.is_dir()
            and os.access(source_path.parent, os.W_OK | os.X_OK)
        ):
            self._show_rename_error(
                "Der Ordner ist schreibgeschützt oder nicht beschreibbar.",
                str(source_path.parent),
            )
            return

        extension = source_path.suffix
        base_name = source_path.name[: -len(extension)] if extension else source_path.name
        dialog = QDialog(self.window)
        dialog.setWindowTitle("Bild umbenennen")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(QLabel(f"Bisher:\n{source_path.name}", dialog))
        layout.addWidget(QLabel("Neuer Name:", dialog))
        name_edit = QLineEdit(base_name, dialog)
        name_edit.selectAll()
        layout.addWidget(name_edit)
        extension_label = QLabel(
            f"Dateiendung: {extension or '(keine)'}", dialog
        )
        layout.addWidget(extension_label)
        buttons = QDialogButtonBox(dialog)
        rename_button = buttons.addButton(
            "Umbenennen", QDialogButtonBox.ButtonRole.AcceptRole
        )
        cancel_button = buttons.addButton(
            "Abbrechen", QDialogButtonBox.ButtonRole.RejectRole
        )
        rename_button.setAutoDefault(False)
        rename_button.setDefault(False)
        cancel_button.setDefault(True)
        cancel_button.setFocus()
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.setStyleSheet(
            message_box_stylesheet(COLOR_SCHEMES[self._color_scheme])
        )
        self._restore_slideshow_cursor()

        def attempt_rename() -> None:
            new_base_name = name_edit.text().strip()
            validation_error = self._validate_rename_base_name(
                source_path, new_base_name
            )
            if validation_error is not None:
                self._show_rename_error(validation_error, parent=dialog)
                name_edit.setFocus()
                name_edit.selectAll()
                return
            target_path = source_path.with_name(new_base_name + extension)
            if target_path.name == source_path.name:
                self._show_rename_error(
                    "Der neue Dateiname ist mit dem bisherigen Namen identisch.",
                    parent=dialog,
                )
                name_edit.setFocus()
                name_edit.selectAll()
                return
            try:
                target_exists = target_path.exists()
                same_file = (
                    target_exists
                    and os.path.samefile(source_path, target_path)
                )
            except OSError:
                target_exists = target_path.exists()
                same_file = False
            case_only_target = (
                source_path.name != target_path.name
                and source_path.name.casefold() == target_path.name.casefold()
            )
            if target_exists and not (same_file and case_only_target):
                self._show_rename_error(
                    "Eine Datei mit diesem Namen existiert bereits.",
                    str(target_path),
                    dialog,
                )
                name_edit.setFocus()
                name_edit.selectAll()
                return

            selected_paths = self._selected_image_paths()
            if source_path not in selected_paths:
                selected_paths.append(source_path)
            try:
                rename_state = self._prepare_rename_state(source_path)
                self._perform_filesystem_rename(source_path, target_path)
                self._complete_image_rename(
                    source_path,
                    target_path,
                    selected_paths,
                    rename_state,
                )
            except OSError as error:
                self._show_rename_error(
                    "Die Bilddatei konnte nicht umbenannt werden.",
                    str(error),
                    dialog,
                )
                return
            dialog.accept()

        rename_button.clicked.connect(attempt_rename)
        dialog.exec()
        self._restart_slideshow_cursor_timer()

    @staticmethod
    def _validate_rename_base_name(
        source_path: Path, base_name: str
    ) -> str | None:
        if not base_name:
            return "Bitte gib einen Dateinamen ein."
        if base_name in (".", ".."):
            return "Dieser Dateiname ist nicht zulässig."
        if "/" in base_name or "\0" in base_name:
            return "Der Dateiname darf weder „/“ noch Nullzeichen enthalten."
        extension = source_path.suffix
        old_base_name = (
            source_path.name[: -len(extension)] if extension else source_path.name
        )
        if base_name == old_base_name:
            return "Der neue Dateiname ist mit dem bisherigen Namen identisch."
        return None

    @staticmethod
    def _perform_filesystem_rename(source_path: Path, target_path: Path) -> None:
        case_only_change = (
            source_path.name != target_path.name
            and source_path.name.casefold() == target_path.name.casefold()
        )
        if not case_only_change:
            source_path.rename(target_path)
            return

        temporary_path = None
        for counter in range(1000):
            candidate = source_path.with_name(
                f".bildblick-umbenennen-{os.getpid()}-{counter}{source_path.suffix}"
            )
            if not candidate.exists():
                temporary_path = candidate
                break
        if temporary_path is None:
            raise OSError("Es konnte kein sicherer Zwischenname erzeugt werden.")
        source_path.rename(temporary_path)
        try:
            temporary_path.rename(target_path)
        except OSError:
            try:
                temporary_path.rename(source_path)
            except OSError:
                pass
            raise

    def _prepare_rename_state(self, source_path: Path) -> dict[str, object]:
        cache_files: list[tuple[Path, int]] = []
        for pixels in range(
            THUMBNAIL_MINIMUM, THUMBNAIL_MAXIMUM + 1, THUMBNAIL_STEP
        ):
            thumbnail_size = thumbnail_size_for_pixels(pixels)
            try:
                old_cache_name = thumbnail_cache_name(source_path, thumbnail_size)
            except OSError:
                continue
            for cache_directory in (CACHE_DIRECTORY, LEGACY_CACHE_DIRECTORY):
                cache_path = cache_directory / old_cache_name
                if cache_path.is_file():
                    cache_files.append((cache_path, pixels))
        return {
            "cache_files": cache_files,
            "old_resolved": self._resolved_sort_path(source_path),
        }

    def _complete_image_rename(
        self,
        source_path: Path,
        target_path: Path,
        selected_paths: list[Path],
        rename_state: dict[str, object],
    ) -> None:
        old_resolved = str(rename_state["old_resolved"])
        self._resolved_sort_path_cache.clear()
        new_resolved = self._resolved_sort_path(target_path)

        for old_cache_path, pixels in rename_state["cache_files"]:
            try:
                new_cache_name = thumbnail_cache_name(
                    target_path, thumbnail_size_for_pixels(int(pixels))
                )
                new_cache_path = old_cache_path.parent / new_cache_name
                if not new_cache_path.exists():
                    old_cache_path.rename(new_cache_path)
            except (OSError, TypeError, ValueError):
                pass

        transferred_tooltips = {}
        for key, tooltip in self._metadata_cache.items():
            if key[0] != old_resolved:
                transferred_tooltips[key] = tooltip
                continue
            lines = tooltip.splitlines() or [source_path.name]
            lines[0] = target_path.name
            transferred_tooltips[(new_resolved, *key[1:])] = "\n".join(lines)
        self._metadata_cache = transferred_tooltips
        self._image_metadata_cache = {
            ((new_resolved, *key[1:]) if key[0] == old_resolved else key): value
            for key, value in self._image_metadata_cache.items()
        }
        if old_resolved in self._image_metadata_by_path:
            self._image_metadata_by_path[new_resolved] = (
                self._image_metadata_by_path.pop(old_resolved)
            )
        if old_resolved in self._recording_date_cache:
            self._recording_date_cache[new_resolved] = (
                self._recording_date_cache.pop(old_resolved)
            )
        if old_resolved in self._file_sort_metadata:
            self._file_sort_metadata[new_resolved] = (
                self._file_sort_metadata.pop(old_resolved)
            )
        if old_resolved in self._display_rotation_by_path:
            self._display_rotation_by_path[new_resolved] = (
                self._display_rotation_by_path.pop(old_resolved)
            )

        if self.startup_image is not None and self._resolved_path_equals(
            self.startup_image, source_path
        ):
            self.startup_image = target_path
        self._pending_images = [
            target_path if self._resolved_path_equals(path, source_path) else path
            for path in self._pending_images
        ]

        clipboard_changed = False
        updated_clipboard_paths = []
        for path in self._clipboard_source_paths:
            if self._resolved_path_equals(path, source_path):
                updated_clipboard_paths.append(target_path)
                clipboard_changed = True
            else:
                updated_clipboard_paths.append(path)
        if clipboard_changed and self._clipboard_operation is not None:
            self._set_image_clipboard(
                updated_clipboard_paths, self._clipboard_operation
            )

        restored_selection = [target_path]
        restored_selection.extend(
            path
            for path in selected_paths
            if not self._resolved_path_equals(path, source_path)
        )
        self.current_image = target_path
        self._show_directory(source_path.parent, restored_selection)

    @staticmethod
    def _resolved_path_equals(first: Path, second: Path) -> bool:
        try:
            return first.resolve(strict=False) == second.resolve(strict=False)
        except (OSError, RuntimeError):
            return first.absolute() == second.absolute()

    def _show_rename_error(
        self,
        message: str,
        detail: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        error_dialog = QMessageBox(parent or self.window)
        error_dialog.setWindowTitle("Bild umbenennen")
        error_dialog.setIcon(QMessageBox.Icon.Warning)
        error_dialog.setText(message)
        if detail:
            error_dialog.setInformativeText(detail)
        error_dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        error_dialog.button(QMessageBox.StandardButton.Ok).setText("OK")
        self._style_message_box(error_dialog)
        error_dialog.exec()

    def show_in_file_manager(self, image_path: Path | None = None) -> None:
        target_path = image_path or self.current_image
        if target_path is None:
            return
        try:
            target_path = target_path.resolve(strict=True)
        except (OSError, RuntimeError):
            self._show_file_manager_missing_error(target_path)
            return
        if not target_path.is_file():
            self._show_file_manager_missing_error(target_path)
            return

        parent_directory = target_path.parent
        if not (
            parent_directory.is_dir()
            and os.access(parent_directory, os.R_OK | os.X_OK)
        ):
            self._show_file_manager_error(
                target_path,
                "Der übergeordnete Ordner ist nicht erreichbar.",
            )
            return

        file_uri = bytes(
            QUrl.fromLocalFile(str(target_path)).toEncoded()
        ).decode("ascii").replace("'", "%27")
        errors: list[str] = []
        if self._show_item_via_filemanager1(file_uri, errors):
            return
        if self._start_file_manager_fallback(parent_directory, errors):
            return
        self._show_file_manager_error(
            target_path,
            "Weder Nemo noch ein anderer Dateimanager konnte gestartet werden."
            + (f"\n\n{'\n'.join(errors)}" if errors else ""),
        )

    @staticmethod
    def _show_item_via_filemanager1(
        file_uri: str, errors: list[str]
    ) -> bool:
        gdbus = shutil.which("gdbus")
        if gdbus is None:
            errors.append("FileManager1: gdbus wurde nicht gefunden.")
            return False
        escaped_uri = file_uri.replace("\\", "\\\\").replace("'", "\\'")
        try:
            result = subprocess.run(
                [
                    gdbus,
                    "call",
                    "--session",
                    "--dest",
                    "org.freedesktop.FileManager1",
                    "--object-path",
                    "/org/freedesktop/FileManager1",
                    "--method",
                    "org.freedesktop.FileManager1.ShowItems",
                    f"['{escaped_uri}']",
                    "",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            errors.append(f"FileManager1: {error}")
            return False
        if result.returncode == 0:
            return True
        detail = result.stderr.strip() if result.stderr else "Aufruf fehlgeschlagen"
        errors.append(f"FileManager1: {detail}")
        return False

    @staticmethod
    def _start_file_manager_fallback(
        parent_directory: Path, errors: list[str]
    ) -> bool:
        candidates: tuple[tuple[str, list[str]], ...] = (
            ("nemo", [str(parent_directory)]),
            ("xdg-open", [str(parent_directory)]),
            ("gio", ["open", str(parent_directory)]),
        )
        if sys.platform == "darwin":
            candidates = (("open", [str(parent_directory)]),)
        for executable_name, arguments in candidates:
            executable = shutil.which(executable_name)
            if executable is None:
                errors.append(f"{executable_name}: nicht gefunden.")
                continue
            try:
                subprocess.Popen(
                    [executable, *arguments],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return True
            except OSError as error:
                errors.append(f"{executable_name}: {error}")
        return False

    def _show_file_manager_missing_error(self, image_path: Path) -> None:
        dialog = QMessageBox(self.window)
        dialog.setWindowTitle("Im Dateimanager anzeigen")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText("Die Datei wurde nicht gefunden.")
        dialog.setInformativeText(str(image_path.absolute()))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.button(QMessageBox.StandardButton.Ok).setText("OK")
        self._style_message_box(dialog)
        dialog.exec()

    def _show_file_manager_error(
        self, image_path: Path, detail: str
    ) -> None:
        dialog = QMessageBox(self.window)
        dialog.setWindowTitle("Im Dateimanager anzeigen")
        dialog.setIcon(QMessageBox.Icon.Critical)
        dialog.setText("Der Speicherort konnte nicht geöffnet werden.")
        dialog.setInformativeText(f"{image_path}\n\n{detail}")
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.button(QMessageBox.StandardButton.Ok).setText("OK")
        self._style_message_box(dialog)
        dialog.exec()

    def _compare_selected_images(self) -> None:
        selected_items = sorted(
            self.thumbnail_list.selectedItems(),
            key=self.thumbnail_list.row,
        )
        selected_count = len(selected_items)
        if selected_count != 2:
            if selected_count == 0:
                message = "Bitte markieren Sie zuerst zwei Bilder."
            elif selected_count == 1:
                message = "Bitte markieren Sie noch ein zweites Bild."
            else:
                message = (
                    "Bitte markieren Sie genau zwei Bilder.\n"
                    f"Aktuell sind {selected_count} Bilder ausgewählt."
                )
            dialog = QMessageBox(self.window)
            dialog.setWindowTitle("Bilder vergleichen")
            dialog.setIcon(QMessageBox.Icon.Information)
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setText(message)
            dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
            dialog.button(QMessageBox.StandardButton.Ok).setText("OK")
            self._style_message_box(dialog)
            dialog.exec()
            return
        selected_paths = [
            Path(item.data(Qt.ItemDataRole.UserRole)) for item in selected_items
        ]
        dialog = ImageComparisonDialog(
            selected_paths[0],
            selected_paths[1],
            COLOR_SCHEMES[self._color_scheme],
            self.window,
        )
        dialog.exec()

    def _put_current_image_on_clipboard(self, operation: str) -> None:
        source_paths = [
            path.resolve(strict=False)
            for path in self._selected_image_paths()
            if path.is_file()
        ]
        if not source_paths:
            return
        self._set_image_clipboard(source_paths, operation)

    def _set_image_clipboard(
        self,
        source_paths: list[Path],
        operation: str,
    ) -> None:
        self._clear_internal_clipboard_state()
        source_urls = [QUrl.fromLocalFile(str(path)) for path in source_paths]
        mime_data = QMimeData()
        mime_data.setUrls(source_urls)
        mime_data.setData(
            "x-special/gnome-copied-files",
            operation.encode("utf-8")
            + b"\n"
            + b"\n".join(bytes(url.toEncoded()) for url in source_urls),
        )
        self._clipboard_operation = operation
        self._clipboard_source_paths = source_paths
        self.clipboard.setMimeData(mime_data)
        if operation == "cut":
            for source_path in source_paths:
                item = self._thumbnail_item_for_path(source_path)
                if item is not None:
                    item.setForeground(QBrush(QColor("#888888")))

    def _show_file_operation_error(self, message: str, detail: str) -> None:
        error_dialog = QMessageBox(self.window)
        error_dialog.setWindowTitle("Dateivorgang fehlgeschlagen")
        error_dialog.setIcon(QMessageBox.Icon.Critical)
        error_dialog.setTextFormat(Qt.TextFormat.PlainText)
        error_dialog.setText(message)
        error_dialog.setInformativeText(detail)
        error_dialog.setStandardButtons(QMessageBox.StandardButton.Close)
        error_dialog.button(QMessageBox.StandardButton.Close).setText("Schließen")
        self._style_message_box(error_dialog)
        error_dialog.exec()

    @staticmethod
    def _unused_destination_path(destination: Path) -> Path:
        counter = 1
        while True:
            candidate = destination.with_name(
                f"{destination.stem} ({counter}){destination.suffix}"
            )
            if not candidate.exists():
                return candidate
            counter += 1

    def _resolve_destination_path(
        self,
        source_path: Path,
        conflict_policy: str | None,
    ) -> tuple[Path | None, str, str | None]:
        destination = self.current_directory / source_path.name
        if not destination.exists():
            return destination, "proceed", conflict_policy
        if conflict_policy == "keep":
            return self._unused_destination_path(destination), "proceed", conflict_policy
        if conflict_policy == "replace":
            return destination, "proceed", conflict_policy
        if conflict_policy == "skip":
            return None, "skip", conflict_policy

        conflict_dialog = QMessageBox(self.window)
        conflict_dialog.setWindowTitle("Datei bereits vorhanden")
        conflict_dialog.setIcon(QMessageBox.Icon.Warning)
        conflict_dialog.setTextFormat(Qt.TextFormat.PlainText)
        conflict_dialog.setText(
            "Im Zielordner ist bereits eine Datei mit diesem Namen vorhanden."
        )
        conflict_dialog.setInformativeText(destination.name)
        replace_button = conflict_dialog.addButton(
            "Datei ersetzen", QMessageBox.ButtonRole.DestructiveRole
        )
        keep_button = conflict_dialog.addButton(
            "Beide behalten", QMessageBox.ButtonRole.AcceptRole
        )
        skip_button = conflict_dialog.addButton(
            "Überspringen", QMessageBox.ButtonRole.ActionRole
        )
        cancel_button = conflict_dialog.addButton(
            "Abbrechen", QMessageBox.ButtonRole.RejectRole
        )
        apply_to_all = QCheckBox("Für alle weiteren Konflikte übernehmen")
        conflict_dialog.setCheckBox(apply_to_all)
        conflict_dialog.setDefaultButton(cancel_button)
        conflict_dialog.setEscapeButton(cancel_button)
        self._style_message_box(conflict_dialog)
        conflict_dialog.exec()

        if conflict_dialog.clickedButton() is keep_button:
            policy = "keep" if apply_to_all.isChecked() else None
            return self._unused_destination_path(destination), "proceed", policy
        if conflict_dialog.clickedButton() is skip_button:
            policy = "skip" if apply_to_all.isChecked() else None
            return None, "skip", policy
        if conflict_dialog.clickedButton() is not replace_button:
            return None, "cancel", conflict_policy

        replace_dialog = QMessageBox(self.window)
        replace_dialog.setWindowTitle("Zieldatei ersetzen")
        replace_dialog.setIcon(QMessageBox.Icon.Warning)
        replace_dialog.setTextFormat(Qt.TextFormat.PlainText)
        replace_dialog.setText("Möchtest du diese Zieldatei wirklich ersetzen?")
        replace_dialog.setInformativeText(str(destination))
        confirm_button = replace_dialog.addButton(
            "Datei ersetzen", QMessageBox.ButtonRole.DestructiveRole
        )
        replace_cancel_button = replace_dialog.addButton(
            "Abbrechen", QMessageBox.ButtonRole.RejectRole
        )
        replace_dialog.setDefaultButton(replace_cancel_button)
        replace_dialog.setEscapeButton(replace_cancel_button)
        self._style_message_box(replace_dialog)
        replace_dialog.exec()
        if replace_dialog.clickedButton() is not confirm_button:
            return None, "cancel", conflict_policy
        policy = "replace" if apply_to_all.isChecked() else None
        return destination, "proceed", policy

    def _paste_image_from_clipboard(self) -> None:
        source_paths, operation = self._clipboard_files()
        if not source_paths or self.current_directory is None:
            self.paste_image_action.setEnabled(False)
            return
        target_directory = self.current_directory
        inserted_paths = []
        successful_source_paths = set()
        failures = []
        conflict_policy = None
        for source_path in source_paths:
            if not self._is_suitable_clipboard_image(source_path):
                failures.append(f"{source_path.name}: nicht verfügbar oder nicht unterstützt")
                continue
            destination, decision, conflict_policy = self._resolve_destination_path(
                source_path, conflict_policy
            )
            if decision == "cancel":
                break
            if decision == "skip" or destination is None:
                failures.append(f"{source_path.name}: übersprungen")
                continue
            same_file = (
                source_path.resolve(strict=False)
                == destination.resolve(strict=False)
            )
            try:
                if not same_file:
                    if operation == "cut":
                        shutil.move(str(source_path), str(destination))
                    else:
                        shutil.copy2(source_path, destination)
                inserted_paths.append(destination)
                successful_source_paths.add(source_path.resolve(strict=False))
            except (OSError, shutil.Error) as error:
                failures.append(f"{source_path.name}: {error}")

        if operation == "cut":
            remaining_paths = [
                path
                for path in source_paths
                if path.resolve(strict=False) not in successful_source_paths
                and path.exists()
            ]
            if remaining_paths:
                self._set_image_clipboard(remaining_paths, "cut")
            else:
                self._clear_internal_clipboard_state()
                self.clipboard.clear()
        if inserted_paths:
            self._show_directory(target_directory, inserted_paths)
        if failures:
            self._show_file_operation_error(
                "Einige Bilder konnten nicht eingefügt werden.",
                "\n".join(failures),
            )

    def _move_current_image_to_trash(self) -> None:
        selected_items = list(self.thumbnail_list.selectedItems())
        if not selected_items:
            return
        selected = [
            (
                self.thumbnail_list.row(item),
                Path(item.data(Qt.ItemDataRole.UserRole)),
            )
            for item in selected_items
        ]
        first_selected_row = min(row for row, _path in selected)

        slideshow_was_running = self._slideshow_running
        if slideshow_was_running:
            self.slideshow_timer.stop()

        confirmation = QMessageBox(self.window)
        confirmation.setWindowTitle("Bild in den Papierkorb verschieben")
        confirmation.setIcon(QMessageBox.Icon.Question)
        confirmation.setTextFormat(Qt.TextFormat.PlainText)
        if len(selected) == 1:
            confirmation.setText(
                "Möchtest du dieses Bild in den Papierkorb verschieben?"
            )
            confirmation.setInformativeText(selected[0][1].name)
        else:
            confirmation.setText(
                f"Möchtest du die ausgewählten {len(selected)} Bilder "
                "in den Papierkorb verschieben?"
            )
        trash_button = confirmation.addButton(
            "In den Papierkorb",
            QMessageBox.ButtonRole.AcceptRole,
        )
        cancel_button = confirmation.addButton(
            "Abbrechen",
            QMessageBox.ButtonRole.RejectRole,
        )
        confirmation.setDefaultButton(cancel_button)
        confirmation.setEscapeButton(cancel_button)
        self._style_message_box(confirmation)
        confirmation.exec()

        if confirmation.clickedButton() is not trash_button:
            if slideshow_was_running:
                self._restart_slideshow_timer()
            return

        successful = []
        failures = []
        for row, image_path in selected:
            try:
                cache_name = thumbnail_cache_name(image_path, self._thumbnail_size)
            except OSError:
                cache_name = None
            try:
                send2trash(str(image_path))
            except Exception as error:
                failures.append(f"{image_path.name}: {error}")
                continue
            successful.append((row, image_path))
            if cache_name is not None:
                for cache_directory in (CACHE_DIRECTORY, LEGACY_CACHE_DIRECTORY):
                    try:
                        (cache_directory / cache_name).unlink(missing_ok=True)
                    except OSError:
                        pass
            resolved_path = str(image_path.resolve(strict=False))
            self._metadata_cache = {
                key: value
                for key, value in self._metadata_cache.items()
                if key[0] != resolved_path
            }
            self._image_metadata_cache = {
                key: value
                for key, value in self._image_metadata_cache.items()
                if key[0] != resolved_path
            }
            self._image_metadata_by_path.pop(resolved_path, None)

        successful_paths = {
            path.resolve(strict=False) for _row, path in successful
        }
        if successful_paths and any(
            path.resolve(strict=False) in successful_paths
            for path in self._clipboard_source_paths
        ):
            remaining_cut_paths = [
                path for path in self._clipboard_source_paths if path.exists()
            ]
            if self._clipboard_operation == "cut" and remaining_cut_paths:
                self._set_image_clipboard(remaining_cut_paths, "cut")
            else:
                self._clear_internal_clipboard_state()
                self.clipboard.clear()

        self.thumbnail_list.setCurrentRow(-1)
        for row, _image_path in sorted(successful, reverse=True):
            removed_item = self.thumbnail_list.takeItem(row)
            del removed_item

        if successful and self.thumbnail_list.count() > 0:
            self._select_image(
                min(first_selected_row, self.thumbnail_list.count() - 1)
            )
        elif successful:
            if self._slideshow_running:
                self._stop_slideshow()
            self.current_image = None
            self.original_image = QImage()
            self._exif_oriented_image = QImage()
            self._zoom_mode = "fit"
            self._zoom_factor = 1.0
            self.image_label.clear()
            self.image_label.resize(self.image_scroll_area.viewport().size())
            self.image_label.setText("Bild anklicken, um es anzuzeigen")
            self._set_file_name_text("0 Bilder")
            self._update_view_actions()
            self._update_navigation_buttons()
        elif slideshow_was_running:
            self._restart_slideshow_timer()

        if failures:
            self._show_file_operation_error(
                "Einige Bilder konnten nicht in den Papierkorb verschoben werden.",
                "\n".join(failures),
            )

    def _show_controls_help(self) -> None:
        help_dialog = QMessageBox(self.window)
        help_dialog.setWindowTitle("Bedienung und Tastenkürzel")
        help_dialog.setIcon(QMessageBox.Icon.Information)
        help_dialog.setTextFormat(Qt.TextFormat.RichText)
        help_dialog.setText(
            "<b>Maus:</b><br>"
            "• Vorschaubild anklicken: Bild anzeigen<br>"
            "• Mausrad über dem großen Bild: Zoomen<br>"
            "• Linke Maustaste ziehen: Vergrößertes Bild verschieben<br>"
            "• Klick auf das große Bild: Vollbild ein oder aus<br><br>"
            "<b>Tastatur:</b><br>"
            "• Alt+Links: Vorheriger Ordner<br>"
            "• Alt+Rechts: Nächster Ordner<br>"
            "• Alt+Oben: Übergeordneter Ordner<br>"
            "• Strg+Links: Aktuelles Bild nach links drehen<br>"
            "• Strg+Rechts: Aktuelles Bild nach rechts drehen<br>"
            "• F2: Aktuelles Bild umbenennen<br>"
            "• Beim Umbenennen bleibt die Dateiendung erhalten. Die "
            "Bilddatei wird nicht neu gespeichert.<br>"
            "• Ausgewählte Bilder verkleinert exportieren erstellt neue "
            "JPEG-Kopien mit frei wählbarer Auflösung und Qualität. Die "
            "Originalbilder bleiben unverändert.<br>"
            "• Die Drehung verändert die Originaldatei nicht<br>"
            "• „Gedrehte Kopie speichern …“ speichert ein neues Bild.<br>"
            "• „Drehung im Original speichern …“ überschreibt die Originaldatei "
            "erst nach einer Sicherheitsabfrage.<br>"
            "• JPEG-Dateien werden beim Speichern neu komprimiert.<br>"
            "• Im Dateimanager anzeigen öffnet den Speicherort des aktuellen "
            "oder rechtsgeklickten Bildes.<br>"
            "• Pfeiltasten: Durch die Vorschaubilder navigieren<br>"
            "• Pos1: Erstes Bild<br>"
            "• Ende: Letztes Bild<br>"
            "• 0: Bild einpassen<br>"
            "• 1: Originalgröße<br>"
            "• F5: Diashow starten oder stoppen<br>"
            "• Leertaste: Diashow pausieren oder fortsetzen<br>"
            "• Pfeiltasten: Während der Diashow vor und zurück<br>"
            "• Nur markierte Bilder: Diashow auf die aktuelle Auswahl begrenzen<br>"
            "• Zufällige Reihenfolge: Alle Diashow-Bilder einmal zufällig anzeigen<br>"
            "• Im Vollbild wird der Mauszeiger nach kurzer Inaktivität ausgeblendet<br>"
            "• F11: Vollbild<br>"
            "• Escape: Diashow beziehungsweise Vollbild beenden<br>"
            "• Strg + Klick: Mehrere einzelne Bilder auswählen<br>"
            "• Umschalt + Klick: Bildbereich auswählen<br>"
            "• Zwei Bilder markieren und unter Werkzeuge → Bilder vergleichen öffnen.<br>"
            "• Strg + A: Alle Bilder auswählen<br>"
            "• Strg + C: Ausgewählte Bilder kopieren<br>"
            "• Strg + X: Ausgewählte Bilder ausschneiden<br>"
            "• Strg + V: Bilder in den aktuellen Ordner einfügen<br>"
            "• Entf: Ausgewählte Bilder in den Papierkorb verschieben<br>"
            "• Die Größe der Vorschaubilder kann unter Ansicht geändert werden.<br>"
            "• Die Reihenfolge der Vorschaubilder kann unter Ansicht → Sortieren "
            "nach geändert werden.<br>"
            "• Strg + Plus: Vorschaubilder vergrößern<br>"
            "• Strg + Minus: Vorschaubilder verkleinern<br>"
            "• Strg + 0: Vorschaubildgröße auf 160 Pixel zurücksetzen<br>"
            "• Alt+F4: Programm beenden"
        )
        help_dialog.setStandardButtons(QMessageBox.StandardButton.Close)
        help_dialog.button(QMessageBox.StandardButton.Close).setText("Schließen")
        self._style_message_box(help_dialog)
        help_dialog.exec()

    def _show_about(self) -> None:
        about_dialog = QDialog(self.window)
        about_dialog.setWindowTitle(f"Über {APP_NAME}")
        about_dialog.setModal(True)
        about_dialog.setMinimumWidth(390)

        layout = QVBoxLayout(about_dialog)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(10)

        logo_label = QLabel()
        logo_label.setObjectName("aboutLogoLabel")
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo = QPixmap(str(resource_path("assets/bildblick.png")))
        if not logo.isNull():
            logo_label.setPixmap(
                logo.scaled(
                    112,
                    112,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        layout.addWidget(logo_label)

        name_label = QLabel(APP_NAME)
        name_label.setObjectName("aboutNameLabel")
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setStyleSheet("font-size: 22px; font-weight: 700;")
        layout.addWidget(name_label)

        version_label = QLabel(f"Version {APP_VERSION}")
        version_label.setObjectName("aboutVersionLabel")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        layout.addWidget(version_label)

        description_label = QLabel(APP_DESCRIPTION)
        description_label.setObjectName("aboutDescriptionLabel")
        description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description_label.setWordWrap(True)
        layout.addWidget(description_label)

        technology_label = QLabel("Erstellt mit Python und PySide6")
        technology_label.setObjectName("aboutTechnologyLabel")
        technology_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(technology_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_button = QPushButton("Schließen")
        close_button.setDefault(True)
        close_button.clicked.connect(about_dialog.accept)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        about_dialog.setStyleSheet(
            message_box_stylesheet(COLOR_SCHEMES[self._color_scheme])
        )
        about_dialog.exec()

    def _toggle_fullscreen(self) -> None:
        if self._fullscreen_mode:
            self._leave_fullscreen()
        elif not self.original_image.isNull():
            self._enter_fullscreen()
        else:
            self.fullscreen_action.setChecked(False)

    def _create_slideshow_menu(self) -> None:
        self.slideshow_menu = self.window.menuBar().addMenu("Diashow")

        self.slideshow_action = QAction("Diashow starten / beenden", self.window)
        self.slideshow_action.setShortcut(QKeySequence("F5"))
        self.slideshow_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.slideshow_action.triggered.connect(self._toggle_slideshow)
        self.slideshow_menu.addAction(self.slideshow_action)

        self.slideshow_pause_action = QAction("Pause / fortsetzen", self.window)
        self.slideshow_pause_action.setShortcut(QKeySequence("Space"))
        self.slideshow_pause_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.slideshow_pause_action.triggered.connect(
            self._toggle_slideshow_pause
        )
        self.slideshow_menu.addAction(self.slideshow_pause_action)
        self.window.addAction(self.slideshow_pause_action)

        self.slideshow_menu.addSeparator()
        option_specs = (
            (
                "slideshow_selected_only_action",
                "Nur markierte Bilder",
                self._slideshow_selected_only,
                SLIDESHOW_SELECTED_ONLY_KEY,
            ),
            (
                "slideshow_random_action",
                "Zufällige Reihenfolge",
                self._slideshow_random,
                SLIDESHOW_RANDOM_KEY,
            ),
            (
                "slideshow_metadata_action",
                "Aufnahmeinformationen anzeigen",
                self._slideshow_show_metadata,
                SLIDESHOW_METADATA_KEY,
            ),
            (
                "slideshow_fade_action",
                "Sanfte Überblendung",
                self._slideshow_soft_fade,
                SLIDESHOW_FADE_KEY,
            ),
        )
        for attribute, text, checked, settings_key in option_specs:
            action = QAction(text, self.window)
            action.setCheckable(True)
            action.setChecked(checked)
            action.toggled.connect(
                lambda enabled, key=settings_key: self._set_slideshow_option(
                    key, enabled
                )
            )
            self.slideshow_menu.addAction(action)
            setattr(self, attribute, action)

        self.slideshow_menu.addSeparator()
        self.interval_menu = self.slideshow_menu.addMenu("Intervall")
        self.interval_action_group = QActionGroup(self.window)
        self.interval_action_group.setExclusive(True)
        for seconds in SLIDESHOW_INTERVALS:
            action = QAction(f"{seconds} Sekunden", self.window)
            action.setCheckable(True)
            action.setData(seconds)
            action.setChecked(seconds == self._slideshow_interval)
            self.interval_action_group.addAction(action)
            self.interval_menu.addAction(action)
        self.interval_action_group.triggered.connect(self._set_slideshow_interval)

        self.slideshow_menu.addSeparator()
        self.slideshow_fullscreen_action = QAction(
            "Im Vollbild starten", self.window
        )
        self.slideshow_fullscreen_action.setCheckable(True)
        self.slideshow_fullscreen_action.setChecked(self._slideshow_fullscreen)
        self.slideshow_fullscreen_action.toggled.connect(
            self._set_slideshow_fullscreen
        )
        self.slideshow_menu.addAction(self.slideshow_fullscreen_action)

        self.slideshow_repeat_action = QAction("Wiederholen", self.window)
        self.slideshow_repeat_action.setCheckable(True)
        self.slideshow_repeat_action.setChecked(self._slideshow_repeat)
        self.slideshow_repeat_action.toggled.connect(self._set_slideshow_repeat)
        self.slideshow_menu.addAction(self.slideshow_repeat_action)
        self._update_slideshow_actions()

    def _set_slideshow_option(self, key: str, enabled: bool) -> None:
        if key == SLIDESHOW_SELECTED_ONLY_KEY:
            self._slideshow_selected_only = enabled
        elif key == SLIDESHOW_RANDOM_KEY:
            self._slideshow_random = enabled
        elif key == SLIDESHOW_METADATA_KEY:
            self._slideshow_show_metadata = enabled
            self._update_slideshow_metadata_overlay()
        elif key == SLIDESHOW_FADE_KEY:
            self._slideshow_soft_fade = enabled
        self.settings.setValue(key, enabled)
        self.settings.sync()

    def _set_slideshow_interval(self, action: QAction) -> None:
        self._slideshow_interval = int(action.data())
        self.settings.setValue(SLIDESHOW_INTERVAL_KEY, self._slideshow_interval)
        self.settings.sync()
        if self._slideshow_running:
            self._restart_slideshow_timer()

    def _set_slideshow_repeat(self, enabled: bool) -> None:
        self._slideshow_repeat = enabled
        self.settings.setValue(SLIDESHOW_REPEAT_KEY, enabled)
        self.settings.sync()
        self._update_navigation_buttons()

    def _set_slideshow_fullscreen(self, enabled: bool) -> None:
        self._slideshow_fullscreen = enabled
        self.settings.setValue(SLIDESHOW_FULLSCREEN_KEY, enabled)
        self.settings.sync()

    def _toggle_slideshow(self) -> None:
        if self._slideshow_running:
            self._stop_slideshow()
        else:
            self._start_slideshow()

    def _start_slideshow(self) -> None:
        if self._slideshow_running or self.thumbnail_list.count() == 0:
            return
        slideshow_paths = [
            Path(self.thumbnail_list.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self.thumbnail_list.count())
            if (
                not self._slideshow_selected_only
                or self.thumbnail_list.item(row).isSelected()
            )
        ]
        if self._slideshow_selected_only and not slideshow_paths:
            dialog = QMessageBox(self.window)
            dialog.setWindowTitle("Diashow")
            dialog.setIcon(QMessageBox.Icon.Information)
            dialog.setText("Bitte markieren Sie zuerst mindestens ein Bild.")
            dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
            dialog.button(QMessageBox.StandardButton.Ok).setText("OK")
            self._style_message_box(dialog)
            dialog.exec()
            return
        if not slideshow_paths:
            return
        if self._slideshow_random:
            random.shuffle(slideshow_paths)
        self._slideshow_paths = slideshow_paths
        self._slideshow_index = 0
        self._slideshow_paused = False
        self._slideshow_running = True
        self._slideshow_entered_fullscreen = False
        if self._slideshow_fullscreen and not self._fullscreen_mode:
            self._enter_fullscreen()
            self._slideshow_entered_fullscreen = self._fullscreen_mode
        self._show_slideshow_path(self._slideshow_paths[0], animated=False)
        self._restart_slideshow_timer()
        self._update_slideshow_metadata_overlay()
        self._restart_slideshow_cursor_timer()
        self._update_slideshow_actions()

    def _stop_slideshow(self) -> None:
        if not self._slideshow_running:
            return
        self._slideshow_running = False
        self._slideshow_paused = False
        self.slideshow_timer.stop()
        self.slideshow_message_timer.stop()
        self.slideshow_message_label.hide()
        self.slideshow_metadata_label.hide()
        self._stop_slideshow_fade()
        self._restore_slideshow_cursor()
        if self._slideshow_entered_fullscreen:
            self._leave_fullscreen()
        self._slideshow_entered_fullscreen = False
        self._slideshow_paths = []
        self._slideshow_index = -1
        self._update_slideshow_actions()
        self._update_navigation_buttons()

    def _advance_slideshow(self) -> None:
        if not self._slideshow_running or self._slideshow_paused:
            return
        if not self._slideshow_paths:
            self._stop_slideshow()
            return
        next_index = self._slideshow_index + 1
        if next_index >= len(self._slideshow_paths):
            if not self._slideshow_repeat:
                self._stop_slideshow()
                return
            if self._slideshow_random and len(self._slideshow_paths) > 1:
                previous_last = self._slideshow_paths[-1]
                random.shuffle(self._slideshow_paths)
                if self._slideshow_paths[0] == previous_last:
                    swap_index = next(
                        (
                            index
                            for index, path in enumerate(self._slideshow_paths[1:], 1)
                            if path != previous_last
                        ),
                        None,
                    )
                    if swap_index is not None:
                        self._slideshow_paths[0], self._slideshow_paths[swap_index] = (
                            self._slideshow_paths[swap_index],
                            self._slideshow_paths[0],
                        )
            next_index = 0
        if len(self._slideshow_paths) == 1:
            self._restart_slideshow_timer()
            return
        self._slideshow_index = next_index
        self._show_slideshow_path(
            self._slideshow_paths[next_index],
            animated=self._slideshow_soft_fade,
        )

    def _toggle_slideshow_pause(self) -> None:
        if not self._slideshow_running:
            return
        self._slideshow_paused = not self._slideshow_paused
        if self._slideshow_paused:
            self.slideshow_timer.stop()
            self._show_slideshow_message("Diashow pausiert")
        else:
            self._restart_slideshow_timer()
            self._show_slideshow_message("Diashow fortgesetzt")
        self._update_slideshow_actions()

    def _restart_slideshow_timer(self) -> None:
        self.slideshow_timer.stop()
        if self._slideshow_running and not self._slideshow_paused:
            self.slideshow_timer.start(self._slideshow_interval * 1000)

    def _show_slideshow_path(self, path: Path, animated: bool) -> None:
        if animated and self._slideshow_running:
            self._start_slideshow_fade(path)
            return
        self._stop_slideshow_fade()
        self._select_slideshow_path(path)
        self._restart_slideshow_timer()

    def _select_slideshow_path(self, path: Path) -> None:
        item = self._thumbnail_item_for_path(path)
        if item is None:
            return
        self.thumbnail_list.setCurrentItem(
            item, QItemSelectionModel.SelectionFlag.NoUpdate
        )
        self.thumbnail_list.scrollToItem(item)
        self._update_slideshow_metadata_overlay()

    def _start_slideshow_fade(self, path: Path) -> None:
        self._stop_slideshow_fade(restore_opacity=False)
        effect = QGraphicsOpacityEffect(self.image_label)
        effect.setOpacity(1.0)
        self.image_label.setGraphicsEffect(effect)
        self._slideshow_opacity_effect = effect
        fade_out = QPropertyAnimation(effect, b"opacity", self)
        fade_out.setDuration(200)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.InOutQuad)

        def show_next_image() -> None:
            if not self._slideshow_running:
                self._stop_slideshow_fade()
                return
            self._select_slideshow_path(path)
            fade_in = QPropertyAnimation(effect, b"opacity", self)
            fade_in.setDuration(250)
            fade_in.setStartValue(0.0)
            fade_in.setEndValue(1.0)
            fade_in.setEasingCurve(QEasingCurve.Type.InOutQuad)
            fade_in.finished.connect(self._finish_slideshow_fade)
            self._slideshow_fade_animation = fade_in
            fade_in.start()

        fade_out.finished.connect(show_next_image)
        self._slideshow_fade_animation = fade_out
        fade_out.start()

    def _finish_slideshow_fade(self) -> None:
        self._stop_slideshow_fade()
        self._restart_slideshow_timer()

    def _stop_slideshow_fade(self, restore_opacity: bool = True) -> None:
        if self._slideshow_fade_animation is not None:
            self._slideshow_fade_animation.stop()
            self._slideshow_fade_animation = None
        if self._slideshow_opacity_effect is not None:
            if restore_opacity:
                self._slideshow_opacity_effect.setOpacity(1.0)
                self.image_label.setGraphicsEffect(None)
                self._slideshow_opacity_effect = None

    def _navigate_slideshow(self, offset: int) -> None:
        if not self._slideshow_running or not self._slideshow_paths:
            return
        self._stop_slideshow_fade()
        target_index = self._slideshow_index + offset
        if self._slideshow_repeat:
            target_index %= len(self._slideshow_paths)
        else:
            target_index = max(0, min(len(self._slideshow_paths) - 1, target_index))
        self._slideshow_index = target_index
        self._select_slideshow_path(self._slideshow_paths[target_index])
        self._restart_slideshow_timer()

    def _select_slideshow_endpoint(self, last: bool) -> None:
        if not self._slideshow_running or not self._slideshow_paths:
            return
        self._stop_slideshow_fade()
        self._slideshow_index = len(self._slideshow_paths) - 1 if last else 0
        self._select_slideshow_path(self._slideshow_paths[self._slideshow_index])
        self._restart_slideshow_timer()

    def _show_slideshow_message(self, text: str) -> None:
        self.slideshow_message_label.setText(text)
        self.slideshow_message_label.adjustSize()
        self.slideshow_message_label.show()
        self.slideshow_message_label.raise_()
        self._position_slideshow_overlays()
        self.slideshow_message_timer.start(1500)

    def _update_slideshow_metadata_overlay(self) -> None:
        if (
            not self._slideshow_running
            or not self._slideshow_show_metadata
            or self.current_image is None
        ):
            self.slideshow_metadata_label.hide()
            return
        metadata = self._image_metadata_by_path.get(
            self._resolved_sort_path(self.current_image), {}
        )
        lines = []
        if metadata.get("recording_time"):
            lines.append(metadata["recording_time"])
        camera_line = " · ".join(
            value
            for value in (metadata.get("camera"), metadata.get("lens"))
            if value
        )
        if camera_line:
            lines.append(camera_line)
        exposure_line = " · ".join(
            value
            for value in (
                metadata.get("exposure"),
                metadata.get("aperture"),
                metadata.get("focal_length"),
                f"ISO {metadata['iso']}" if metadata.get("iso") else None,
            )
            if value
        )
        if exposure_line:
            lines.append(exposure_line)
        if not lines:
            self.slideshow_metadata_label.hide()
            return
        viewport_width = self.image_scroll_area.viewport().width()
        maximum_text_width = max(
            80, min(max(80, viewport_width - 32), round(viewport_width * 0.55))
        )
        metrics = self.slideshow_metadata_label.fontMetrics()
        displayed_lines = [
            metrics.elidedText(
                line, Qt.TextElideMode.ElideRight, maximum_text_width
            )
            for line in lines
        ]
        self.slideshow_metadata_label.setText("\n".join(displayed_lines))
        self.slideshow_metadata_label.setToolTip("\n".join(lines))
        self.slideshow_metadata_label.adjustSize()
        self.slideshow_metadata_label.show()
        self.slideshow_metadata_label.raise_()
        self._position_slideshow_overlays()

    def _position_slideshow_overlays(self) -> None:
        viewport = self.image_scroll_area.viewport()
        if self.slideshow_message_label.isVisible():
            self.slideshow_message_label.move(
                max(12, (viewport.width() - self.slideshow_message_label.width()) // 2),
                max(12, (viewport.height() - self.slideshow_message_label.height()) // 2),
            )
        if self.slideshow_metadata_label.isVisible():
            self.slideshow_metadata_label.move(
                16,
                max(16, viewport.height() - self.slideshow_metadata_label.height() - 16),
            )

    def _restart_slideshow_cursor_timer(self) -> None:
        self._restore_slideshow_cursor()
        if self._slideshow_running and self._fullscreen_mode:
            self.slideshow_cursor_timer.start()

    def _hide_slideshow_cursor(self) -> None:
        if self._slideshow_running and self._fullscreen_mode:
            self.image_scroll_area.viewport().setCursor(
                Qt.CursorShape.BlankCursor
            )

    def _restore_slideshow_cursor(self) -> None:
        self.slideshow_cursor_timer.stop()
        try:
            self.image_scroll_area.viewport().unsetCursor()
            self.window.unsetCursor()
        except RuntimeError:
            pass

    def _update_slideshow_actions(self) -> None:
        action_text = (
            "Diashow beenden" if self._slideshow_running else "Diashow starten"
        )
        self.slideshow_action.setText(action_text)
        self.slideshow_pause_action.setEnabled(self._slideshow_running)
        self.slideshow_pause_action.setText(
            "Fortsetzen" if self._slideshow_paused else "Pause / fortsetzen"
        )
        self.slideshow_selected_only_action.setEnabled(
            not self._slideshow_running
        )
        self.slideshow_random_action.setEnabled(not self._slideshow_running)
        self.slideshow_fullscreen_action.setEnabled(not self._slideshow_running)

    def _handle_escape(self) -> None:
        if self._slideshow_running:
            self._stop_slideshow()
        if self._fullscreen_mode:
            self._leave_fullscreen()
        elif self._pdf_preview_mode:
            self._leave_pdf_preview()

    def _expand_initial_path(self, directory: Path) -> None:
        if directory.is_dir():
            for parent in reversed(directory.parents):
                self.directory_tree.expand(self.directory_model.index(str(parent)))
            start_index = self.directory_model.index(str(directory))
            self.directory_tree.setCurrentIndex(start_index)
            self.directory_tree.scrollTo(start_index)

    @staticmethod
    def _load_ui() -> QMainWindow:
        ui_path = resource_path("bildbetrachter.ui")
        ui_file = QFile(str(ui_path))
        if not ui_file.open(QIODevice.OpenModeFlag.ReadOnly):
            raise RuntimeError(f"UI-Datei konnte nicht geöffnet werden: {ui_path}")
        loader = QUiLoader()
        try:
            window = loader.load(ui_file)
        finally:
            ui_file.close()
        if not isinstance(window, QMainWindow):
            raise RuntimeError(f"UI-Datei konnte nicht geladen werden: {loader.errorString()}")
        return window

    def _widget(self, widget_type, object_name):
        widget = self.window.findChild(widget_type, object_name)
        if widget is None:
            raise RuntimeError(f"Widget fehlt in der UI-Datei: {object_name}")
        return widget

    def _directory_selected(self, index) -> None:
        directory = Path(self.directory_model.filePath(index))
        if directory.is_dir():
            self._show_directory(directory)

    def _record_folder_history(self, directory: Path) -> None:
        if (
            0 <= self._folder_history_index < len(self._folder_history)
            and self._folder_history[self._folder_history_index] == directory
        ):
            self._update_folder_navigation_actions()
            return
        if self._folder_history_index < len(self._folder_history) - 1:
            self._folder_history = self._folder_history[
                : self._folder_history_index + 1
            ]
        self._folder_history.append(directory)
        if len(self._folder_history) > FOLDER_HISTORY_LIMIT:
            self._folder_history = self._folder_history[-FOLDER_HISTORY_LIMIT:]
        self._folder_history_index = len(self._folder_history) - 1
        self._update_folder_navigation_actions()

    def _go_to_folder_history_index(self, index: int) -> None:
        if not 0 <= index < len(self._folder_history):
            return
        if self._show_directory(
            self._folder_history[index],
            add_to_history=False,
            show_open_error=True,
        ):
            self._folder_history_index = index
            self._update_folder_navigation_actions()

    def _go_to_previous_folder(self) -> None:
        self._go_to_folder_history_index(self._folder_history_index - 1)

    def _go_to_next_folder(self) -> None:
        self._go_to_folder_history_index(self._folder_history_index + 1)

    def _go_to_parent_folder(self) -> None:
        if self.current_directory is None:
            return
        parent = self.current_directory.parent
        if parent == self.current_directory:
            self._update_folder_navigation_actions()
            return
        self._show_directory(parent, show_open_error=True)

    def _show_folder_open_error(self, directory: Path, error: OSError) -> None:
        dialog = QMessageBox(self.window)
        dialog.setWindowTitle("Ordner konnte nicht geöffnet werden")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText("Der Ordner kann nicht geöffnet werden.")
        dialog.setInformativeText(f"{directory}\n\n{error}")
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.button(QMessageBox.StandardButton.Ok).setText("OK")
        self._style_message_box(dialog)
        dialog.exec()

    def _show_directory(
        self,
        directory: Path,
        select_paths: list[Path] | None = None,
        primary_path: Path | None = None,
        add_to_history: bool = True,
        show_open_error: bool = False,
    ) -> bool:
        try:
            directory = directory.resolve(strict=True)
            new_directory_iterator = os.scandir(directory)
        except OSError as error:
            if show_open_error:
                self._show_folder_open_error(directory, error)
            else:
                self._set_file_name_text("Ordner konnte nicht gelesen werden")
            return False
        if self._slideshow_running:
            self._stop_slideshow()
        self._set_thumbnail_size_actions_enabled(False)
        if self._directory_iterator is not None:
            self._directory_iterator.close()
        self._directory_iterator = None
        self.thread_pool.clear()
        self._load_generation += 1
        generation = self._load_generation
        self._pending_images = []
        self._next_job_index = 0
        self._prepare_index = 0
        self._completed_jobs = 0
        self._active_jobs = 0
        self._file_sort_metadata = {}
        self._resolved_sort_path_cache = {}
        self._capture_sort_waiting = False
        self.current_directory = directory
        self.folder_changed.emit(directory)
        self._directory_iterator = new_directory_iterator
        if add_to_history:
            self._record_folder_history(directory)
        else:
            self._update_folder_navigation_actions()
        self._expand_initial_path(directory)
        self._pending_selection_paths = {
            path.resolve(strict=False) for path in (select_paths or [])
        }
        self._pending_primary_path = (
            primary_path.resolve(strict=False)
            if primary_path is not None
            else (select_paths[0].resolve(strict=False) if select_paths else None)
        )
        self.thumbnail_list.clear()
        self._update_navigation_buttons()
        self.current_image = None
        self.original_image = QImage()
        self._exif_oriented_image = QImage()
        self._update_view_actions()
        self._zoom_mode = "fit"
        self._zoom_factor = 1.0
        self.image_label.clear()
        self.image_label.resize(self.image_scroll_area.viewport().size())
        self.image_label.setText("Bild anklicken, um es anzuzeigen")
        self._set_file_name_text("Suche nach Bildern …")
        self._clipboard_changed()

        self.settings.setValue(LAST_DIRECTORY_KEY, str(directory.resolve(strict=False)))
        self.settings.sync()
        QTimer.singleShot(0, lambda: self._scan_directory_batch(generation))
        return True

    def _show_drop_hint(self) -> None:
        self.drop_hint_label.setText("Bild oder Ordner hier ablegen")
        self.drop_hint_label.setGeometry(self.image_scroll_area.viewport().rect())
        self.drop_hint_label.show()
        self.drop_hint_label.raise_()

    def _hide_drop_hint(self) -> None:
        self.drop_hint_label.hide()

    @staticmethod
    def _local_drop_paths(mime_data: QMimeData) -> list[Path] | None:
        urls = mime_data.urls()
        if not urls or any(not url.isLocalFile() for url in urls):
            return None
        return [Path(url.toLocalFile()) for url in urls]

    def dragEnterEvent(self, event) -> None:
        if self._local_drop_paths(event.mimeData()) is None:
            event.ignore()
            return
        self._show_drop_hint()
        event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if self._local_drop_paths(event.mimeData()) is None:
            event.ignore()
            return
        self._show_drop_hint()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._hide_drop_hint()
        event.accept()

    def dropEvent(self, event) -> None:
        self._hide_drop_hint()
        paths = self._local_drop_paths(event.mimeData())
        if paths is None:
            event.ignore()
            return
        resolution = resolve_dropped_paths(paths)
        if resolution.error_message is not None:
            dialog = QMessageBox(self.window)
            dialog.setWindowTitle("Ablage nicht möglich")
            dialog.setIcon(QMessageBox.Icon.Warning)
            dialog.setText("Die abgelegten Elemente können nicht geöffnet werden.")
            dialog.setInformativeText(resolution.error_message)
            dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
            dialog.button(QMessageBox.StandardButton.Ok).setText("OK")
            self._style_message_box(dialog)
            dialog.exec()
            event.acceptProposedAction()
            return
        if resolution.directory is not None:
            self._show_directory(
                resolution.directory,
                resolution.selected_paths,
                resolution.primary_path,
            )
        if resolution.ignored_paths:
            dialog = QMessageBox(self.window)
            dialog.setWindowTitle("Nicht alle Elemente geöffnet")
            dialog.setIcon(QMessageBox.Icon.Information)
            dialog.setText(
                "Es wurden nur unterstützte Bilder aus dem Ordner des ersten "
                "Bildes geöffnet."
            )
            dialog.setInformativeText(
                "Ignoriert:\n" + "\n".join(
                    str(path) for path in resolution.ignored_paths
                )
            )
            dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
            dialog.button(QMessageBox.StandardButton.Ok).setText("OK")
            self._style_message_box(dialog)
            dialog.exec()
        event.acceptProposedAction()

    def _scan_directory_batch(self, generation: int) -> None:
        if generation != self._load_generation or self._directory_iterator is None:
            return

        try:
            for _ in range(DIRECTORY_ENTRIES_PER_BATCH):
                entry = next(self._directory_iterator)
                path = Path(entry.path)
                try:
                    if (
                        should_show_path(path, self._show_hidden_files)
                        and entry.is_file()
                        and path.suffix.lower() in SUPPORTED_FILE_EXTENSIONS
                    ):
                        self._pending_images.append(path)
                        try:
                            file_info = entry.stat()
                            self._file_sort_metadata[
                                self._resolved_sort_path(path)
                            ] = (file_info.st_size, file_info.st_mtime_ns)
                        except OSError:
                            pass
                except OSError:
                    continue
        except StopIteration:
            self._directory_iterator.close()
            self._directory_iterator = None
            self._pending_images = self._sorted_paths(self._pending_images)
            self._capture_sort_waiting = (
                self._sort_criterion == "recording_date"
                and bool(self._pending_images)
            )
            self._update_loading_text()
            QTimer.singleShot(0, lambda: self._prepare_thumbnail_items(generation))
            return
        except OSError:
            self._directory_iterator.close()
            self._directory_iterator = None
            self._set_file_name_text("Ordner konnte nicht vollständig gelesen werden")
            self._set_thumbnail_size_actions_enabled(True)
            return

        self._set_file_name_text(
            f"Suche nach Bildern … ({len(self._pending_images)} gefunden)"
        )
        QTimer.singleShot(0, lambda: self._scan_directory_batch(generation))

    def _prepare_thumbnail_items(self, generation: int) -> None:
        if generation != self._load_generation:
            return
        end = min(
            self._prepare_index + LIST_ITEMS_PER_BATCH,
            len(self._pending_images),
        )
        while self._prepare_index < end:
            image_path = self._pending_images[self._prepare_index]
            try:
                item = QListWidgetItem(image_path.name)
                item.setSizeHint(self._thumbnail_grid_size)
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
                item.setData(Qt.ItemDataRole.UserRole, str(image_path))
                item.setToolTip(image_path.name)
                self.thumbnail_list.addItem(item)
                if (
                    self._clipboard_operation == "cut"
                    and self._clipboard_source_paths
                    and image_path.resolve(strict=False)
                    in {
                        path.resolve(strict=False)
                        for path in self._clipboard_source_paths
                    }
                ):
                    item.setForeground(QBrush(QColor("#888888")))
                resolved_image_path = image_path.resolve(strict=False)
                if resolved_image_path in self._pending_selection_paths:
                    item.setSelected(True)
                    self._pending_selection_paths.discard(resolved_image_path)
                if resolved_image_path == self._pending_primary_path:
                    self.thumbnail_list.setCurrentItem(
                        item,
                        QItemSelectionModel.SelectionFlag.NoUpdate,
                    )
                    self.thumbnail_list.scrollToItem(item)
                    self._pending_primary_path = None
            except (OSError, RuntimeError):
                pass
            finally:
                self._prepare_index += 1
        self._update_navigation_buttons()
        if self._prepare_index < len(self._pending_images):
            QTimer.singleShot(0, lambda: self._prepare_thumbnail_items(generation))
        else:
            self._start_more_thumbnail_jobs(generation)

    def _start_more_thumbnail_jobs(self, generation: int) -> None:
        if generation != self._load_generation:
            return
        while self._active_jobs < 3 and self._next_job_index < len(self._pending_images):
            index = self._next_job_index
            self._next_job_index += 1
            self._active_jobs += 1
            image_path = self._pending_images[index]
            try:
                file_info = image_path.stat()
                self._file_sort_metadata[
                    self._resolved_sort_path(image_path)
                ] = (file_info.st_size, file_info.st_mtime_ns)
                metadata_key = (
                    str(image_path.resolve(strict=False)),
                    file_info.st_size,
                    file_info.st_mtime_ns,
                    TOOLTIP_METADATA_VERSION,
                )
            except OSError:
                metadata_key = (
                    str(image_path.resolve(strict=False)),
                    -1,
                    -1,
                    TOOLTIP_METADATA_VERSION,
                )
            task = ThumbnailTask(
                image_path,
                index,
                generation,
                metadata_key,
                self._metadata_cache.get(metadata_key),
                self._image_metadata_cache.get(metadata_key),
                self._thumbnail_size,
            )
            try:
                task.signals.ready.connect(self._thumbnail_ready)
                self.thread_pool.start(task)
            except (RuntimeError, OSError):
                self._active_jobs -= 1
                self._completed_jobs += 1
        if self._completed_jobs >= len(self._pending_images):
            self._finish_thumbnail_loading(generation)

    def _thumbnail_ready(
        self,
        generation: int,
        index: int,
        image: QImage,
        tooltip: str,
        metadata_key: tuple[str, int, int, int],
        metadata: dict[str, str],
    ) -> None:
        if generation != self._load_generation:
            return
        self._active_jobs = max(0, self._active_jobs - 1)
        self._completed_jobs += 1
        try:
            self._metadata_cache[metadata_key] = tooltip
            self._image_metadata_cache[metadata_key] = metadata
            self._image_metadata_by_path[metadata_key[0]] = metadata
            self._recording_date_cache[metadata_key[0]] = (
                self._recording_date_from_tooltip(tooltip)
            )
            item = self.thumbnail_list.item(index)
            expected_path = metadata_key[0]
            if (
                item is None
                or str(
                    Path(item.data(Qt.ItemDataRole.UserRole)).resolve(strict=False)
                ) != expected_path
            ):
                item = self._thumbnail_item_for_path(Path(expected_path))
            if item is not None:
                item.setToolTip(tooltip)
                if not image.isNull():
                    item.setIcon(QIcon(QPixmap.fromImage(image)))
                    item.setSizeHint(self._thumbnail_grid_size)
                if item is self.thumbnail_list.currentItem():
                    self._update_status_bar()
                    self._update_slideshow_metadata_overlay()
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
        self._update_loading_text()
        if self._completed_jobs >= len(self._pending_images):
            self._finish_thumbnail_loading(generation)
        else:
            self._start_more_thumbnail_jobs(generation)

    def _update_loading_text(self) -> None:
        if self._capture_sort_waiting:
            self._set_file_name_text("Aufnahmedaten werden gelesen …")
            return
        self._set_file_name_text(
            f"Lade Vorschaubilder: {self._completed_jobs} von {len(self._pending_images)}"
        )

    def _finish_thumbnail_loading(self, generation: int) -> None:
        if generation != self._load_generation:
            return
        self._capture_sort_waiting = False
        self._sort_thumbnail_items()
        self._pending_images = [
            Path(self.thumbnail_list.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self.thumbnail_list.count())
        ]
        self._set_thumbnail_size_actions_enabled(True)
        current_item = self.thumbnail_list.currentItem()
        if current_item is not None:
            self.thumbnail_list.scrollToItem(current_item)
        if self.current_image is not None:
            self._set_file_name_text(self.current_image.name)
            return
        count = self.thumbnail_list.count()
        self._set_file_name_text(
            f"{count} Bild" if count == 1 else f"{count} Bilder"
        )

    def _thumbnail_selected(
        self,
        item: QListWidgetItem | None,
        _previous_item: QListWidgetItem | None = None,
    ) -> None:
        if item is None:
            self._update_navigation_buttons()
            return
        self.current_image = Path(item.data(Qt.ItemDataRole.UserRole))
        self._set_file_name_text(self.current_image.name)
        self._load_current_image()
        self._update_navigation_buttons()
        if self._slideshow_running:
            current_key = self._resolved_sort_path(self.current_image)
            matching_index = next(
                (
                    index
                    for index, path in enumerate(self._slideshow_paths)
                    if self._resolved_sort_path(path) == current_key
                ),
                None,
            )
            if matching_index is not None:
                self._slideshow_index = matching_index
            self._restart_slideshow_timer()
            self._update_slideshow_metadata_overlay()

    def _selection_changed(self) -> None:
        self._update_view_actions()

    def _add_rotation_context_submenu(
        self, context_menu: QMenu, image_path: Path | None
    ) -> QMenu:
        rotation_menu = context_menu.addMenu("Drehen")
        rotation_menu.addAction(self.rotate_left_action)
        rotation_menu.addAction(self.rotate_right_action)
        rotation_menu.addAction(self.reset_rotation_action)
        rotation_menu.addSeparator()
        rotation_menu.addAction(self.save_rotated_copy_action)
        rotation_menu.addAction(self.save_rotation_to_original_action)
        self._set_rotation_action_states(image_path)
        return rotation_menu

    def _exec_rotation_context_menu(
        self,
        context_menu: QMenu,
        global_position,
        image_path: Path | None,
    ) -> None:
        self._rotation_context_path = image_path
        self._file_manager_context_path = image_path
        self._rename_context_path = image_path
        self._set_file_manager_action_state(image_path)
        self._set_rename_action_state(image_path)
        self._add_rotation_context_submenu(context_menu, image_path)
        try:
            context_menu.exec(global_position)
        finally:
            self._rotation_context_path = None
            self._file_manager_context_path = None
            self._rename_context_path = None
            self._export_context_path = None
            self._update_view_actions()

    def _show_image_context_menu(self, global_position) -> None:
        context_menu = QMenu(self.image_scroll_area.viewport())
        image_path = (
            self.current_image if not self.original_image.isNull() else None
        )
        self._export_context_path = image_path
        self._set_rename_action_state(image_path)
        context_menu.addAction(self.rename_image_action)
        context_menu.addAction(self.export_resized_action)
        context_menu.addAction(self.show_in_file_manager_action)
        context_menu.addSeparator()
        self._exec_rotation_context_menu(
            context_menu, global_position, image_path
        )

    def _show_thumbnail_context_menu(self, position) -> None:
        clicked_item = self.thumbnail_list.itemAt(position)
        context_menu = QMenu(self.thumbnail_list)
        context_image_path = None

        if clicked_item is not None:
            if clicked_item.isSelected():
                self.thumbnail_list.setCurrentItem(
                    clicked_item,
                    QItemSelectionModel.SelectionFlag.NoUpdate,
                )
            else:
                self.thumbnail_list.setCurrentItem(
                    clicked_item,
                    QItemSelectionModel.SelectionFlag.ClearAndSelect,
                )
            context_image_path = Path(
                clicked_item.data(Qt.ItemDataRole.UserRole)
            )
            context_menu.addAction(self.copy_image_action)
            context_menu.addAction(self.cut_image_action)
            context_menu.addAction(self.paste_image_action)
            context_menu.addSeparator()
            context_menu.addAction(self.select_all_action)
            context_menu.addSeparator()
            self._file_manager_context_path = context_image_path
            self._set_file_manager_action_state(context_image_path)
            self._rename_context_path = context_image_path
            self._export_context_path = context_image_path
            self._set_rename_action_state(context_image_path)
            context_menu.addAction(self.rename_image_action)
            context_menu.addAction(self.export_resized_action)
            context_menu.addAction(self.show_in_file_manager_action)
            context_menu.addSeparator()
            self._rotation_context_path = context_image_path
            self._add_rotation_context_submenu(
                context_menu, context_image_path
            )
            context_menu.addSeparator()
            context_menu.addAction(self.compare_images_action)
            context_menu.addAction(self.trash_image_action)
        else:
            context_menu.addAction(self.paste_image_action)
            context_menu.addAction(self.select_all_action)
            context_menu.addSeparator()
            self._file_manager_context_path = None
            self._set_file_manager_action_state(None)
            self._rename_context_path = None
            self._export_context_path = None
            self._set_rename_action_state(None)
            context_menu.addAction(self.rename_image_action)
            context_menu.addAction(self.export_resized_action)
            context_menu.addAction(self.show_in_file_manager_action)
            context_menu.addSeparator()
            self._rotation_context_path = None
            self._add_rotation_context_submenu(context_menu, None)
            context_menu.addSeparator()
            context_menu.addAction(self.compare_images_action)

        try:
            context_menu.exec(
                self.thumbnail_list.viewport().mapToGlobal(position)
            )
        finally:
            self._rotation_context_path = None
            self._file_manager_context_path = None
            self._rename_context_path = None
            self._export_context_path = None
            self._update_view_actions()

    def _select_all_images(self) -> None:
        self.thumbnail_list.selectAll()
        if self.thumbnail_list.currentRow() < 0 and self.thumbnail_list.count() > 0:
            self.thumbnail_list.setCurrentItem(
                self.thumbnail_list.item(0),
                QItemSelectionModel.SelectionFlag.NoUpdate,
            )

    def _select_relative_image(self, offset: int) -> None:
        if self._slideshow_running:
            self._navigate_slideshow(offset)
            return
        self._select_image(self.thumbnail_list.currentRow() + offset)

    def _select_image(self, row: int) -> None:
        if not 0 <= row < self.thumbnail_list.count():
            return
        target_item = self.thumbnail_list.item(row)
        self.thumbnail_list.setCurrentItem(target_item)
        self.thumbnail_list.scrollToItem(target_item)

    def _set_file_name_text(self, text: str) -> None:
        self._file_name_text = text
        available_width = max(0, self.file_name_label.width() - 12)
        displayed_text = self.file_name_label.fontMetrics().elidedText(
            text,
            Qt.TextElideMode.ElideMiddle,
            available_width,
        )
        self.file_name_label.setText(displayed_text)
        self.file_name_label.setToolTip(text)

    def _update_navigation_buttons(self) -> None:
        current_row = self.thumbnail_list.currentRow()
        last_row = self.thumbnail_list.count() - 1
        self.previous_button.setEnabled(current_row > 0)
        self.next_button.setEnabled(0 <= current_row < last_row)
        self.first_image_action.setEnabled(last_row >= 0 and current_row != 0)
        self.previous_image_action.setEnabled(current_row > 0)
        self.next_image_action.setEnabled(last_row >= 0 and current_row < last_row)
        self.last_image_action.setEnabled(last_row >= 0 and current_row != last_row)
        if self._slideshow_running and self._slideshow_paths:
            multiple = len(self._slideshow_paths) > 1
            can_go_back = multiple and (
                self._slideshow_repeat or self._slideshow_index > 0
            )
            can_go_forward = multiple and (
                self._slideshow_repeat
                or self._slideshow_index < len(self._slideshow_paths) - 1
            )
            self.previous_button.setEnabled(can_go_back)
            self.next_button.setEnabled(can_go_forward)
            self.previous_image_action.setEnabled(can_go_back)
            self.next_image_action.setEnabled(can_go_forward)
            self.first_image_action.setEnabled(
                multiple and self._slideshow_index != 0
            )
            self.last_image_action.setEnabled(
                multiple and self._slideshow_index != len(self._slideshow_paths) - 1
            )
        self.select_all_action.setEnabled(last_row >= 0)
        if hasattr(self, "directory_path_label"):
            self._update_directory_heading()
        self._update_status_bar()

    def _create_directory_navigation_buttons(self) -> None:
        self.directory_path_label = QLabel(self.directory_panel)
        self.directory_path_label.setObjectName("directoryPathLabel")
        self.directory_path_label.setStyleSheet("font-size: 11px;")
        self.directory_path_label.setToolTip("")
        self.directory_path_label.installEventFilter(self)

        navigation_row = QHBoxLayout()
        navigation_row.setContentsMargins(0, 0, 0, 0)
        navigation_row.setSpacing(4)
        button_specs = (
            ("previous_folder_button", "←", self.previous_folder_action),
            ("next_folder_button", "→", self.next_folder_action),
            ("parent_folder_button", "↑", self.parent_folder_action),
        )
        for attribute_name, text, action in button_specs:
            button = QToolButton(self.directory_panel)
            button.setDefaultAction(action)
            button.setText(text)
            button.setToolTip(action.toolTip())
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setFixedSize(30, 26)
            navigation_row.addWidget(button)
            setattr(self, attribute_name, button)
        navigation_row.addStretch(1)
        directory_layout = self.directory_panel.layout()
        if isinstance(directory_layout, QVBoxLayout):
            directory_layout.insertWidget(1, self.directory_path_label)
            directory_layout.insertLayout(2, navigation_row)
        self._update_directory_heading()
        self._update_folder_navigation_actions()

    def _update_folder_navigation_actions(self) -> None:
        self.previous_folder_action.setEnabled(self._folder_history_index > 0)
        self.next_folder_action.setEnabled(
            0 <= self._folder_history_index < len(self._folder_history) - 1
        )
        has_parent = (
            self.current_directory is not None
            and self.current_directory.parent != self.current_directory
        )
        self.parent_folder_action.setEnabled(has_parent)
        for attribute_name, text in (
            ("previous_folder_button", "←"),
            ("next_folder_button", "→"),
            ("parent_folder_button", "↑"),
        ):
            button = getattr(self, attribute_name, None)
            if button is not None:
                button.setText(text)

    def _update_directory_heading(self) -> None:
        if self.current_directory is None:
            self.directory_heading_label.setText("Kein Ordner")
            self._directory_path_text = ""
        else:
            directory = self.current_directory
            self.directory_heading_label.setText(
                directory.name or str(directory)
            )
            try:
                relative_path = directory.relative_to(HOME_DIRECTORY)
                display_path = str(Path("~") / relative_path)
            except ValueError:
                display_path = str(directory)
            image_count = self.thumbnail_list.count()
            count_text = (
                f"{image_count} Bild"
                if image_count == 1
                else f"{image_count} Bilder"
            )
            self._directory_path_text = f"{display_path} · {count_text}"

        available_width = max(0, self.directory_path_label.width() - 4)
        displayed_text = self.directory_path_label.fontMetrics().elidedText(
            self._directory_path_text,
            Qt.TextElideMode.ElideMiddle,
            available_width,
        )
        self.directory_path_label.setText(displayed_text)
        self.directory_path_label.setToolTip(self._directory_path_text)

    def _update_status_bar(self) -> None:
        current_row = self.thumbnail_list.currentRow()
        if (
            self.current_image is None
            or self.original_image.isNull()
            or current_row < 0
        ):
            self._status_full_text = "Kein Bild ausgewählt"
            self.status_info_label.setText(self._status_full_text)
            self.status_info_label.setToolTip("")
            self.status_zoom_label.clear()
            self.status_zoom_label.setToolTip("")
            return

        resolved_path = self._resolved_sort_path(self.current_image)
        metadata = self._image_metadata_by_path.get(resolved_path, {})
        parts = [
            f"Bild {current_row + 1} von {self.thumbnail_list.count()}",
            f"{self.original_image.width()} × {self.original_image.height()} Pixel",
        ]
        if self._current_file_size is not None:
            parts.append(format_file_size(self._current_file_size))
        for key, prefix in (
            ("recording_time", "Aufgenommen "),
            ("camera", "Kamera "),
            ("lens", "Objektiv "),
            ("exposure", ""),
            ("aperture", ""),
            ("focal_length", ""),
            ("iso", "ISO "),
            ("gps", ""),
        ):
            value = metadata.get(key)
            if value:
                parts.append(f"{prefix}{value}")

        self._status_full_text = " | ".join(parts)
        self._refresh_status_info_text()
        zoom_text = f"Zoom {round(self._zoom_factor * 100)} %"
        self.status_zoom_label.setText(zoom_text)

        tooltip_lines = [
            f"Datei: {self.current_image.name}",
            f"Pfad: {self.current_image}",
            f"Position: Bild {current_row + 1} von {self.thumbnail_list.count()}",
            f"Abmessungen: {self.original_image.width()} × "
            f"{self.original_image.height()} Pixel",
        ]
        if self._current_file_size is not None:
            tooltip_lines.append(
                f"Dateigröße: {format_file_size(self._current_file_size)}"
            )
        for key, label in (
            ("recording_time", "Aufnahmezeit"),
            ("camera", "Kamera"),
            ("lens", "Objektiv"),
            ("exposure", "Belichtungszeit"),
            ("aperture", "Blende"),
            ("focal_length", "Brennweite"),
            ("iso", "ISO"),
        ):
            value = metadata.get(key)
            if value:
                tooltip_lines.append(f"{label}: {value}")
        if metadata.get("gps_detail"):
            tooltip_lines.append(metadata["gps_detail"])
        tooltip_lines.append(zoom_text)
        complete_tooltip = "\n".join(tooltip_lines)
        self.status_info_label.setToolTip(complete_tooltip)
        self.status_zoom_label.setToolTip(complete_tooltip)

    def _refresh_status_info_text(self) -> None:
        available_width = max(0, self.status_info_label.width() - 8)
        displayed_text = self.status_info_label.fontMetrics().elidedText(
            self._status_full_text,
            Qt.TextElideMode.ElideRight,
            available_width,
        )
        self.status_info_label.setText(displayed_text)

    def _load_current_image(self) -> None:
        self._hide_zoom_indicator()
        if self.current_image is None:
            self._exif_oriented_image = QImage()
            self._current_file_size = None
            self._clear_pdf_state()
            self._update_status_bar()
            return
        if self.current_image.suffix.lower() in PDF_EXTENSIONS:
            result = load_pdf(self.current_image)
            if result.document is None:
                self._clear_pdf_state()
                self.original_image = QImage()
                self.image_label.setText(result.error or "Die PDF konnte nicht geöffnet werden")
                self._update_view_actions()
                return
            self._pdf_document = result.document
            self._pdf_page = 0
            self._pdf_render_size = QSize()
            self._zoom_mode = "fit"
            self._render_pdf_page()
            return
        if self._pdf_preview_mode:
            self._leave_pdf_preview()
        self._pdf_document = None
        self._pdf_page = 0
        self._pdf_render_size = QSize()
        self._update_pdf_page_navigation()
        try:
            self._current_file_size = self.current_image.stat().st_size
        except OSError:
            self._current_file_size = None
        reader = QImageReader(str(self.current_image))
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            self.original_image = QImage()
            self._exif_oriented_image = QImage()
            self._zoom_mode = "fit"
            self._zoom_factor = 1.0
            self.image_label.clear()
            self.image_label.resize(self.image_scroll_area.viewport().size())
            self.image_label.setText("Bild konnte nicht geladen werden")
            self._update_view_actions()
            self._update_status_bar()
            return
        self._exif_oriented_image = image
        rotation = self._display_rotation_by_path.get(
            self._resolved_sort_path(self.current_image), 0
        )
        self.original_image = rotated_display_image(
            self._exif_oriented_image, rotation
        )
        self._update_view_actions()
        self._zoom_mode = "fit"
        self._render_current_image()

    def _render_pdf_page(
        self,
        requested_page: int | None = None,
        schedule_quality_refresh: bool = True,
    ) -> bool:
        if self._pdf_document is None:
            return False
        page_count = self._pdf_document.pageCount()
        if page_count < 1:
            self._clear_pdf_state()
            self.image_label.setText("Die PDF enthält keine Seiten.")
            return False
        page = self._pdf_page if requested_page is None else requested_page
        page = max(0, min(page_count - 1, page))
        viewport = self.image_scroll_area.viewport().size()
        render_scale = self._zoom_factor if self._zoom_mode == "manual" else 1.0
        target = pdf_display_target_size(
            viewport,
            render_scale,
        )
        image = render_pdf_page_with_fallback(self._pdf_document, page, target)
        if image.isNull() or image.width() <= 0 or image.height() <= 0:
            self.original_image = QImage()
            self.image_label.clear()
            self.image_label.resize(self.image_scroll_area.viewport().size())
            self.image_label.setText("Die PDF-Seite konnte nicht gerendert werden")
            self._update_pdf_page_navigation()
            return False
        self._pdf_page = page
        self.original_image = image
        self._pdf_render_size = image.size()
        if self._zoom_mode != "manual":
            self._zoom_mode = "fit"
        self._render_current_image()
        self._set_file_name_text(self.current_image.name)
        self._update_pdf_page_navigation()
        if schedule_quality_refresh:
            self._schedule_pdf_quality_refresh()
        return True

    def _change_pdf_page(self, offset: int) -> None:
        if self._pdf_document is None:
            return
        page_count = self._pdf_document.pageCount()
        if page_count < 1:
            self._clear_pdf_state()
            return
        requested_page = max(0, min(page_count - 1, self._pdf_page + offset))
        self._render_pdf_page(requested_page)

    def _clear_pdf_state(self) -> None:
        self._pdf_document = None
        self._pdf_page = 0
        self._pdf_render_size = QSize()
        self._pdf_quality_refresh_pending = False
        self._update_pdf_page_navigation()

    def _schedule_pdf_quality_refresh(self) -> None:
        if self._pdf_document is None or self._pdf_quality_refresh_pending:
            return
        self._pdf_quality_refresh_pending = True
        QTimer.singleShot(0, self._refresh_pdf_render_quality)

    def _refresh_pdf_render_quality(self) -> None:
        self._pdf_quality_refresh_pending = False
        if self._pdf_document is None or self.original_image.isNull():
            return
        render_scale = self._zoom_factor if self._zoom_mode == "manual" else 1.0
        required_size = pdf_page_render_size(
            self._pdf_document,
            self._pdf_page,
            pdf_display_target_size(
                self.image_scroll_area.viewport().size(), render_scale
            ),
        )
        if (
            required_size.isEmpty()
            or (
                self._pdf_render_size.width() >= required_size.width()
                and self._pdf_render_size.height() >= required_size.height()
            )
        ):
            return
        self._render_pdf_page(
            self._pdf_page,
            schedule_quality_refresh=False,
        )

    def _update_pdf_page_navigation(self) -> None:
        document = self._pdf_document
        page_count = document.pageCount() if document is not None else 0
        is_pdf = page_count > 0
        self.pdf_page_navigation.setVisible(is_pdf and page_count > 1)
        self.previous_pdf_page_action.setEnabled(is_pdf and self._pdf_page > 0)
        self.next_pdf_page_action.setEnabled(is_pdf and self._pdf_page + 1 < page_count)
        if not is_pdf:
            self.pdf_page_label.clear()
            self.previous_pdf_page_button.setEnabled(False)
            self.next_pdf_page_button.setEnabled(False)
            return
        self.pdf_page_label.setText(f"Seite {self._pdf_page + 1} von {page_count}")
        self.previous_pdf_page_button.setEnabled(self._pdf_page > 0)
        self.next_pdf_page_button.setEnabled(self._pdf_page + 1 < page_count)

    def _activate_rotation_target(self, image_path: Path | None = None) -> bool:
        target_path = image_path or self.current_image
        if target_path is None:
            return False
        target_key = self._resolved_sort_path(target_path)
        current_key = (
            self._resolved_sort_path(self.current_image)
            if self.current_image is not None
            else None
        )
        if target_key != current_key or self._exif_oriented_image.isNull():
            item = self._thumbnail_item_for_path(target_path)
            if item is not None:
                self.thumbnail_list.setCurrentItem(
                    item, QItemSelectionModel.SelectionFlag.NoUpdate
                )
                self.thumbnail_list.scrollToItem(item)
            if (
                self.current_image is None
                or self._resolved_sort_path(self.current_image) != target_key
                or self._exif_oriented_image.isNull()
            ):
                self.current_image = target_path
                self._set_file_name_text(target_path.name)
                self._load_current_image()
        return (
            self.current_image is not None
            and self._resolved_sort_path(self.current_image) == target_key
            and not self._exif_oriented_image.isNull()
        )

    def _rotate_current_image(
        self, degrees: int, image_path: Path | None = None
    ) -> None:
        if not self._activate_rotation_target(image_path):
            return
        path_key = self._resolved_sort_path(self.current_image)
        rotation = (
            self._display_rotation_by_path.get(path_key, 0) + degrees
        ) % 360
        if rotation == 0:
            self._display_rotation_by_path.pop(path_key, None)
        else:
            self._display_rotation_by_path[path_key] = rotation
        self._apply_current_display_rotation(rotation)

    def _current_display_rotation(self, image_path: Path | None = None) -> int:
        target_path = image_path or self.current_image
        if target_path is None:
            return 0
        return self._display_rotation_by_path.get(
            self._resolved_sort_path(target_path), 0
        )

    def _reset_current_rotation(self, image_path: Path | None = None) -> None:
        if not self._activate_rotation_target(image_path):
            return
        self._display_rotation_by_path.pop(
            self._resolved_sort_path(self.current_image), None
        )
        self._apply_current_display_rotation(0)

    def _apply_current_display_rotation(self, rotation: int) -> None:
        self.original_image = rotated_display_image(
            self._exif_oriented_image, rotation
        )
        self._zoom_mode = "fit"
        self._render_current_image()
        self.image_scroll_area.horizontalScrollBar().setValue(0)
        self.image_scroll_area.verticalScrollBar().setValue(0)
        self._show_zoom_indicator()
        self._update_view_actions()

    def _suggested_rotated_copy_path(self) -> Path | None:
        if self.current_image is None:
            return None
        base_path = self.current_image.with_name(
            f"{self.current_image.stem}-gedreht{self.current_image.suffix}"
        )
        if not base_path.exists():
            return base_path
        counter = 1
        while True:
            candidate = self.current_image.with_name(
                f"{self.current_image.stem}-gedreht-{counter}"
                f"{self.current_image.suffix}"
            )
            if not candidate.exists():
                return candidate
            counter += 1

    def _animated_gif_save_unsupported(self) -> bool:
        if self.current_image is None or self.current_image.suffix.lower() != ".gif":
            return False
        try:
            with PillowImage.open(self.current_image) as image:
                is_animated = bool(getattr(image, "is_animated", False))
        except Exception:
            return False
        if not is_animated:
            return False
        dialog = QMessageBox(self.window)
        dialog.setWindowTitle("Drehung speichern")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText(
            "Das dauerhafte Drehen animierter GIF-Dateien wird derzeit nicht "
            "unterstützt."
        )
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.button(QMessageBox.StandardButton.Ok).setText("OK")
        self._style_message_box(dialog)
        dialog.exec()
        return True

    def _save_rotated_copy(self, image_path: Path | None = None) -> None:
        if not self._activate_rotation_target(image_path):
            return
        if self._current_display_rotation() == 0:
            return
        if self._animated_gif_save_unsupported():
            return
        suggested_path = self._suggested_rotated_copy_path()
        if suggested_path is None:
            return
        destination_name, _selected_filter = QFileDialog.getSaveFileName(
            self.window,
            "Gedrehte Kopie speichern",
            str(suggested_path),
            "Bilder (*.jpg *.jpeg *.png *.webp *.tif *.tiff *.bmp)",
        )
        if not destination_name:
            return
        destination = Path(destination_name)
        if (
            self.current_image is not None
            and self._resolved_sort_path(destination)
            == self._resolved_sort_path(self.current_image)
        ):
            self._show_rotation_save_error(
                "Für das Überschreiben der Originaldatei verwenden Sie bitte "
                "„Drehung im Original speichern …“."
            )
            return
        if destination.exists() and not self._confirm_rotated_copy_overwrite(
            destination
        ):
            return
        if self._write_rotated_image(destination, replace_original=False):
            self._show_directory(destination.parent, [destination])

    def _confirm_rotated_copy_overwrite(self, destination: Path) -> bool:
        dialog = QMessageBox(self.window)
        dialog.setWindowTitle("Datei überschreiben")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText("Die gewählte Datei ist bereits vorhanden.")
        dialog.setInformativeText(str(destination))
        overwrite_button = dialog.addButton(
            "Überschreiben", QMessageBox.ButtonRole.AcceptRole
        )
        cancel_button = dialog.addButton(
            "Abbrechen", QMessageBox.ButtonRole.RejectRole
        )
        dialog.setDefaultButton(cancel_button)
        dialog.setEscapeButton(cancel_button)
        self._style_message_box(dialog)
        dialog.exec()
        return dialog.clickedButton() is overwrite_button

    def _save_rotation_to_original(
        self, image_path: Path | None = None
    ) -> None:
        if not self._activate_rotation_target(image_path):
            return
        if self.current_image is None or self._current_display_rotation() == 0:
            return
        if self._animated_gif_save_unsupported():
            return
        image_path = self.current_image
        if not os.access(image_path, os.W_OK):
            self._show_rotation_save_error(
                "Die Originaldatei ist schreibgeschützt oder es fehlen "
                "Schreibrechte."
            )
            return
        dialog = QMessageBox(self.window)
        dialog.setWindowTitle("Drehung im Original speichern")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(
            "Möchtest du die Drehung dauerhaft in der Originaldatei speichern?\n\n"
            "Die Bilddaten werden neu gespeichert. Dieser Vorgang kann in "
            "BildBlick nicht direkt rückgängig gemacht werden."
        )
        dialog.setInformativeText(
            f"Dateiname: {image_path.name}\n"
            f"Dateipfad: {image_path}\n"
            f"Aktuelle Drehung: {self._display_rotation_description()}"
        )
        overwrite_button = dialog.addButton(
            "Original überschreiben", QMessageBox.ButtonRole.DestructiveRole
        )
        cancel_button = dialog.addButton(
            "Abbrechen", QMessageBox.ButtonRole.RejectRole
        )
        dialog.setDefaultButton(cancel_button)
        dialog.setEscapeButton(cancel_button)
        self._style_message_box(dialog)
        dialog.exec()
        if dialog.clickedButton() is not overwrite_button:
            return

        try:
            old_cache_name = thumbnail_cache_name(
                image_path, self._thumbnail_size
            )
        except OSError:
            old_cache_name = None
        selected_paths = self._selected_image_paths()
        if image_path not in selected_paths:
            selected_paths.insert(0, image_path)
        else:
            selected_paths.remove(image_path)
            selected_paths.insert(0, image_path)
        if not self._write_rotated_image(image_path, replace_original=True):
            return

        resolved_path = self._resolved_sort_path(image_path)
        self._display_rotation_by_path.pop(resolved_path, None)
        self._invalidate_saved_image_caches(image_path, old_cache_name)
        self._show_directory(image_path.parent, selected_paths)
        self._show_rotation_saved_confirmation()

    def _display_rotation_description(self) -> str:
        rotation = self._current_display_rotation()
        if rotation == 90:
            return "90° nach rechts"
        if rotation == 180:
            return "180°"
        if rotation == 270:
            return "90° nach links"
        return "0°"

    @staticmethod
    def _pillow_image_from_qimage(image: QImage):
        rgba_image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        pixel_data = bytes(rgba_image.constBits())
        return PillowImage.frombuffer(
            "RGBA",
            (rgba_image.width(), rgba_image.height()),
            pixel_data,
            "raw",
            "RGBA",
            rgba_image.bytesPerLine(),
            1,
        ).copy()

    @staticmethod
    def _save_format_for_path(path: Path) -> str | None:
        return {
            ".jpg": "JPEG",
            ".jpeg": "JPEG",
            ".png": "PNG",
            ".webp": "WEBP",
            ".tif": "TIFF",
            ".tiff": "TIFF",
            ".bmp": "BMP",
        }.get(path.suffix.lower())

    def _source_metadata_for_save(
        self, save_format: str
    ) -> tuple[dict[str, object], list[str]]:
        metadata: dict[str, object] = {}
        warnings: list[str] = []
        if self.current_image is None:
            return metadata, warnings
        try:
            with PillowImage.open(self.current_image) as source_image:
                if save_format in {"JPEG", "PNG", "WEBP", "TIFF"}:
                    try:
                        exif = source_image.getexif()
                        exif[274] = 1
                        metadata["exif"] = exif.tobytes()
                    except Exception as error:
                        warnings.append(f"EXIF-Daten: {error}")
                icc_profile = source_image.info.get("icc_profile")
                if icc_profile and save_format != "BMP":
                    metadata["icc_profile"] = icc_profile
                dpi = source_image.info.get("dpi")
                if dpi:
                    metadata["dpi"] = dpi
        except Exception as error:
            warnings.append(f"Metadaten konnten nicht vollständig gelesen werden: {error}")
        return metadata, warnings

    def _write_rotated_image(
        self, destination: Path, replace_original: bool
    ) -> bool:
        save_format = self._save_format_for_path(destination)
        if save_format is None:
            self._show_rotation_save_error(
                "Das gewählte Bildformat wird nicht unterstützt."
            )
            return False
        if self.current_image is None or self.original_image.isNull():
            return False
        if not destination.parent.is_dir():
            self._show_rotation_save_error("Der Zielordner existiert nicht.")
            return False

        metadata, metadata_warnings = self._source_metadata_for_save(save_format)
        image = self._pillow_image_from_qimage(self.original_image)
        save_options: dict[str, object] = dict(metadata)
        if save_format == "JPEG":
            image = image.convert("RGB")
            save_options.update(quality=95, optimize=True)
        elif save_format == "WEBP":
            save_options.update(quality=95, method=6)
        elif save_format == "BMP":
            image = image.convert("RGB")
        elif save_format == "TIFF":
            save_options["compression"] = "tiff_deflate"

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{destination.stem}-",
                suffix=destination.suffix,
                dir=destination.parent,
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
            try:
                image.save(temporary_path, format=save_format, **save_options)
            except (TypeError, ValueError) as metadata_error:
                metadata_warnings.append(
                    f"Einige Metadaten konnten nicht geschrieben werden: {metadata_error}"
                )
                fallback_options = {
                    key: value
                    for key, value in save_options.items()
                    if key in {"quality", "optimize", "method", "compression"}
                }
                image.save(
                    temporary_path, format=save_format, **fallback_options
                )
            if not temporary_path.is_file() or temporary_path.stat().st_size <= 0:
                raise OSError(
                    "Die temporäre Bilddatei wurde nicht vollständig gespeichert."
                )
            with PillowImage.open(temporary_path) as verification_image:
                verification_image.verify()
            if replace_original:
                original_mode = destination.stat().st_mode
                os.chmod(temporary_path, original_mode)
            os.replace(temporary_path, destination)
            temporary_path = None
        except Exception as error:
            self._show_rotation_save_error(str(error))
            return False
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

        if metadata_warnings:
            self._show_metadata_save_warning(metadata_warnings)
        return True

    def _invalidate_saved_image_caches(
        self, image_path: Path, old_cache_name: str | None
    ) -> None:
        cache_names = {old_cache_name} if old_cache_name is not None else set()
        try:
            cache_names.add(thumbnail_cache_name(image_path, self._thumbnail_size))
        except OSError:
            pass
        for cache_directory in (CACHE_DIRECTORY, LEGACY_CACHE_DIRECTORY):
            for cache_name in cache_names:
                try:
                    (cache_directory / cache_name).unlink(missing_ok=True)
                except OSError:
                    pass
        resolved_path = self._resolved_sort_path(image_path)
        self._metadata_cache = {
            key: value
            for key, value in self._metadata_cache.items()
            if key[0] != resolved_path
        }
        self._image_metadata_cache = {
            key: value
            for key, value in self._image_metadata_cache.items()
            if key[0] != resolved_path
        }
        self._image_metadata_by_path.pop(resolved_path, None)
        self._recording_date_cache.pop(resolved_path, None)
        self._file_sort_metadata.pop(resolved_path, None)

    def _show_rotation_save_error(self, detail: str) -> None:
        dialog = QMessageBox(self.window)
        dialog.setWindowTitle("Drehung konnte nicht gespeichert werden")
        dialog.setIcon(QMessageBox.Icon.Critical)
        dialog.setText("Das gedrehte Bild konnte nicht gespeichert werden.")
        dialog.setInformativeText(detail)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.button(QMessageBox.StandardButton.Ok).setText("OK")
        self._style_message_box(dialog)
        dialog.exec()

    def _show_metadata_save_warning(self, warnings: list[str]) -> None:
        dialog = QMessageBox(self.window)
        dialog.setWindowTitle("Bild mit eingeschränkten Metadaten gespeichert")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(
            "Das Bild wurde gespeichert, einige Metadaten konnten jedoch nicht "
            "vollständig erhalten werden."
        )
        dialog.setDetailedText("\n".join(warnings))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.button(QMessageBox.StandardButton.Ok).setText("OK")
        self._style_message_box(dialog)
        dialog.exec()

    def _show_rotation_saved_confirmation(self) -> None:
        dialog = QMessageBox(self.window)
        dialog.setWindowTitle("Drehung gespeichert")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText("Die Drehung wurde im Original gespeichert.")
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.button(QMessageBox.StandardButton.Ok).setText("OK")
        self._style_message_box(dialog)
        dialog.exec()

    def _render_current_image(self) -> None:
        self._image_render_pending = False
        if self.original_image.isNull():
            return
        viewport_size = self.image_scroll_area.viewport().size()
        if viewport_size.width() <= 1 or viewport_size.height() <= 1:
            return
        if self._zoom_mode == "fit":
            self._zoom_factor = image_fit_zoom_factor(
                self.original_image, viewport_size
            )
        scaled_size = image_size_at_zoom(
            self.original_image, self._zoom_factor
        )
        scaled_image = self.original_image.scaled(
            scaled_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.resize(scaled_size)
        self.image_label.setPixmap(QPixmap.fromImage(scaled_image))
        if self._zoom_mode == "fit":
            self.image_scroll_area.horizontalScrollBar().setValue(0)
            self.image_scroll_area.verticalScrollBar().setValue(0)
        self._update_status_bar()

    def _fit_image_to_window(self) -> None:
        if self.original_image.isNull():
            return
        self._zoom_mode = "fit"
        self._render_current_image()
        self._show_zoom_indicator()

    def _show_image_at_actual_size(self) -> None:
        if self.original_image.isNull():
            return
        self._zoom_mode = "manual"
        self._zoom_factor = 1.0
        self._render_current_image()
        self._show_zoom_indicator()
        horizontal_bar = self.image_scroll_area.horizontalScrollBar()
        vertical_bar = self.image_scroll_area.verticalScrollBar()
        horizontal_bar.setValue(horizontal_bar.maximum() // 2)
        vertical_bar.setValue(vertical_bar.maximum() // 2)

    def _zoom_at(self, viewport_position, factor: float) -> None:
        if self.original_image.isNull():
            return
        old_size = self.image_label.size()
        label_position = self.image_label.pos()
        relative_x = min(
            1.0,
            max(0.0, (viewport_position.x() - label_position.x()) / old_size.width()),
        )
        relative_y = min(
            1.0,
            max(0.0, (viewport_position.y() - label_position.y()) / old_size.height()),
        )
        self._zoom_mode = "manual"
        self._zoom_factor = min(MAX_ZOOM, max(MIN_ZOOM, self._zoom_factor * factor))
        self._render_current_image()
        self._show_zoom_indicator()
        horizontal_bar = self.image_scroll_area.horizontalScrollBar()
        vertical_bar = self.image_scroll_area.verticalScrollBar()
        horizontal_bar.setValue(
            round(relative_x * self.image_label.width() - viewport_position.x())
        )
        vertical_bar.setValue(
            round(relative_y * self.image_label.height() - viewport_position.y())
        )

    def _schedule_image_render(self, *_args) -> None:
        if self._image_render_pending or self.original_image.isNull():
            return
        if self._pdf_document is not None:
            self._schedule_pdf_quality_refresh()
        self._image_render_pending = True
        QTimer.singleShot(0, self._render_current_image)

    def _position_zoom_indicator(self) -> None:
        if not self.zoom_indicator.isVisible():
            return
        viewport = self.image_scroll_area.viewport()
        margin = 16
        self.zoom_indicator.move(
            max(margin, viewport.width() - self.zoom_indicator.width() - margin),
            max(margin, viewport.height() - self.zoom_indicator.height() - margin),
        )

    def _show_zoom_indicator(self) -> None:
        if self.original_image.isNull():
            return
        prefix = "Eingepasst · " if self._zoom_mode == "fit" else ""
        self.zoom_indicator.setText(
            f"{prefix}{round(self._zoom_factor * 100)} %"
        )
        self.zoom_indicator.adjustSize()
        self.zoom_indicator.show()
        self.zoom_indicator.raise_()
        self._position_zoom_indicator()
        self.zoom_indicator_timer.start(ZOOM_INDICATOR_DURATION)

    def _hide_zoom_indicator(self) -> None:
        self.zoom_indicator_timer.stop()
        self.zoom_indicator.hide()

    def _show_fullscreen_tooltip(self, global_position) -> None:
        if not self._fullscreen_mode or self._fullscreen_tooltip_visible:
            return
        self._fullscreen_tooltip_visible = True
        QToolTip.showText(global_position, FULLSCREEN_TOOLTIP, self.window)
        self.fullscreen_tooltip_timer.start(FULLSCREEN_TOOLTIP_DURATION)

    def _hide_fullscreen_tooltip(self) -> None:
        QToolTip.hideText()
        self._fullscreen_tooltip_visible = False

    def _enter_pdf_preview(self) -> None:
        """Show a directly opened PDF without the directory and thumbnail panes."""
        if self._pdf_preview_mode or self._fullscreen_mode:
            return
        self._pdf_preview_mode = True
        self._pdf_preview_main_splitter_sizes = self.splitter.sizes()
        self._pdf_preview_right_splitter_sizes = self.right_splitter.sizes()
        self.directory_panel.hide()
        self.thumbnail_panel.hide()
        self.splitter.handle(1).hide()
        self.right_splitter.handle(1).hide()
        self.splitter.setSizes([0, max(1, self.splitter.width())])
        self.right_splitter.setSizes([0, max(1, self.right_splitter.width())])
        self.leave_pdf_preview_action.setEnabled(True)
        self._schedule_image_render()

    def _leave_pdf_preview(self) -> None:
        """Restore the file panes after a direct PDF preview."""
        if not self._pdf_preview_mode:
            return
        if self._fullscreen_mode:
            self._leave_fullscreen()
        self._pdf_preview_mode = False
        self.directory_panel.show()
        self.thumbnail_panel.show()
        self.splitter.handle(1).show()
        self.right_splitter.handle(1).show()
        self.splitter.setSizes(self._pdf_preview_main_splitter_sizes)
        self.right_splitter.setSizes(self._pdf_preview_right_splitter_sizes)
        self.leave_pdf_preview_action.setEnabled(False)
        self._schedule_image_render()

    def _enter_fullscreen(self) -> None:
        if self._fullscreen_mode or self.original_image.isNull():
            return

        self._fullscreen_mode = True
        self.fullscreen_action.setChecked(True)
        self._normal_geometry = self.window.geometry()
        self._normal_was_maximized = self.window.isMaximized()
        self._normal_main_splitter_sizes = self.splitter.sizes()
        self._normal_right_splitter_sizes = self.right_splitter.sizes()
        self._normal_window_style = self.window.styleSheet()
        self._normal_image_style = self.image_label.styleSheet()

        central_layout = self.window.centralWidget().layout()
        if central_layout is not None:
            self._normal_central_margins = central_layout.getContentsMargins()
            central_layout.setContentsMargins(0, 0, 0, 0)

        self.directory_panel.hide()
        self.thumbnail_panel.hide()
        self.previous_button.hide()
        self.next_button.hide()
        self.file_name_label.hide()
        self.window.menuBar().hide()
        self.splitter.handle(1).hide()
        self.right_splitter.handle(1).hide()
        self.splitter.setSizes([0, max(1, self.splitter.width())])
        self.right_splitter.setSizes([0, max(1, self.right_splitter.width())])
        self.window.setStyleSheet("background-color: black;")
        self.image_label.setStyleSheet("background-color: black;")
        self.window.showFullScreen()
        self._schedule_image_render()
        self._show_fullscreen_tooltip(QCursor.pos())
        self._position_slideshow_overlays()
        self._restart_slideshow_cursor_timer()

    def _leave_fullscreen(self) -> None:
        if not self._fullscreen_mode:
            return

        self._fullscreen_mode = False
        self._restore_slideshow_cursor()
        self.fullscreen_tooltip_timer.stop()
        self._hide_fullscreen_tooltip()
        self.fullscreen_action.setChecked(False)
        self.window.setStyleSheet(self._normal_window_style)
        self.image_label.setStyleSheet(self._normal_image_style)
        central_layout = self.window.centralWidget().layout()
        if central_layout is not None and self._normal_central_margins is not None:
            central_layout.setContentsMargins(*self._normal_central_margins)

        if not self._pdf_preview_mode:
            self.directory_panel.show()
            self.thumbnail_panel.show()
        self.previous_button.show()
        self.next_button.show()
        self._update_pdf_page_navigation()
        self.file_name_label.show()
        self.window.menuBar().show()
        if not self._pdf_preview_mode:
            self.splitter.handle(1).show()
            self.right_splitter.handle(1).show()

        self.window.showNormal()
        if self._normal_geometry is not None:
            self.window.setGeometry(self._normal_geometry)
        if self._normal_was_maximized:
            self.window.showMaximized()
        if self._pdf_preview_mode:
            self.splitter.setSizes([0, max(1, self.splitter.width())])
            self.right_splitter.setSizes([0, max(1, self.right_splitter.width())])
        else:
            self.splitter.setSizes(self._normal_main_splitter_sizes)
            self.right_splitter.setSizes(self._normal_right_splitter_sizes)
        self._schedule_image_render()

    def eventFilter(self, watched, event) -> bool:
        # Qt can deliver events for the status bar while the window is still
        # being assembled, before the drag-and-drop widgets exist.
        if not all(
            hasattr(self, attribute)
            for attribute in (
                "image_label",
                "image_scroll_area",
                "thumbnail_list",
            )
        ):
            return super().eventFilter(watched, event)
        try:
            image_widgets = (self.image_label, self.image_scroll_area.viewport())
            thumbnail_viewport = self.thumbnail_list.viewport()
        except RuntimeError:
            return False
        if watched is self.window or watched in image_widgets:
            if event.type() == QEvent.Type.DragEnter:
                self.dragEnterEvent(event)
                return event.isAccepted()
            if event.type() == QEvent.Type.DragMove:
                self.dragMoveEvent(event)
                return event.isAccepted()
            if event.type() == QEvent.Type.DragLeave:
                self.dragLeaveEvent(event)
                return event.isAccepted()
            if event.type() == QEvent.Type.Drop:
                self.dropEvent(event)
                return event.isAccepted()
        if watched is thumbnail_viewport:
            if event.type() == QEvent.Type.DragEnter:
                self.dragEnterEvent(event)
                return event.isAccepted()
            if event.type() == QEvent.Type.DragMove:
                self.dragMoveEvent(event)
                return event.isAccepted()
            if event.type() == QEvent.Type.DragLeave:
                self.dragLeaveEvent(event)
                return event.isAccepted()
            if event.type() == QEvent.Type.Drop:
                self.dropEvent(event)
                return event.isAccepted()
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                pressed_item = self.thumbnail_list.itemAt(event.position().toPoint())
                if pressed_item is not None:
                    self._thumbnail_drag_start_position = event.globalPosition().toPoint()
                    self._thumbnail_drag_pressed_path = Path(
                        pressed_item.data(Qt.ItemDataRole.UserRole)
                    )
                    selected_paths = self._selected_thumbnail_paths_in_display_order()
                    self._thumbnail_drag_selected_paths_snapshot = (
                        selected_paths
                        if pressed_item.isSelected() and len(selected_paths) > 1
                        else []
                    )
                else:
                    self._thumbnail_drag_start_position = None
                    self._thumbnail_drag_pressed_path = None
                    self._thumbnail_drag_selected_paths_snapshot = []
            elif (
                event.type() == QEvent.Type.MouseMove
                and self._thumbnail_drag_start_position is not None
                and event.buttons() & Qt.MouseButton.LeftButton
            ):
                current_position = event.globalPosition().toPoint()
                if (
                    current_position - self._thumbnail_drag_start_position
                ).manhattanLength() >= QApplication.startDragDistance():
                    drag_paths = drag_paths_for_selection(
                        self._selected_thumbnail_paths_in_display_order(),
                        self._thumbnail_drag_pressed_path,
                        self._thumbnail_drag_selected_paths_snapshot,
                    )
                    if self._thumbnail_drag_selected_paths_snapshot:
                        self._restore_thumbnail_selection(
                            self._thumbnail_drag_selected_paths_snapshot,
                            self._thumbnail_drag_pressed_path,
                        )
                    self._thumbnail_drag_start_position = None
                    self._thumbnail_drag_pressed_path = None
                    self._thumbnail_drag_selected_paths_snapshot = []
                    return self._start_thumbnail_drag(drag_paths)
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self._thumbnail_drag_start_position = None
                self._thumbnail_drag_pressed_path = None
                self._thumbnail_drag_selected_paths_snapshot = []
        if watched is self.status_info_label:
            if event.type() == QEvent.Type.Resize:
                self._refresh_status_info_text()
            return False
        if watched is self.file_name_label and event.type() == QEvent.Type.Resize:
            self._set_file_name_text(self._file_name_text)
        if (
            hasattr(self, "directory_path_label")
            and watched is self.directory_path_label
            and event.type() == QEvent.Type.Resize
        ):
            self._update_directory_heading()
        if self._fullscreen_mode and watched in image_widgets:
            if event.type() == QEvent.Type.ToolTip:
                return True
            if event.type() in (QEvent.Type.Enter, QEvent.Type.MouseMove):
                if self._slideshow_running:
                    self._restart_slideshow_cursor_timer()
                global_position = (
                    event.globalPosition().toPoint()
                    if event.type() == QEvent.Type.MouseMove
                    else QCursor.pos()
                )
                self._show_fullscreen_tooltip(global_position)
        if watched in image_widgets and event.type() == QEvent.Type.ContextMenu:
            self._restore_slideshow_cursor()
            self._show_image_context_menu(event.globalPos())
            self._restart_slideshow_cursor_timer()
            return True
        if (
            watched is self.image_scroll_area.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            if self.drop_hint_label.isVisible():
                self.drop_hint_label.setGeometry(
                    self.image_scroll_area.viewport().rect()
                )
            self._position_zoom_indicator()
            self._position_slideshow_overlays()
            self._update_slideshow_metadata_overlay()
            if self.original_image.isNull():
                self.image_label.resize(event.size())
            else:
                self._schedule_image_render()
        elif watched in image_widgets and event.type() == QEvent.Type.Wheel:
            wheel_steps = event.angleDelta().y() / 120
            if wheel_steps and not self.original_image.isNull():
                viewport_position = self.image_scroll_area.viewport().mapFromGlobal(
                    event.globalPosition().toPoint()
                )
                self._zoom_at(viewport_position, ZOOM_STEP**wheel_steps)
                return True
        elif (
            watched in image_widgets
            and event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            if self.original_image.isNull():
                return False
            self._mouse_press_position = event.globalPosition().toPoint()
            self._pan_last_position = self._mouse_press_position
            self._dragging_image = False
            return True
        elif (
            watched in image_widgets
            and event.type() == QEvent.Type.MouseMove
            and self._mouse_press_position is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            current_position = event.globalPosition().toPoint()
            if (
                current_position - self._mouse_press_position
            ).manhattanLength() >= QApplication.startDragDistance():
                self._dragging_image = True
            if self._dragging_image:
                movement = current_position - self._pan_last_position
                horizontal_bar = self.image_scroll_area.horizontalScrollBar()
                vertical_bar = self.image_scroll_area.verticalScrollBar()
                horizontal_bar.setValue(horizontal_bar.value() - movement.x())
                vertical_bar.setValue(vertical_bar.value() - movement.y())
            self._pan_last_position = current_position
            return True
        elif (
            watched in image_widgets
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and self._mouse_press_position is not None
        ):
            was_dragging = self._dragging_image
            self._mouse_press_position = None
            self._pan_last_position = None
            self._dragging_image = False
            if not was_dragging:
                self._toggle_fullscreen()
            return True
        return False

    def show(self) -> None:
        self.window.show()


def resolve_startup_path(
    argument: str | None,
) -> tuple[Path | None, Path | None, str | None]:
    if argument is None:
        return None, None, None
    candidate = Path(argument).expanduser()
    try:
        candidate = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return None, None, f"Der angegebene Pfad existiert nicht:\n{candidate}"
    if candidate.is_dir():
        return candidate, None, None
    if not candidate.is_file():
        return None, None, f"Der angegebene Pfad ist keine normale Datei:\n{candidate}"
    if candidate.suffix.lower() not in SUPPORTED_FILE_EXTENSIONS:
        return (
            None,
            None,
            "Die angegebene Datei hat kein unterstütztes Bild- oder PDF-Format:\n"
            f"{candidate}",
        )
    return candidate.parent, candidate, None


@dataclass
class DropResolution:
    """The safe, ordered result of accepting local drag-and-drop paths."""

    directory: Path | None
    selected_paths: list[Path]
    primary_path: Path | None
    ignored_paths: list[Path]
    error_message: str | None


def resolve_dropped_paths(paths: list[Path]) -> DropResolution:
    """Accept supported images from the first valid image directory only."""
    if not paths:
        return DropResolution(
            None, [], None, [], "Es wurden keine Dateien oder Ordner abgelegt."
        )

    resolved_entries: list[tuple[Path, Path | None, str | None]] = []
    directories: list[Path] = []
    images_present = False
    for path in paths:
        directory, image, error = resolve_startup_path(str(path))
        resolved_entries.append((path, image, error))
        if error is None and image is None and directory is not None:
            directories.append(directory)
        elif error is None and image is not None:
            images_present = True

    if directories:
        if len(paths) != 1 or images_present:
            return DropResolution(
                None,
                [],
                None,
                [],
                "Bitte legen Sie entweder einen einzelnen Ordner oder Bilddateien ab.",
            )
        return DropResolution(directories[0], [], None, [], None)

    selected_paths: list[Path] = []
    ignored_paths: list[Path] = []
    seen_paths: set[Path] = set()
    primary_directory: Path | None = None
    first_error: str | None = None
    for original_path, image, error in resolved_entries:
        if error is not None or image is None:
            ignored_paths.append(original_path)
            if first_error is None:
                first_error = error
            continue
        resolved_image = image.resolve(strict=False)
        if primary_directory is None:
            primary_directory = resolved_image.parent
        if resolved_image.parent != primary_directory or resolved_image in seen_paths:
            ignored_paths.append(original_path)
            continue
        seen_paths.add(resolved_image)
        selected_paths.append(resolved_image)

    if not selected_paths:
        return DropResolution(None, [], None, ignored_paths, first_error)
    return DropResolution(
        primary_directory,
        selected_paths,
        selected_paths[0],
        ignored_paths,
        None,
    )


def exportable_image_paths(paths: list[Path]) -> list[Path]:
    """Return existing, supported image files suitable for a Copy drag."""
    exportable: list[Path] = []
    seen_paths: set[Path] = set()
    for path in paths:
        if path.suffix.lower() not in SUPPORTED_FILE_EXTENSIONS or not path.is_file():
            continue
        try:
            resolved_path = path.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if resolved_path not in seen_paths:
            seen_paths.add(resolved_path)
            exportable.append(resolved_path)
    return exportable


def drag_paths_for_selection(
    current_selected_paths: list[Path],
    pressed_path: Path | None,
    snapshot_paths: list[Path],
) -> list[Path]:
    """Keep a pre-click multi-selection intact when its item starts a drag."""
    if pressed_path is not None:
        pressed_resolved = pressed_path.resolve(strict=False)
        snapshot_resolved = {
            path.resolve(strict=False) for path in snapshot_paths
        }
        if len(snapshot_paths) > 1 and pressed_resolved in snapshot_resolved:
            return exportable_image_paths(snapshot_paths)
        return exportable_image_paths([pressed_path])
    return exportable_image_paths(current_selected_paths)


def show_startup_error(viewer: ImageViewer, message: str) -> None:
    dialog = QMessageBox(viewer.window)
    dialog.setWindowTitle(f"{APP_NAME} – Startpfad")
    dialog.setIcon(QMessageBox.Icon.Warning)
    dialog.setText("Der übergebene Pfad konnte nicht geöffnet werden.")
    dialog.setInformativeText(message)
    dialog.setStandardButtons(QMessageBox.StandardButton.Close)
    dialog.button(QMessageBox.StandardButton.Close).setText("Schließen")
    viewer._style_message_box(dialog)
    dialog.exec()


def create_command_line_parser() -> QCommandLineParser:
    parser = QCommandLineParser()
    parser.setApplicationDescription(APP_DESCRIPTION)
    parser.addHelpOption()
    parser.addVersionOption()
    parser.addOption(
        QCommandLineOption(
            ["fullscreen"],
            "Die übergebene Datei nach dem Laden im Vollbild öffnen.",
        )
    )
    parser.addPositionalArgument(
        "pfad",
        "Optionaler Ordner oder eine zu öffnende Bilddatei.",
        "[pfad]",
    )
    return parser


def activate_startup_fullscreen(viewer: ImageViewer) -> bool:
    """Use the regular F11 toggle once a startup image has finished loading."""
    if viewer.original_image.isNull():
        return False
    if not viewer._fullscreen_mode:
        viewer._toggle_fullscreen()
    return True


def schedule_startup_fullscreen(viewer: ImageViewer, attempts: int = 100) -> None:
    """Wait for asynchronous thumbnail/image loading before entering fullscreen."""
    def activate_when_ready(remaining_attempts: int) -> None:
        if activate_startup_fullscreen(viewer) or remaining_attempts <= 0:
            return
        QTimer.singleShot(
            25,
            lambda: activate_when_ready(remaining_attempts - 1),
        )

    QTimer.singleShot(0, lambda: activate_when_ready(attempts))


class BildBlickApplication(QApplication):
    """Receives macOS Finder 'open document' events for an already running app."""

    file_open_requested = Signal(str)

    def __init__(self, arguments: list[str]) -> None:
        super().__init__(arguments)
        self.pending_file_opens: list[str] = []

    def event(self, event: QEvent) -> bool:
        if isinstance(event, QFileOpenEvent):
            path = event.file() or event.url().toLocalFile()
            if path:
                self.pending_file_opens.append(path)
                self.file_open_requested.emit(path)
                return True
        return super().event(event)


def main() -> int:
    app = BildBlickApplication(sys.argv)
    install_selection_accent_style(app)
    app.setWindowIcon(QIcon(str(resource_path("assets/bildblick.png"))))
    app.setOrganizationName(SETTINGS_ORGANIZATION)
    app.setApplicationName(SETTINGS_APPLICATION)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    parser = create_command_line_parser()
    parser.process(app)
    arguments = parser.positionalArguments()
    start_fullscreen = parser.isSet("fullscreen")
    startup_error = None
    startup_directory = None
    startup_image = None
    if len(arguments) > 1:
        startup_error = "Bitte nur eine Bilddatei oder einen Ordner angeben."
    else:
        startup_directory, startup_image, startup_error = resolve_startup_path(
            arguments[0] if arguments else None
        )

    viewer = ImageViewer(startup_directory, startup_image)

    def bring_window_to_front() -> None:
        if viewer.window.isMinimized():
            viewer.window.showNormal()
        viewer.window.show()
        viewer.window.raise_()
        viewer.window.activateWindow()

    def open_requested_path(path: str, fullscreen: bool = False) -> None:
        directory, image, error = resolve_startup_path(path)
        if error is not None:
            show_startup_error(viewer, error)
        elif directory is not None:
            viewer._show_directory(
                directory,
                [image] if image is not None else None,
            )
            if should_auto_enter_pdf_preview(image):
                viewer._enter_pdf_preview()
            else:
                viewer._leave_pdf_preview()
            if fullscreen and image is not None:
                schedule_startup_fullscreen(viewer)
        bring_window_to_front()

    app.file_open_requested.connect(open_requested_path)
    viewer.show()
    if start_fullscreen and startup_image is not None and startup_error is None:
        schedule_startup_fullscreen(viewer)
    for path in app.pending_file_opens:
        QTimer.singleShot(0, lambda path=path: open_requested_path(path))
    if startup_error is not None:
        QTimer.singleShot(
            0, lambda message=startup_error: show_startup_error(viewer, message)
        )
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
