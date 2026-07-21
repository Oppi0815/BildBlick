import hashlib
import os
import shutil
import sys
import threading
from datetime import datetime
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
)
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
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
    QSizePolicy,
    QSplitter,
    QToolTip,
    QTreeView,
    QVBoxLayout,
)

from duplicate_finder import DuplicateFinderDialog


APP_NAME = "BildBlick"
APP_VERSION = "1.1.0"
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
SLIDESHOW_INTERVALS = (3, 5, 10, 15)
ZOOM_STEP = 1.15
MIN_ZOOM = 0.10
MAX_ZOOM = 8.0
FULLSCREEN_TOOLTIP_DURATION = 3000
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
QSplitter::handle {{ background-color: {colors['border']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QScrollBar {{ background-color: {colors['panel']}; }}
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


def thumbnail_cache_name(path: Path) -> str:
    file_info = path.stat()
    key_data = "\0".join(
        (
            str(path.resolve(strict=False)),
            str(file_info.st_size),
            str(file_info.st_mtime_ns),
            f"{THUMBNAIL_SIZE.width()}x{THUMBNAIL_SIZE.height()}",
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
    ) -> None:
        super().__init__()
        self.path = path
        self.index = index
        self.generation = generation
        self.metadata_key = metadata_key
        self.cached_tooltip = cached_tooltip
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
        cache_name = thumbnail_cache_name(self.path)
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
        reader.setScaledSize(fitted_size(reader.size(), THUMBNAIL_SIZE))
        image = reader.read()
        if image.isNull():
            return image
        image = image.scaled(
            THUMBNAIL_SIZE,
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


class ImageViewer(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)
        self._migrate_legacy_settings()
        self.start_directory = self._start_directory()
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
        self.window = self._load_ui()
        self.window.setWindowTitle(APP_NAME)
        self.directory_tree = self._widget(QTreeView, "directoryTreeView")
        self.thumbnail_list = self._widget(QListWidget, "thumbnailList")
        self.image_scroll_area = self._widget(QScrollArea, "imageScrollArea")
        self.image_label = self._widget(QLabel, "imageLabel")
        self.previous_button = self._widget(QPushButton, "previousButton")
        self.next_button = self._widget(QPushButton, "nextButton")
        self.previous_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.next_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.file_name_label = self._widget(QLabel, "fileNameLabel")
        self.splitter = self._widget(QSplitter, "mainSplitter")
        self.right_splitter = self._widget(QSplitter, "rightSplitter")
        self.directory_panel = self.directory_tree.parentWidget()
        self.preview_panel = self.image_scroll_area.parentWidget()
        self.current_directory: Path | None = None
        self.current_image: Path | None = None
        self._pending_selection_paths: set[Path] = set()
        self._pending_primary_path: Path | None = None
        self._clipboard_operation: str | None = None
        self._clipboard_source_paths: list[Path] = []
        self._handling_clipboard_change = False
        self.clipboard = QApplication.clipboard()
        self.original_image = QImage()
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

        self.thumbnail_list.setViewMode(QListView.ViewMode.IconMode)
        self.thumbnail_list.setMovement(QListView.Movement.Static)
        self.thumbnail_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.thumbnail_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.thumbnail_list.setWrapping(True)
        self.thumbnail_list.setWordWrap(True)
        self.thumbnail_list.setIconSize(THUMBNAIL_SIZE)
        self.thumbnail_list.setGridSize(THUMBNAIL_GRID_SIZE)
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
        self.window.installEventFilter(self)
        self.escape_shortcut = QShortcut(QKeySequence("Escape"), self.window)
        self.escape_shortcut.activated.connect(self._handle_escape)
        self._create_application_menus()
        self.clipboard.dataChanged.connect(self._clipboard_changed)
        self._clipboard_changed()
        self._update_navigation_buttons()

        self._expand_initial_path(self.start_directory)
        if self.start_directory.is_dir():
            self._show_directory(self.start_directory)

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
            self.first_image_action,
            self.previous_image_action,
            self.next_image_action,
            self.last_image_action,
        ):
            self.window.addAction(action)

        self._create_slideshow_menu()

        self.tools_menu = self.window.menuBar().addMenu("Werkzeuge")
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
        has_selection = bool(self.thumbnail_list.selectedItems())
        self.trash_image_action.setEnabled(has_selection)
        self.copy_image_action.setEnabled(has_selection)
        self.cut_image_action.setEnabled(has_selection)
        self.select_all_action.setEnabled(self.thumbnail_list.count() > 0)

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
                cache_name = thumbnail_cache_name(image_path)
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
            self._zoom_mode = "fit"
            self._zoom_factor = 1.0
            self.image_label.clear()
            self.image_label.resize(self.image_scroll_area.viewport().size())
            self.image_label.setText("Bild anklicken, um es anzuzeigen")
            self.file_name_label.setText("0 Bilder")
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
            "• Strg + A: Alle Bilder auswählen<br>"
            "• Strg + C: Ausgewählte Bilder kopieren<br>"
            "• Strg + X: Ausgewählte Bilder ausschneiden<br>"
            "• Strg + V: Bilder in den aktuellen Ordner einfügen<br>"
            "• Entf: Ausgewählte Bilder in den Papierkorb verschieben<br>"
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

    def _show_directory(
        self,
        directory: Path,
        select_paths: list[Path] | None = None,
    ) -> None:
        if self._slideshow_running:
            self._stop_slideshow()
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
        self.current_directory = directory
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
        self._update_view_actions()
        self._zoom_mode = "fit"
        self._zoom_factor = 1.0
        self.image_label.clear()
        self.image_label.resize(self.image_scroll_area.viewport().size())
        self.image_label.setText("Bild anklicken, um es anzuzeigen")
        self.file_name_label.setText("Suche nach Bildern …")
        self._clipboard_changed()

        try:
            self._directory_iterator = os.scandir(directory)
        except OSError:
            self.file_name_label.setText("Ordner konnte nicht gelesen werden")
            return

        self.settings.setValue(LAST_DIRECTORY_KEY, str(directory.resolve(strict=False)))
        self.settings.sync()
        QTimer.singleShot(0, lambda: self._scan_directory_batch(generation))

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
                except OSError:
                    continue
        except StopIteration:
            self._directory_iterator.close()
            self._directory_iterator = None
            self._pending_images.sort(key=lambda path: path.name.casefold())
            self._update_loading_text()
            QTimer.singleShot(0, lambda: self._prepare_thumbnail_items(generation))
            return
        except OSError:
            self._directory_iterator.close()
            self._directory_iterator = None
            self.file_name_label.setText("Ordner konnte nicht vollständig gelesen werden")
            return

        self.file_name_label.setText(
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
                item.setSizeHint(THUMBNAIL_GRID_SIZE)
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
                    item.setSizeHint(THUMBNAIL_GRID_SIZE)
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
        self._update_loading_text()
        if self._completed_jobs >= len(self._pending_images):
            self._finish_thumbnail_loading(generation)
        else:
            self._start_more_thumbnail_jobs(generation)

    def _update_loading_text(self) -> None:
        self.file_name_label.setText(
            f"Lade Vorschaubilder: {self._completed_jobs} von {len(self._pending_images)}"
        )

    def _finish_thumbnail_loading(self, generation: int) -> None:
        if generation != self._load_generation:
            return
        if self.current_image is not None:
            self.file_name_label.setText(self.current_image.name)
            return
        count = self.thumbnail_list.count()
        self.file_name_label.setText(f"{count} Bild" if count == 1 else f"{count} Bilder")

    def _thumbnail_selected(
        self,
        item: QListWidgetItem | None,
        _previous_item: QListWidgetItem | None = None,
    ) -> None:
        if item is None:
            self._update_navigation_buttons()
            return
        self.current_image = Path(item.data(Qt.ItemDataRole.UserRole))
        self.file_name_label.setText(self.current_image.name)
        self._load_current_image()
        self._update_navigation_buttons()
        if self._slideshow_running:
            self.slideshow_timer.start(self._slideshow_interval * 1000)

    def _selection_changed(self) -> None:
        self._update_view_actions()

    def _show_thumbnail_context_menu(self, position) -> None:
        clicked_item = self.thumbnail_list.itemAt(position)
        context_menu = QMenu(self.thumbnail_list)

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
            context_menu.addAction(self.copy_image_action)
            context_menu.addAction(self.cut_image_action)
            context_menu.addAction(self.paste_image_action)
            context_menu.addSeparator()
            context_menu.addAction(self.select_all_action)
            context_menu.addSeparator()
            context_menu.addAction(self.trash_image_action)
        else:
            context_menu.addAction(self.paste_image_action)
            context_menu.addAction(self.select_all_action)

        context_menu.exec(
            self.thumbnail_list.viewport().mapToGlobal(position)
        )

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

    def _load_current_image(self) -> None:
        if self.current_image is None:
            return
        reader = QImageReader(str(self.current_image))
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            self.original_image = QImage()
            self._zoom_mode = "fit"
            self._zoom_factor = 1.0
            self.image_label.clear()
            self.image_label.resize(self.image_scroll_area.viewport().size())
            self.image_label.setText("Bild konnte nicht geladen werden")
            self._update_view_actions()
            return
        self.original_image = image
        self._update_view_actions()
        self._zoom_mode = "fit"
        self._render_current_image()

    def _render_current_image(self) -> None:
        self._image_render_pending = False
        if self.original_image.isNull():
            return
        viewport_size = self.image_scroll_area.viewport().size()
        if viewport_size.width() <= 1 or viewport_size.height() <= 1:
            return
        if self._zoom_mode == "fit":
            self._zoom_factor = min(
                viewport_size.width() / self.original_image.width(),
                viewport_size.height() / self.original_image.height(),
            )
        scaled_size = QSize(
            max(1, round(self.original_image.width() * self._zoom_factor)),
            max(1, round(self.original_image.height() * self._zoom_factor)),
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

    def _fit_image_to_window(self) -> None:
        if self.original_image.isNull():
            return
        self._zoom_mode = "fit"
        self._render_current_image()

    def _show_image_at_actual_size(self) -> None:
        if self.original_image.isNull():
            return
        self._zoom_mode = "manual"
        self._zoom_factor = 1.0
        self._render_current_image()
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
        if (
            watched is self.image_scroll_area.viewport()
            and event.type() == QEvent.Type.Resize
        ):
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


def main() -> int:
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(resource_path("assets/bildblick.png"))))
    app.setOrganizationName(SETTINGS_ORGANIZATION)
    app.setApplicationName(SETTINGS_APPLICATION)
    app.setApplicationDisplayName(APP_NAME)
    viewer = ImageViewer()
    viewer.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
