import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from functools import cmp_to_key
from pathlib import Path

from PIL import Image as PillowImage
from send2trash import send2trash
from PySide6.QtCore import (
    QDir,
    QEvent,
    QFile,
    QIODevice,
    QItemSelectionModel,
    QMimeData,
    QObject,
    QRunnable,
    QSettings,
    QSize,
    QStandardPaths,
    QCommandLineParser,
    QCollator,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QBrush,
    QColor,
    QCursor,
    QIcon,
    QImage,
    QImageReader,
    QKeySequence,
    QPixmap,
    QShortcut,
    QTransform,
)
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFileSystemModel,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QSplitter,
    QToolButton,
    QToolTip,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from duplicate_finder import DuplicateFinderDialog


APP_NAME = "BildBlick"
APP_VERSION = "1.4.0"
APP_DESCRIPTION = "Ein schneller und komfortabler Bildbetrachter für Linux"

ROOT_DIRECTORY = Path("/")
HOME_DIRECTORY = Path.home()
_pictures_location = QStandardPaths.writableLocation(
    QStandardPaths.StandardLocation.PicturesLocation
)
START_DIRECTORY = Path(_pictures_location) if _pictures_location else HOME_DIRECTORY
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
THUMBNAIL_SIZE = QSize(160, 120)
THUMBNAIL_GRID_SIZE = QSize(190, 175)
THUMBNAIL_SPACING = 8
THUMBNAIL_MINIMUM = 80
THUMBNAIL_MAXIMUM = 256
THUMBNAIL_STEP = 16
THUMBNAIL_DEFAULT = 160
FOLDER_HISTORY_LIMIT = 50
TOOLTIP_METADATA_VERSION = 2
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
COLOR_SCHEME_KEY = "colorScheme"
THUMBNAIL_SIZE_KEY = "thumbnailSize"
SORT_CRITERION_KEY = "sortCriterion"
SORT_ASCENDING_KEY = "sortAscending"
SLIDESHOW_INTERVALS = (3, 5, 10, 15)
SORT_CRITERIA = ("name", "recording_date", "modified", "size")
ZOOM_STEP = 1.15
MIN_ZOOM = 0.10
MAX_ZOOM = 8.0
FULLSCREEN_TOOLTIP_DURATION = 3000
ZOOM_INDICATOR_DURATION = 1500
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


def color_scheme_stylesheet(colors: dict[str, str] | None) -> str:
    if colors is None:
        return ""
    return f"""
QMainWindow, QWidget#centralwidget {{
    background-color: {colors['window']}; color: {colors['text']};
}}
QWidget#directoryPanel, QWidget#previewPanel {{
    background-color: {colors['panel']}; color: {colors['text']};
}}
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


def normalized_thumbnail_pixels(value: int) -> int:
    bounded = min(THUMBNAIL_MAXIMUM, max(THUMBNAIL_MINIMUM, value))
    steps = round((bounded - THUMBNAIL_MINIMUM) / THUMBNAIL_STEP)
    return THUMBNAIL_MINIMUM + steps * THUMBNAIL_STEP


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


def build_image_tooltip(path: Path) -> str:
    lines = [path.name]
    file_info = None
    dimensions = None
    recording_date = None
    iso_value = None

    try:
        file_info = path.stat()
    except OSError:
        pass

    try:
        with PillowImage.open(path) as image:
            dimensions = image.size
            exif = image.getexif()
            for tag in (36867, 36868, 306):
                recording_date = format_date(exif.get(tag))
                if recording_date is not None:
                    break
            iso_value = extract_iso_value(exif)
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
    return "\n".join(lines)


class ThumbnailSignals(QObject):
    ready = Signal(int, int, QImage, str, object)


class ThumbnailTask(QRunnable):
    def __init__(
        self,
        path: Path,
        index: int,
        generation: int,
        metadata_key: tuple[str, int, int, int],
        cached_tooltip: str | None,
        thumbnail_size: QSize = THUMBNAIL_SIZE,
    ) -> None:
        super().__init__()
        self.path = path
        self.index = index
        self.generation = generation
        self.metadata_key = metadata_key
        self.cached_tooltip = cached_tooltip
        self.thumbnail_size = QSize(thumbnail_size)
        self.signals = ThumbnailSignals()

    def run(self) -> None:
        image = QImage()
        tooltip = self.path.name
        try:
            tooltip = self.cached_tooltip or build_image_tooltip(self.path)
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
            )
        except RuntimeError:
            pass

    def _load_or_create_thumbnail(self) -> QImage:
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


class ImageViewer(QObject):
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
        self._thumbnail_size = thumbnail_size_for_pixels(self._thumbnail_pixels)
        self._thumbnail_grid_size = thumbnail_grid_size_for_pixels(
            self._thumbnail_pixels
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
        self.status_bar.showMessage("Kein Bild ausgewählt")
        self.directory_tree = self._widget(QTreeView, "directoryTreeView")
        self.thumbnail_list = self._widget(QListWidget, "thumbnailList")
        self.image_scroll_area = self._widget(QScrollArea, "imageScrollArea")
        self.image_label = self._widget(QLabel, "imageLabel")
        self.previous_button = self._widget(QPushButton, "previousButton")
        self.next_button = self._widget(QPushButton, "nextButton")
        self.previous_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.next_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.file_name_label = self._widget(QLabel, "fileNameLabel")
        navigation_button_text_width = max(
            self.previous_button.fontMetrics().horizontalAdvance(
                self.previous_button.text()
            ),
            self.next_button.fontMetrics().horizontalAdvance(
                self.next_button.text()
            ),
        )
        navigation_button_width = max(180, navigation_button_text_width + 40)
        self.previous_button.setFixedWidth(navigation_button_width)
        self.next_button.setFixedWidth(navigation_button_width)
        self._file_name_text = ""
        self.splitter = self._widget(QSplitter, "mainSplitter")
        self.right_splitter = self._widget(QSplitter, "rightSplitter")
        self.directory_panel = self.directory_tree.parentWidget()
        self.preview_panel = self.image_scroll_area.parentWidget()
        self.current_directory: Path | None = None
        self.current_image: Path | None = None
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
        self._zoom_mode = "fit"
        self._zoom_factor = 1.0
        self._mouse_press_position = None
        self._pan_last_position = None
        self._dragging_image = False
        self._slideshow_running = False
        self._slideshow_entered_fullscreen = False
        self._image_render_pending = False
        self._fullscreen_mode = False
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
        self._file_sort_metadata: dict[str, tuple[int, int]] = {}
        self._recording_date_cache: dict[str, datetime | None] = {}
        self._resolved_sort_path_cache: dict[str, str] = {}
        self._capture_sort_waiting = False
        self.thread_pool = QThreadPool(self)
        self.thread_pool.setMaxThreadCount(3)
        self.slideshow_timer = QTimer(self)
        self.slideshow_timer.timeout.connect(self._advance_slideshow)
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
        self.image_scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_scroll_area.setWidgetResizable(False)
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

        self.directory_model = QFileSystemModel(self.window)
        self.directory_model.setFilter(
            QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives
        )
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

    def _start_directory(self) -> Path:
        saved_value = self.settings.value(LAST_DIRECTORY_KEY, "", type=str)
        if saved_value:
            saved_directory = Path(saved_value).expanduser()
            if saved_directory.is_dir():
                return saved_directory
        return START_DIRECTORY

    def _create_application_menus(self) -> None:
        self.file_menu = self.window.menuBar().addMenu("Datei")
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
        self.first_image_action.triggered.connect(lambda: self._select_image(0))
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
            lambda: self._select_image(self.thumbnail_list.count() - 1)
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
        self._set_rotation_action_states(
            self.current_image if image_loaded else None
        )
        has_selection = bool(self.thumbnail_list.selectedItems())
        self.trash_image_action.setEnabled(has_selection)
        self.copy_image_action.setEnabled(has_selection)
        self.cut_image_action.setEnabled(has_selection)
        self.compare_images_action.setEnabled(True)
        self.select_all_action.setEnabled(self.thumbnail_list.count() > 0)

    def _set_file_manager_action_state(self, image_path: Path | None) -> None:
        self.show_in_file_manager_action.setEnabled(
            image_path is not None and image_path.is_file()
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
        dialog.setStyleSheet(
            message_box_stylesheet(COLOR_SCHEMES[self._color_scheme])
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

    def _apply_thumbnail_size(self, pixels: int) -> None:
        pixels = normalized_thumbnail_pixels(pixels)
        if pixels == self._thumbnail_pixels:
            self._set_thumbnail_size_actions_enabled(True)
            return
        self._thumbnail_pixels = pixels
        self._thumbnail_size = thumbnail_size_for_pixels(pixels)
        self._thumbnail_grid_size = thumbnail_grid_size_for_pixels(pixels)
        self.settings.setValue(THUMBNAIL_SIZE_KEY, pixels)
        self.settings.sync()

        self._set_thumbnail_size_actions_enabled(False)
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
            item.setIcon(QIcon())
            item.setSizeHint(self._thumbnail_grid_size)
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
        candidates = (
            ("nemo", [str(parent_directory)]),
            ("xdg-open", [str(parent_directory)]),
            ("gio", ["open", str(parent_directory)]),
        )
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
                self.slideshow_timer.start(self._slideshow_interval * 1000)
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
            self.slideshow_timer.start(self._slideshow_interval * 1000)

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

        self.slideshow_action = QAction("Diashow starten", self.window)
        self.slideshow_action.setShortcut(QKeySequence("F5"))
        self.slideshow_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.slideshow_action.triggered.connect(self._toggle_slideshow)
        self.slideshow_menu.addAction(self.slideshow_action)

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
            "Vollbild bei Diashow", self.window
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

    def _set_slideshow_interval(self, action: QAction) -> None:
        self._slideshow_interval = int(action.data())
        self.settings.setValue(SLIDESHOW_INTERVAL_KEY, self._slideshow_interval)
        self.settings.sync()
        if self._slideshow_running:
            self.slideshow_timer.start(self._slideshow_interval * 1000)

    def _set_slideshow_repeat(self, enabled: bool) -> None:
        self._slideshow_repeat = enabled
        self.settings.setValue(SLIDESHOW_REPEAT_KEY, enabled)
        self.settings.sync()

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
        if self.thumbnail_list.currentRow() < 0:
            self._select_relative_image(1)
        self._slideshow_running = True
        self._slideshow_entered_fullscreen = False
        if self._slideshow_fullscreen and not self._fullscreen_mode:
            self._enter_fullscreen()
            self._slideshow_entered_fullscreen = self._fullscreen_mode
        self.slideshow_timer.start(self._slideshow_interval * 1000)
        self._update_slideshow_actions()

    def _stop_slideshow(self) -> None:
        if not self._slideshow_running:
            return
        self._slideshow_running = False
        self.slideshow_timer.stop()
        if self._slideshow_entered_fullscreen:
            self._leave_fullscreen()
        self._slideshow_entered_fullscreen = False
        self._update_slideshow_actions()

    def _advance_slideshow(self) -> None:
        last_row = self.thumbnail_list.count() - 1
        current_row = self.thumbnail_list.currentRow()
        if last_row < 0:
            self._stop_slideshow()
        elif current_row < last_row:
            self._select_relative_image(1)
        elif self._slideshow_repeat:
            first_item = self.thumbnail_list.item(0)
            self.thumbnail_list.setCurrentItem(first_item)
            self.thumbnail_list.scrollToItem(first_item)
        else:
            self._stop_slideshow()

    def _update_slideshow_actions(self) -> None:
        action_text = (
            "Diashow stoppen" if self._slideshow_running else "Diashow starten"
        )
        self.slideshow_action.setText(action_text)

    def _handle_escape(self) -> None:
        if self._slideshow_running:
            self._stop_slideshow()
        if self._fullscreen_mode:
            self._leave_fullscreen()

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
            select_paths[0].resolve(strict=False) if select_paths else None
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

    def _scan_directory_batch(self, generation: int) -> None:
        if generation != self._load_generation or self._directory_iterator is None:
            return

        try:
            for _ in range(DIRECTORY_ENTRIES_PER_BATCH):
                entry = next(self._directory_iterator)
                path = Path(entry.path)
                try:
                    if (
                        not entry.name.startswith("._")
                        and entry.is_file()
                        and path.suffix.lower() in IMAGE_EXTENSIONS
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
    ) -> None:
        if generation != self._load_generation:
            return
        self._active_jobs = max(0, self._active_jobs - 1)
        self._completed_jobs += 1
        try:
            self._metadata_cache[metadata_key] = tooltip
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
            self.slideshow_timer.start(self._slideshow_interval * 1000)

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
        self._set_file_manager_action_state(image_path)
        self._add_rotation_context_submenu(context_menu, image_path)
        try:
            context_menu.exec(global_position)
        finally:
            self._rotation_context_path = None
            self._file_manager_context_path = None
            self._update_view_actions()

    def _show_image_context_menu(self, global_position) -> None:
        context_menu = QMenu(self.image_scroll_area.viewport())
        image_path = (
            self.current_image if not self.original_image.isNull() else None
        )
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
            self._update_view_actions()

    def _select_all_images(self) -> None:
        self.thumbnail_list.selectAll()
        if self.thumbnail_list.currentRow() < 0 and self.thumbnail_list.count() > 0:
            self.thumbnail_list.setCurrentItem(
                self.thumbnail_list.item(0),
                QItemSelectionModel.SelectionFlag.NoUpdate,
            )

    def _select_relative_image(self, offset: int) -> None:
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
        self.select_all_action.setEnabled(last_row >= 0)
        self._update_status_bar()

    def _create_directory_navigation_buttons(self) -> None:
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
            directory_layout.insertLayout(1, navigation_row)
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

    def _update_status_bar(self) -> None:
        current_row = self.thumbnail_list.currentRow()
        if (
            self.current_image is None
            or self.original_image.isNull()
            or current_row < 0
        ):
            self.status_bar.showMessage("Kein Bild ausgewählt")
            return

        parts = [
            f"Bild {current_row + 1} von {self.thumbnail_list.count()}",
            f"{self.original_image.width()} × {self.original_image.height()} Pixel",
        ]
        if self._current_file_size is not None:
            parts.append(format_file_size(self._current_file_size))
        current_item = self.thumbnail_list.currentItem()
        if current_item is not None:
            iso_value = next(
                (
                    line.removeprefix("ISO: ")
                    for line in current_item.toolTip().splitlines()
                    if line.startswith("ISO: ")
                ),
                None,
            )
            if iso_value is not None:
                parts.append(f"ISO {iso_value}")
        parts.append(f"Zoom {round(self._zoom_factor * 100)} %")
        self.status_bar.showMessage(" | ".join(parts))

    def _load_current_image(self) -> None:
        self._hide_zoom_indicator()
        if self.current_image is None:
            self._exif_oriented_image = QImage()
            self._current_file_size = None
            self._update_status_bar()
            return
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
            Qt.AspectRatioMode.IgnoreAspectRatio,
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
        self.thumbnail_list.hide()
        self.previous_button.hide()
        self.next_button.hide()
        self.file_name_label.hide()
        self.window.menuBar().hide()
        self.splitter.handle(1).hide()
        self.right_splitter.handle(1).hide()
        self.window.setStyleSheet("background-color: black;")
        self.image_label.setStyleSheet("background-color: black;")
        self.window.showFullScreen()
        self._schedule_image_render()
        self._show_fullscreen_tooltip(QCursor.pos())

    def _leave_fullscreen(self) -> None:
        if not self._fullscreen_mode:
            return

        self._fullscreen_mode = False
        self.fullscreen_tooltip_timer.stop()
        self._hide_fullscreen_tooltip()
        self.fullscreen_action.setChecked(False)
        self.window.setStyleSheet(self._normal_window_style)
        self.image_label.setStyleSheet(self._normal_image_style)
        central_layout = self.window.centralWidget().layout()
        if central_layout is not None and self._normal_central_margins is not None:
            central_layout.setContentsMargins(*self._normal_central_margins)

        self.directory_panel.show()
        self.thumbnail_list.show()
        self.previous_button.show()
        self.next_button.show()
        self.file_name_label.show()
        self.window.menuBar().show()
        self.splitter.handle(1).show()
        self.right_splitter.handle(1).show()

        self.window.showNormal()
        if self._normal_geometry is not None:
            self.window.setGeometry(self._normal_geometry)
        if self._normal_was_maximized:
            self.window.showMaximized()
        self.splitter.setSizes(self._normal_main_splitter_sizes)
        self.right_splitter.setSizes(self._normal_right_splitter_sizes)
        self._schedule_image_render()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.file_name_label and event.type() == QEvent.Type.Resize:
            self._set_file_name_text(self._file_name_text)
        image_widgets = (self.image_label, self.image_scroll_area.viewport())
        if self._fullscreen_mode and watched in image_widgets:
            if event.type() == QEvent.Type.ToolTip:
                return True
            if event.type() in (QEvent.Type.Enter, QEvent.Type.MouseMove):
                global_position = (
                    event.globalPosition().toPoint()
                    if event.type() == QEvent.Type.MouseMove
                    else QCursor.pos()
                )
                self._show_fullscreen_tooltip(global_position)
        if watched in image_widgets and event.type() == QEvent.Type.ContextMenu:
            self._show_image_context_menu(event.globalPos())
            return True
        if (
            watched is self.image_scroll_area.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            self._position_zoom_indicator()
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
    if candidate.suffix.lower() not in IMAGE_EXTENSIONS:
        return (
            None,
            None,
            "Die angegebene Datei hat kein unterstütztes Bildformat:\n"
            f"{candidate}",
        )
    return candidate.parent, candidate, None


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


def main() -> int:
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(resource_path("assets/bildblick.png"))))
    app.setOrganizationName(SETTINGS_ORGANIZATION)
    app.setApplicationName(SETTINGS_APPLICATION)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    parser = QCommandLineParser()
    parser.setApplicationDescription(APP_DESCRIPTION)
    parser.addHelpOption()
    parser.addVersionOption()
    parser.addPositionalArgument(
        "pfad",
        "Optionaler Ordner oder eine zu öffnende Bilddatei.",
        "[pfad]",
    )
    parser.process(app)
    arguments = parser.positionalArguments()
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
    viewer.show()
    if startup_error is not None:
        QTimer.singleShot(
            0, lambda message=startup_error: show_startup_error(viewer, message)
        )
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
