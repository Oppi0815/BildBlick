import hashlib
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from time import perf_counter
from io import BytesIO
from datetime import datetime
from dataclasses import dataclass
from functools import cmp_to_key
from pathlib import Path
from typing import Callable, TypeVar

from PIL import ExifTags, Image as PillowImage, ImageOps, IptcImagePlugin
from send2trash import send2trash
from PySide6.QtCore import (
    QDir,
    QEvent,
    QEasingCurve,
    QFile,
    QFileSystemWatcher,
    QIODevice,
    QItemSelectionModel,
    QLineF,
    QModelIndex,
    QMimeData,
    QObject,
    QPropertyAnimation,
    QRunnable,
    QSettings,
    QSize,
    QPointF,
    QRect,
    QRectF,
    QStandardPaths,
    QStringListModel,
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
    QDesktopServices,
    QDrag,
    QFileOpenEvent,
    QIcon,
    QImage,
    QImageReader,
    QKeySequence,
    QPageLayout,
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
from PySide6.QtPdf import QPdfLinkModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFileSystemModel,
    QFormLayout,
    QGroupBox,
    QGraphicsOpacityEffect,
    QHBoxLayout,
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
    QProgressDialog,
    QProxyStyle,
    QFrame,
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
    QTextEdit,
    QTreeView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from duplicate_finder import DuplicateFinderDialog
from metadata_database import suggest_people, suggest_places, upsert_person, upsert_place
from image_index import (
    index_folder, indexed_folders, remove_indexed_folder, search_images,
    update_indexed_image,
)
from printing.multi_image_print import (
    MultiImagePrintSettings,
    current_print_date_text,
    multi_image_document_from_settings,
)
from printing.layout import ImageSourceInfo, PageSizeMm
from printing.planner import plan_multi_image_pages
from printing.printer_geometry import (
    configure_printer_page_layout,
    printer_geometry_mm,
    printer_target_rect_for_painter,
)
from printing.renderer import render_page_plan
from printing.wysiwyg_dialog import SingleImageWysiwygPrintDialog
from printing.multi_wysiwyg_dialog import MultiImageWysiwygPrintDialog
from pdf_support import (
    PDF_EXTENSIONS,
    pdf_display_target_size,
    pdf_page_render_size,
    pdf_render_size_matches,
    load_pdf,
    render_pdf_page,
    render_pdf_page_for_printer,
    render_pdf_page_with_fallback,
)
from i18n import LANGUAGES, LanguageManager, t


APP_NAME = "BildBlick"
APP_VERSION = "1.22.0"
APP_DESCRIPTION = "Ein schneller und komfortabler Bildbetrachter"
LOGGER = logging.getLogger(__name__)

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
VOLUMES_DIRECTORY = Path("/Volumes")
HOME_DIRECTORY = Path.home()


def network_mount_roots(
    platform: str | None = None,
    uid: int | None = None,
    username: str | None = None,
    *,
    is_dir: Callable[[Path], bool] | None = None,
) -> tuple[Path, ...]:
    """Return existing roots where desktop network mounts can appear.

    macOS publishes mounted shares below ``/Volumes``.  Mint's file manager
    exposes GVFS shares below the per-user FUSE directory; ``/media/$USER``
    and ``/mnt`` are also watched as conventional administrator-managed mount
    locations.  Missing roots are deliberately omitted so a temporary GVFS
    daemon shutdown cannot make the tree watcher fail.
    """
    platform = sys.platform if platform is None else platform
    is_dir = Path.is_dir if is_dir is None else is_dir
    if platform == "darwin":
        candidates = (VOLUMES_DIRECTORY,)
    elif platform.startswith("linux"):
        uid = os.getuid() if uid is None else uid
        username = os.environ.get("USER", "") if username is None else username
        candidates = (
            Path(f"/run/user/{uid}/gvfs"),
            Path("/media") / username,
            Path("/mnt"),
        )
    else:
        candidates = ()
    return tuple(path for path in candidates if is_dir(path))


def network_mount_paths(
    roots: tuple[Path, ...] | None = None,
    *,
    iterdir: Callable[[Path], object] | None = None,
    mountinfo_text: str | None = None,
) -> tuple[Path, ...]:
    """Return only actual network mounts below known mount roots.

    A QFileSystemWatcher also reports unrelated activity at e.g.
    ``/run/user/$UID``.  The child-directory snapshot is therefore the source
    of truth for deciding whether a tree rebuild is necessary.
    """
    roots = network_mount_roots() if roots is None else roots
    iterdir = Path.iterdir if iterdir is None else iterdir
    paths: list[Path] = []
    network_mounts: set[Path] = set()
    if sys.platform.startswith("linux"):
        if mountinfo_text is None:
            try:
                mountinfo_text = Path("/proc/self/mountinfo").read_text()
            except OSError:
                mountinfo_text = ""
        network_fstypes = {"cifs", "smb3", "nfs", "nfs4", "fuse.sshfs", "sshfs"}
        for line in mountinfo_text.splitlines():
            before, marker, after = line.partition(" - ")
            fields = before.split()
            filesystem = after.split()[0] if marker and after else ""
            if len(fields) >= 5 and filesystem in network_fstypes:
                network_mounts.add(Path(fields[4].replace("\\040", " ")))
    for root in roots:
        if sys.platform.startswith("linux") and root.name != "gvfs":
            continue
        try:
            children = iterdir(root)
        except OSError:
            continue
        try:
            # Do not stat every child here.  A GVFS entry can require a round
            # trip to a sleeping network host; its presence is sufficient for
            # mount-change detection and avoids blocking the GUI thread.
            paths.extend(child for child in children if not child.name.startswith("."))
        except OSError:
            continue
    paths.extend(network_mounts)
    return tuple(sorted(set(paths), key=lambda path: str(path)))


def network_mount_label(path: Path) -> str:
    """Provide a short, human-readable label while retaining the real path."""
    name = path.name
    host = re.search(r"(?:^|[:,])host=([^,]+)", name)
    if host:
        return host.group(1)
    server = re.search(r"(?:^|,)server=([^,]+)", name)
    if server:
        share = re.search(r"(?:^|,)share=([^,]+)", name)
        return f"{server.group(1)}/{share.group(1)}" if share else server.group(1)
    return name
_pictures_location = QStandardPaths.writableLocation(
    QStandardPaths.StandardLocation.PicturesLocation
)
START_DIRECTORY = Path(_pictures_location) if _pictures_location else HOME_DIRECTORY
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
JPEG_EXTENSIONS = {".jpg", ".jpeg"}
SUPPORTED_FILE_EXTENSIONS = IMAGE_EXTENSIONS | PDF_EXTENSIONS


def _manual_metadata_people(value: str) -> list[str]:
    """Normalize the comma-separated editor value for XMP list storage."""
    people: list[str] = []
    seen: set[str] = set()
    for part in value.split(","):
        person = part.strip()
        key = person.casefold()
        if person and key not in seen:
            people.append(person)
            seen.add(key)
    return people


def _manual_metadata_gps(value: str) -> tuple[float, float] | None:
    value = value.strip()
    if not value:
        return None
    try:
        latitude, longitude = (float(item.strip()) for item in value.split(","))
    except (TypeError, ValueError):
        raise ValueError(t("GPS muss als Breitengrad, Längengrad eingegeben werden.")) from None
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError(t("GPS-Koordinaten liegen außerhalb des gültigen Bereichs."))
    return latitude, longitude


class PersonCompleter(QCompleter):
    """Complete only the person currently being typed after the last comma."""
    def splitPath(self, path: str) -> list[str]:
        return [path.rsplit(",", 1)[-1].strip()]

    def pathFromIndex(self, index: QModelIndex) -> str:
        completion = super().pathFromIndex(index)
        widget = self.widget()
        current = widget.text() if isinstance(widget, QLineEdit) else ""
        prefix = current.rsplit(",", 1)
        return f"{prefix[0]}, {completion}" if len(prefix) == 2 else completion


def _exiftool_json(path: Path) -> dict[str, object]:
    result = subprocess.run(
        ["exiftool", "-j", "-n", "-G1", "-XMP-dc:Description", "-IPTC:Caption-Abstract",
         "-EXIF:ImageDescription", "-XMP-iptcExt:PersonInImage", "-XMP-photoshop:City",
         "-IPTC:City", "-GPS:GPSLatitude", "-GPS:GPSLongitude", str(path)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or t("Metadaten konnten nicht gelesen werden."))
    records = json.loads(result.stdout)
    return records[0] if records else {}


def read_manual_image_metadata(path: Path) -> dict[str, str]:
    """Read the standardized fields without decoding or rewriting JPEG pixels."""
    if path.suffix.lower() not in JPEG_EXTENSIONS:
        return {"comment": "", "people": "", "place": "", "gps": ""}
    tags = _exiftool_json(path)
    comment = next((str(tags[key]) for key in ("XMP-dc:Description", "IPTC:Caption-Abstract", "EXIF:ImageDescription") if tags.get(key)), "")
    raw_people = tags.get("XMP-iptcExt:PersonInImage", [])
    people = raw_people if isinstance(raw_people, list) else [raw_people]
    place = next((str(tags[key]) for key in ("XMP-photoshop:City", "IPTC:City") if tags.get(key)), "")
    latitude, longitude = tags.get("GPS:GPSLatitude"), tags.get("GPS:GPSLongitude")
    gps = "" if latitude is None or longitude is None else f"{float(latitude):.6f}, {float(longitude):.6f}"
    return {"comment": comment, "people": ", ".join(str(item) for item in people), "place": place, "gps": gps}


def write_manual_image_metadata(path: Path, metadata: dict[str, str]) -> None:
    """Update only requested metadata tags via ExifTool, preserving JPEG data."""
    if path.suffix.lower() not in JPEG_EXTENSIONS:
        raise ValueError(t("Bildinformationen können nur in JPG/JPEG gespeichert werden."))
    gps = _manual_metadata_gps(metadata.get("gps", ""))
    args = ["exiftool", "-overwrite_original"]
    def set_or_delete(tag: str, value: str) -> None:
        args.append(f"-{tag}={value.strip()}" if value.strip() else f"-{tag}=")
    comment = metadata.get("comment", "")
    set_or_delete("XMP-dc:Description", comment)
    set_or_delete("IPTC:Caption-Abstract", comment)
    place = metadata.get("place", "")
    set_or_delete("XMP-photoshop:City", place)
    set_or_delete("IPTC:City", place)
    args.append("-XMP-iptcExt:PersonInImage=")
    for person in _manual_metadata_people(metadata.get("people", "")):
        args.append(f"-XMP-iptcExt:PersonInImage+={person}")
    if gps is None:
        for tag in ("GPSLatitude", "GPSLatitudeRef", "GPSLongitude", "GPSLongitudeRef"):
            args.append(f"-{tag}=")
    else:
        latitude, longitude = gps
        args.extend((f"-GPSLatitude={abs(latitude)}", f"-GPSLatitudeRef={'S' if latitude < 0 else 'N'}", f"-GPSLongitude={abs(longitude)}", f"-GPSLongitudeRef={'W' if longitude < 0 else 'E'}"))
    result = subprocess.run([*args, str(path)], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or t("Metadaten konnten nicht gespeichert werden."))
THUMBNAIL_SIZE = QSize(160, 120)
THUMBNAIL_GRID_SIZE = QSize(190, 175)
THUMBNAIL_SPACING = 14
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
THUMBNAIL_POSITION_KEY = "view/thumbnail_position"
LAST_VISIBLE_THUMBNAIL_POSITION_KEY = "view/last_visible_thumbnail_position"
THUMBNAIL_POSITIONS = ("top", "left", "right", "hidden")
BOTTOM_CONTROL_BAR_HEIGHT = 46
BOTTOM_CONTROL_BAR_START_DELAY_MS = 3000
BOTTOM_CONTROL_BAR_HIDE_DELAY_MS = 1000
BOTTOM_CONTROL_BAR_ACTIVATION_ZONE_PX = 72
STATUS_READY = "ready"
STATUS_BUSY = "busy"
STATUS_ERROR = "error"
STATUS_STATES = (STATUS_READY, STATUS_BUSY, STATUS_ERROR)
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
MULTI_IMAGE_PRINT_TARGET_DPI = 300
SLIDESHOW_INTERVALS = (3, 5, 10, 15)
SORT_CRITERIA = ("name", "recording_date", "modified", "size")
ZOOM_STEP = 1.15
MIN_ZOOM = 0.10
MAX_ZOOM = 8.0
FULLSCREEN_TOOLTIP_DURATION = 3000
PDF_FULLSCREEN_NAVIGATION_HINT_DURATION = 8000
ZOOM_INDICATOR_DURATION = 1500
CHECK_ACCENT_COLOR = "#D32F2F"
CLIPBOARD_OPERATION_MIME_TYPE = "application/x-bildblick-file-operation"
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
        "slider_groove": "#737a82", "slider_active": "#1769aa",
        "slider_disabled_groove": "#c5c9ce", "slider_disabled_active": "#8fb9dd",
    },
    "Dunkel": {
        "window": "#20242a", "panel": "#292e35", "preview": "#252a30",
        "image": "#111315", "text": "#edf0f3", "muted": "#aeb5bd",
        "border": "#444b54", "button": "#343a42", "hover": "#424a54",
        "selection": "#3b8edb", "selection_text": "#ffffff",
        "tooltip": "#353b43", "tooltip_text": "#ffffff",
        "slider_groove": "#6d747d", "slider_active": "#66b5ff",
        "slider_disabled_groove": "#50565d", "slider_disabled_active": "#637f99",
    },
    "Anthrazit": {
        "window": "#1b1d20", "panel": "#272a2f", "preview": "#22252a",
        "image": "#090a0c", "text": "#f1f2f4", "muted": "#adb2b9",
        "border": "#3b4047", "button": "#30343a", "hover": "#3d424a",
        "selection": "#d88932", "selection_text": "#ffffff",
        "tooltip": "#30343a", "tooltip_text": "#ffffff",
        "slider_groove": "#656b72", "slider_active": "#eea34d",
        "slider_disabled_groove": "#4a4f55", "slider_disabled_active": "#856b50",
    },
    "Warm": {
        "window": "#e8e2d9", "panel": "#f3eee7", "preview": "#ddd5ca",
        "image": "#282522", "text": "#322e29", "muted": "#716960",
        "border": "#b9aea0", "button": "#f5f0e9", "hover": "#ded3c5",
        "selection": "#9a6136", "selection_text": "#ffffff",
        "tooltip": "#fff4d8", "tooltip_text": "#322e29",
        "slider_groove": "#81776c", "slider_active": "#9a6136",
        "slider_disabled_groove": "#c4b9ad", "slider_disabled_active": "#bf9d82",
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


class DirectoryTreeIndicatorDelegate(QStyledItemDelegate):
    """Draw cached folder-depth indicators in the tree's branch area."""

    _LINE_WIDTH = 1.15
    _SYMBOL_SIZE = 8.0

    def __init__(self, tree: QTreeView) -> None:
        super().__init__(tree)
        self._tree = tree
        self._contains_subdirectory_cache: dict[str, bool] = {}
        self._watched_directory_paths: set[str] = set()
        self._directory_watcher = QFileSystemWatcher(tree)
        self._directory_watcher.directoryChanged.connect(self.invalidate)
        tree.viewport().installEventFilter(self)
        tree.expanded.connect(lambda _index: tree.viewport().update())
        tree.collapsed.connect(lambda _index: tree.viewport().update())

    def indicator_rect(self, index: QModelIndex) -> QRect:
        item_rect = self._tree.visualRect(index)
        return QRect(
            item_rect.left() - self._tree.indentation(),
            item_rect.top(),
            self._tree.indentation(),
            item_rect.height(),
        )

    def invalidate(self, directory: str | Path | None = None) -> None:
        if directory is None:
            self._contains_subdirectory_cache.clear()
        else:
            directory_path = str(directory)
            self._contains_subdirectory_cache.pop(directory_path, None)
            if directory_path not in self._directory_watcher.directories():
                self._watched_directory_paths.discard(directory_path)
        self._tree.viewport().update()

    def _directory_path(self, index: QModelIndex) -> Path | None:
        model = self._tree.model()
        if not isinstance(model, QFileSystemModel) or not index.isValid():
            return None
        path = Path(model.filePath(index))
        return path if path.is_dir() else None

    def _contains_subdirectory(self, index: QModelIndex) -> bool:
        path = self._directory_path(index)
        if path is None:
            return False
        cache_key = str(path)
        cached = self._contains_subdirectory_cache.get(cache_key)
        if cached is not None:
            return cached
        if cache_key not in self._watched_directory_paths:
            if self._directory_watcher.addPath(cache_key):
                self._watched_directory_paths.add(cache_key)
        try:
            with os.scandir(path) as entries:
                contains_subdirectory = any(
                    entry.is_dir(follow_symlinks=False)
                    and (
                        self._tree.property("showHiddenDirectories")
                        or not entry.name.startswith(".")
                    )
                    for entry in entries
                )
        except OSError:
            contains_subdirectory = False
        self._contains_subdirectory_cache[cache_key] = contains_subdirectory
        return contains_subdirectory

    def _symbol_kind(self, index: QModelIndex) -> str:
        if not self._contains_subdirectory(index):
            return "none"
        return "down" if self._tree.isExpanded(index) else "plus"

    def _symbol_color(self, option: QStyleOptionViewItem) -> QColor:
        configured_color = self._tree.property("directoryIndicatorColor")
        if configured_color:
            return QColor(str(configured_color))
        return option.palette.color(QPalette.ColorRole.Text)

    def _hierarchy_color(self, option: QStyleOptionViewItem) -> QColor:
        configured_color = self._tree.property("directoryHierarchyColor")
        color = (
            QColor(str(configured_color))
            if configured_color
            else option.palette.color(QPalette.ColorRole.Mid)
        )
        color.setAlphaF(0.52)
        return color

    @staticmethod
    def _symbol_center(rect: QRect) -> QPointF:
        return QPointF(rect.right() - 5, QRectF(rect).center().y())

    @staticmethod
    def _branch_x(rect: QRect) -> int:
        return rect.left() + 1

    @staticmethod
    def _has_next_sibling(index: QModelIndex) -> bool:
        model = index.model()
        return model is not None and model.index(
            index.row() + 1, 0, index.parent()
        ).isValid()

    def _draw_hierarchy_lines(
        self,
        painter: QPainter,
        rect: QRect,
        index: QModelIndex,
        option: QStyleOptionViewItem,
    ) -> None:
        parent = index.parent()
        if not parent.isValid():
            return

        center_y = QRectF(rect).center().y()
        symbol_x = self._symbol_center(rect).x()
        branch_x = self._branch_x(rect)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(self._hierarchy_color(option), 1.0)
        pen.setDashPattern([1.0, 1.5])
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        ancestor = parent
        ancestor_x = branch_x - self._tree.indentation()
        while ancestor.isValid() and ancestor != self._tree.rootIndex():
            if self._has_next_sibling(ancestor):
                painter.drawLine(
                    QPointF(ancestor_x, rect.top()),
                    QPointF(ancestor_x, rect.bottom()),
                )
            ancestor = ancestor.parent()
            ancestor_x -= self._tree.indentation()

        painter.drawLine(
            QPointF(branch_x, rect.top()), QPointF(branch_x, center_y)
        )
        if self._has_next_sibling(index):
            painter.drawLine(
                QPointF(branch_x, center_y), QPointF(branch_x, rect.bottom())
            )
        painter.drawLine(
            QPointF(branch_x, center_y),
            QPointF(symbol_x - self._SYMBOL_SIZE / 2 - 2, center_y),
        )
        painter.restore()

    def _draw_symbol(
        self, painter: QPainter, rect: QRect, kind: str, color: QColor
    ) -> None:
        center = self._symbol_center(rect)
        half_size = self._SYMBOL_SIZE / 2
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(color, self._LINE_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        if kind == "plus":
            painter.drawLine(
                QPointF(center.x() - half_size, center.y()),
                QPointF(center.x() + half_size, center.y()),
            )
            painter.drawLine(
                QPointF(center.x(), center.y() - half_size),
                QPointF(center.x(), center.y() + half_size),
            )
        elif kind == "down":
            painter.drawPolyline(
                [
                    QPointF(center.x() - half_size, center.y() - 2),
                    QPointF(center.x(), center.y() + 2),
                    QPointF(center.x() + half_size, center.y() - 2),
                ]
            )
        else:
            painter.drawPolyline(
                [
                    QPointF(center.x() - 2, center.y() - half_size),
                    QPointF(center.x() + 2, center.y()),
                    QPointF(center.x() - 2, center.y() + half_size),
                ]
            )
        painter.restore()

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        if index.column() != 0 or not self._directory_path(index):
            return
        indicator_rect = self.indicator_rect(index)
        self._draw_hierarchy_lines(painter, indicator_rect, index, option)
        symbol_kind = self._symbol_kind(index)
        if symbol_kind != "none":
            self._draw_symbol(
                painter, indicator_rect, symbol_kind, self._symbol_color(option)
            )

    def eventFilter(self, watched, event) -> bool:
        if (
            watched is self._tree.viewport()
            and event.type()
            in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease)
            and event.button() == Qt.MouseButton.LeftButton
        ):
            index = self._tree.indexAt(event.position().toPoint())
            if index.isValid() and self.indicator_rect(index).contains(
                event.position().toPoint()
            ):
                # Consume the complete click sequence.  QTreeView handles its
                # native branch indicator on release, so toggling on press
                # would otherwise be immediately undone by the view.
                if (
                    event.type() == QEvent.Type.MouseButtonRelease
                    and self._contains_subdirectory(index)
                ):
                    self._tree.setExpanded(index, not self._tree.isExpanded(index))
                return True
        return super().eventFilter(watched, event)


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
    font-size: 13px; font-weight: 600;
    padding: 8px 8px 2px 8px;
}
QWidget#centralwidget QLabel#directoryPathLabel {
    font-size: 11px; padding: 0 8px 5px 8px;
}
QWidget#centralwidget QTreeView {
    border: none; padding: 4px 7px;
}
QWidget#centralwidget QTreeView::item {
    min-height: 28px; border-radius: 5px; padding: 1px 5px;
}
QWidget#centralwidget QTreeView::branch { image: none; }
QWidget#centralwidget QListWidget {
    border: none; padding: 10px;
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
QWidget#centralwidget QToolButton#informationToggleButton {
    min-height: 22px; max-height: 22px;
    min-width: 22px; max-width: 22px;
    border-radius: 6px; padding: 0;
    background: palette(button); color: palette(button-text);
    border: 1px solid palette(mid); font-weight: 600;
}
QWidget#centralwidget QToolButton#informationToggleButton:hover {
    background: palette(alternate-base);
}
QWidget#centralwidget QToolButton#informationToggleButton:checked {
    background: palette(alternate-base); border-color: palette(highlight);
}
QWidget#centralwidget QWidget#informationPanel {
    border-left: 1px solid palette(mid);
}
QWidget#centralwidget QLabel#informationEmptyLabel {
    color: palette(mid); padding: 8px 2px;
}
QWidget#informationPanel QLineEdit#manualMetadataField,
QWidget#informationPanel QTextEdit#manualMetadataField {
    background-color: palette(base); color: palette(text);
    border: 1px solid palette(mid); border-radius: 4px; padding: 4px;
    selection-background-color: palette(highlight);
    selection-color: palette(highlighted-text);
}
QWidget#informationPanel QLineEdit#manualMetadataField:focus,
QWidget#informationPanel QTextEdit#manualMetadataField:focus {
    border-color: palette(highlight);
}
QWidget#centralwidget QWidget#pdfPageNavigation QPushButton {
    min-height: 20px; max-height: 20px;
    min-width: 22px; max-width: 22px;
    padding: 0; border-radius: 5px;
}
QWidget#centralwidget QLabel#pdfPageLabel { padding: 0 4px; }
QWidget#fullscreenPdfThumbnailBar {
    border: none; border-right: 1px solid palette(mid); padding: 5px;
    background: palette(window);
}
QWidget#fullscreenPdfThumbnailBar::item {
    border-radius: 5px; padding: 4px; margin: 1px;
}
QWidget#fullscreenPdfThumbnailBar::item:selected {
    background: palette(alternate-base); border: 1px solid palette(highlight);
}
QWidget#fullscreenPdfThumbnailBusy {
    border-top: 1px solid palette(mid); padding: 4px 6px;
    background: palette(window);
}
QWidget#fullscreenPdfThumbnailBusy QLabel { color: palette(text); }
QWidget#fullscreenPdfPrintBar {
    border-top: 1px solid palette(mid); padding: 6px;
    background: #242424;
}
QWidget#fullscreenPdfPrintBar QPushButton {
    color: #f8f8f8; background: #3a3a3a; border: 1px solid #777;
    border-radius: 4px; min-height: 28px; padding: 3px 8px;
}
QWidget#fullscreenPdfPrintBar QPushButton:hover {
    color: white; background: #555; border-color: #ddd;
}
QLabel#pdfFullscreenNavigationHint {
    border-radius: 7px; padding: 7px 11px; font-size: 14px; font-weight: 600;
}
QMainWindow#MainWindow QStatusBar {
    min-height: 46px; max-height: 46px; padding: 2px 12px;
}
QWidget#bottomControlBar QWidget#thumbnailSizeControls QToolButton,
QWidget#bottomControlBar QPushButton {
    min-height: 28px; max-height: 28px;
    min-width: 36px; max-width: 36px;
    padding: 0; border-radius: 6px;
    border: 1px solid palette(mid); background: palette(button);
}
QWidget#bottomControlBar QWidget#thumbnailSizeControls QToolButton {
    min-width: 30px; max-width: 30px; font-size: 20px; font-weight: 600;
}
QWidget#bottomControlBar QPushButton {
    font-size: 24px; font-weight: 500;
}
QWidget#bottomControlBar QWidget#thumbnailSizeControls QToolButton:hover,
QWidget#bottomControlBar QPushButton:hover {
    background: palette(alternate-base);
}
QWidget#bottomControlBar QLabel#fileNameLabel {
    font-size: 14px; padding: 0 12px;
}
QWidget#bottomControlBar QToolButton#informationToggleButton {
    border: 1px solid transparent; border-radius: 12px; padding: 0;
    background: #2878c8; color: #ffffff;
    font-size: 15px; font-weight: 700;
}
QWidget#bottomControlBar QToolButton#informationToggleButton:hover {
    border: 1px solid #ffffff;
}
QWidget#bottomControlBar QToolButton#informationToggleButton:checked {
    background: #2878c8; color: #ffffff;
    border: 1px solid #ffffff;
}
QWidget#bottomControlBar QWidget#bottomBarSeparator {
    background: palette(mid); max-width: 1px;
}
QWidget#bottomControlBar QSlider {
    background: transparent; border: none; outline: none;
}
QWidget#bottomControlBar QSlider:focus { outline: none; }
QWidget#bottomControlBar QSlider::groove:horizontal {
    height: 5px; border: 1px solid palette(dark); border-radius: 3px;
    background: palette(midlight);
}
QWidget#bottomControlBar QSlider::sub-page:horizontal {
    border-radius: 2px; background: palette(highlight);
}
QWidget#bottomControlBar QSlider::add-page:horizontal {
    border-radius: 2px; background: palette(midlight);
}
QWidget#bottomControlBar QSlider::handle:horizontal {
    width: 10px; margin: -4px 0; border: 1px solid palette(dark);
    border-radius: 5px; background: palette(highlight);
}
QWidget#quickSwitches QToolButton {
    min-height: 22px; padding: 1px 6px; border-radius: 5px;
    border: 1px solid palette(mid); background: palette(button);
}
QWidget#quickSwitches QToolButton:hover {
    background: palette(alternate-base);
}
QWidget#quickSwitches QToolButton:checked {
    background: palette(alternate-base); border-color: palette(highlight);
    color: palette(text); font-weight: 600;
}
QWidget#centralwidget QSplitter::handle:horizontal { width: 1px; }
QWidget#centralwidget QSplitter::handle:vertical { height: 1px; }
"""


def color_scheme_stylesheet(colors: dict[str, str] | None) -> str:
    if colors is None:
        # Keep the directory tree selection tied to the desktop palette.  In
        # particular, do not let an inherited item text color turn a selected
        # system-theme row into white text on a light highlight background.
        return selection_menu_stylesheet() + interface_polish_stylesheet() + """
QWidget#centralwidget QTreeView::item:selected,
QWidget#centralwidget QTreeView::item:selected:active,
QWidget#centralwidget QTreeView::item:selected:!active {
    background-color: palette(highlight); color: palette(highlighted-text);
}
QWidget#thumbnailPanel[thumbnailPosition="top"] {
    background-color: palette(alternate-base);
    border-bottom: 1px solid palette(mid);
}
QWidget#thumbnailPanel[thumbnailPosition="top"] QListWidget#thumbnailList {
    background-color: transparent;
}
"""
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
QTreeView::item:selected, QTreeView::item:selected:active,
QTreeView::item:selected:!active {{
    background-color: {colors['hover']}; color: {colors['text']};
    border: 1px solid {colors['border']};
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
QWidget#bottomControlBar QToolButton#informationToggleButton,
QWidget#bottomControlBar QToolButton#informationToggleButton:checked {{
    background-color: {colors['selection']}; color: {colors['selection_text']};
}}
QWidget#bottomControlBar QToolButton#informationToggleButton:hover,
QWidget#bottomControlBar QToolButton#informationToggleButton:checked {{
    border-color: {colors['selection_text']};
}}
QWidget#informationPanel {{ background-color: {colors['panel']}; color: {colors['text']}; }}
QWidget#informationPanel QScrollArea {{ background-color: {colors['panel']}; border: none; }}
QWidget#informationPanel QLabel#informationPanelTitle {{ font-weight: 600; }}
QWidget#informationPanel QToolButton#informationCloseButton {{
    min-width: 20px; max-width: 20px; min-height: 20px; max-height: 20px;
    padding: 0; border-radius: 5px; border-color: transparent; background: transparent;
}}
QWidget#informationPanel QToolButton#informationCloseButton:hover {{ background-color: {colors['hover']}; }}
QWidget#informationPanel QGroupBox#informationSection {{
    border: none; margin-top: 7px; padding: 5px 0 0 0; font-weight: 600;
}}
QWidget#informationPanel QGroupBox#informationSection::title {{
    subcontrol-origin: margin; left: 0; padding: 0; color: {colors['text']};
}}
QWidget#informationPanel QLabel#informationFieldLabel {{ color: {colors['muted']}; font-weight: 400; }}
QWidget#informationPanel QLabel#informationValueLabel {{ color: {colors['text']}; font-weight: 500; }}
QWidget#informationPanel QLabel#manualMetadataLabel {{ color: {colors['muted']}; font-size: 11px; }}
QWidget#informationPanel QLineEdit#manualMetadataField,
QWidget#informationPanel QTextEdit#manualMetadataField {{
    background-color: {colors['button']}; color: {colors['text']};
    border: 1px solid {colors['border']}; border-radius: 4px; padding: 4px;
    selection-background-color: {colors['selection']}; selection-color: {colors['selection_text']};
}}
QWidget#informationPanel QLineEdit#manualMetadataField:focus,
QWidget#informationPanel QTextEdit#manualMetadataField:focus {{ border-color: {colors['selection']}; }}
QWidget#informationPanel QLineEdit#manualMetadataField:disabled,
QWidget#informationPanel QTextEdit#manualMetadataField:disabled {{ color: {colors['muted']}; }}
QWidget#informationPanel QFrame#manualMetadataSeparator {{ background: {colors['border']}; max-height: 1px; }}
QWidget#informationPanel QToolButton#allMetadataToggle {{
    padding: 2px 0; border: none; border-radius: 4px; background: transparent;
    text-align: left; font-weight: 600;
}}
QWidget#informationPanel QToolButton#allMetadataToggle:hover {{ background-color: {colors['hover']}; }}
QWidget#informationPanel QScrollBar:vertical {{ width: 8px; margin: 2px 0; }}
QWidget#informationPanel QScrollBar::handle:vertical {{ background: {colors['border']}; min-height: 24px; border-radius: 4px; }}
QSplitter::handle {{ background-color: {colors['border']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QScrollBar {{ background-color: {colors['panel']}; }}
QStatusBar {{
    background-color: {colors['panel']}; color: {colors['text']};
    border-top: 1px solid {colors['border']};
}}
QStatusBar::item {{ border: none; }}
QWidget#thumbnailSizeControls QSlider {{
    background: transparent; border: none; outline: none;
}}
QWidget#thumbnailSizeControls QSlider:focus {{ outline: none; }}
QWidget#thumbnailSizeControls QSlider::groove:horizontal {{
    height: 5px; border-radius: 2px; background: {colors['slider_groove']};
}}
QWidget#thumbnailSizeControls QSlider::sub-page:horizontal {{
    border-radius: 2px; background: {colors['slider_groove']};
}}
QWidget#thumbnailSizeControls QSlider::add-page:horizontal {{
    border-radius: 2px; background: {colors['slider_groove']};
}}
QWidget#thumbnailSizeControls QSlider::handle:horizontal {{
    width: 10px; margin: -4px 0; border: 1px solid {colors['panel']};
    border-radius: 5px; background: {colors['slider_active']};
}}
QWidget#thumbnailSizeControls QSlider::groove:horizontal:disabled,
QWidget#thumbnailSizeControls QSlider::add-page:horizontal:disabled,
QWidget#thumbnailSizeControls QSlider::sub-page:horizontal:disabled {{
    background: {colors['slider_disabled_groove']};
}}
QWidget#thumbnailSizeControls QSlider::handle:horizontal:disabled {{
    background: {colors['slider_disabled_active']};
}}
QToolTip {{
    background-color: palette(toolTipBase); color: palette(toolTipText);
    border: 1px solid palette(mid); padding: 4px;
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


def multi_image_sources(
    paths: list[Path], include_capture_date: bool = False,
) -> list[ImageSourceInfo]:
    """Read each image's lightweight metadata once for PagePlan creation."""

    sources: list[ImageSourceInfo] = []
    for path in paths:
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        size = reader.size()
        width = size.width() if size.isValid() else 1
        height = size.height() if size.isValid() else 1
        sources.append(ImageSourceInfo(
            path, width, height, filename=path.name,
            capture_date=capture_date_text(path) if include_capture_date else None,
        ))
    return sources


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


def _information_value(value: object) -> str | None:
    text = exif_text(value)
    if text is not None:
        return text
    number = rational_float(value)
    return format_decimal(number, 2) if number is not None else None


def _exif_value(exif, exif_ifd: dict, tag: int) -> object:
    try:
        value = exif_ifd.get(tag)
        return exif.get(tag) if value is None else value
    except Exception:
        return None


def build_information_metadata(path: Path) -> dict[str, dict[str, str]]:
    """Return present file and EXIF fields, grouped for the information panel."""
    groups: dict[str, dict[str, str]] = {t("BILD"): {t("Dateiname"): path.name}}
    try:
        file_info = path.stat()
        groups[t("BILD")][t("Dateipfad")] = str(path)
        groups[t("BILD")][t("Dateigröße")] = format_file_size(file_info.st_size)
    except OSError:
        pass
    suffix = path.suffix.lstrip(".").upper()
    if suffix:
        groups[t("BILD")][t("Dateiformat")] = suffix
    if path.suffix.lower() in PDF_EXTENSIONS:
        return groups

    exif_found = False
    try:
        with PillowImage.open(path) as image:
            width, height = image.size
            groups[t("BILD")][t("Abmessungen")] = f"{width} × {height} Pixel"
            groups[t("BILD")][t("Megapixel")] = f"{format_decimal(width * height / 1_000_000, 1)} MP"
            if image.format:
                groups[t("BILD")][t("Dateiformat")] = image.format
            dpi = image.info.get("dpi")
            if isinstance(dpi, (tuple, list)) and len(dpi) >= 2:
                x_dpi, y_dpi = rational_float(dpi[0]), rational_float(dpi[1])
                if x_dpi is not None and y_dpi is not None:
                    groups[t("BILD")][t("Auflösung")] = f"{format_decimal(x_dpi)} × {format_decimal(y_dpi)} DPI"
            exif = image.getexif()
            exif_found = bool(exif)
            try:
                exif_ifd = exif.get_ifd(0x8769)
            except Exception:
                exif_ifd = {}

            camera: dict[str, str] = {}
            for label, tag in (("Hersteller", 271), ("Kameramodell", 272), ("Objektiv", 42036), ("Objektivhersteller", 42035), ("Firmware", 305)):
                value = _information_value(_exif_value(exif, exif_ifd, tag))
                if value:
                    camera[label] = value
            lens_spec = format_lens_specification(_exif_value(exif, exif_ifd, 42034))
            if lens_spec and "Objektiv" not in camera:
                camera["Objektiv"] = lens_spec
            if camera:
                groups[t("KAMERA")] = {t(label): value for label, value in camera.items()}

            recording: dict[str, str] = {}
            for tag in (36867, 36868, 306):
                date = format_date(_exif_value(exif, exif_ifd, tag))
                if date:
                    recording["Aufnahmedatum"] = date
                    break
            values = (
                ("Belichtungszeit", format_exposure(_exif_value(exif, exif_ifd, 33434))),
                ("Blende", (lambda value: f"f/{format_decimal(value)}" if value and value > 0 else None)(rational_float(_exif_value(exif, exif_ifd, 33437)))),
                ("ISO", extract_iso_value(exif)),
                ("Brennweite", (lambda value: f"{format_decimal(value)} mm" if value and value > 0 else None)(rational_float(_exif_value(exif, exif_ifd, 37386)))),
                ("Brennweite (KB)", (lambda value: f"{format_decimal(value)} mm" if value and value > 0 else None)(rational_float(_exif_value(exif, exif_ifd, 41989)))),
                ("Belichtungskorrektur", (lambda value: f"{format_decimal(value)} EV" if value is not None else None)(rational_float(_exif_value(exif, exif_ifd, 37380)))),
                ("Belichtungsprogramm", _information_value(_exif_value(exif, exif_ifd, 34850))),
                ("Messmethode", _information_value(_exif_value(exif, exif_ifd, 37383))),
                ("Blitz", _information_value(_exif_value(exif, exif_ifd, 37385))),
                ("Weißabgleich", _information_value(_exif_value(exif, exif_ifd, 41987))),
            )
            recording.update({label: value for label, value in values if value})
            if recording:
                groups[t("AUFNAHME")] = {t(label): value for label, value in recording.items()}

            orientation = _information_value(exif.get(274))
            color_space = _information_value(_exif_value(exif, exif_ifd, 40961))
            if orientation:
                groups[t("BILD")][t("Ausrichtung")] = orientation
            if color_space:
                groups[t("BILD")][t("Farbraum")] = color_space
            try:
                gps = exif.get_ifd(0x8825)
            except Exception:
                gps = {}
            latitude = gps_coordinate(gps.get(2), gps.get(1))
            longitude = gps_coordinate(gps.get(4), gps.get(3))
            if latitude is not None and longitude is not None:
                gps_group = {"Breitengrad": f"{latitude:.6f}".replace(".", ","), "Längengrad": f"{longitude:.6f}".replace(".", ",")}
                altitude = rational_float(gps.get(6))
                if altitude is not None:
                    gps_group["Höhe"] = f"{format_decimal(altitude)} m"
                groups[t("GPS")] = gps_group
    except Exception:
        pass
    if not exif_found:
        groups[t("WEITERE EXIF-DATEN")] = {"Hinweis": t("Keine EXIF-Daten vorhanden")}
    return groups


def _metadata_value_present(value: object) -> bool:
    """Return whether a raw metadata value carries information (0 and False do)."""
    if value is None:
        return False
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or cleaned.casefold() in {
            "none", "null", "n/a", "not available",
        }:
            return False
        return bool(re.sub(r"[\s,;|/\\()[\]{}<>…—–-]", "", cleaned))
    if isinstance(value, (bytes, bytearray)):
        return bool(value)
    if isinstance(value, (tuple, list, set)):
        return any(_metadata_value_present(item) for item in value)
    if isinstance(value, dict):
        return any(_metadata_value_present(item) for item in value.values())
    return True


def _raw_metadata_text(value: object, limit: int = 500) -> str | None:
    """Safely present raw metadata without exposing huge binary blocks."""
    if not _metadata_value_present(value):
        return None
    if isinstance(value, bytes):
        return f"{len(value)} Bytes (binär)"
    if isinstance(value, (tuple, list)):
        parts = [_raw_metadata_text(item, 100) for item in value[:20]]
        text = ", ".join(part for part in parts if part is not None)
        if not text:
            return None
        if len(value) > 20:
            text += ", …"
    elif isinstance(value, set):
        parts = [_raw_metadata_text(item, 100) for item in sorted(value, key=str)[:20]]
        text = ", ".join(part for part in parts if part is not None)
        if not text:
            return None
    elif isinstance(value, dict):
        parts = [
            f"{key}: {text}"
            for key, item in value.items()
            if (text := _raw_metadata_text(item, 100)) is not None
        ]
        text = ", ".join(parts)
        if not text:
            return None
    else:
        text = exif_text(value) or str(value)
    return text if len(text) <= limit else f"{text[:limit - 1]}…"


def _metadata_tag_name(tags: dict[int, str], tag: int) -> str:
    return tags.get(tag, f"Unbekanntes Tag 0x{tag:04X}")


def build_all_image_metadata(path: Path) -> dict[str, dict[str, str]]:
    """Read the complete, optional metadata view on demand."""
    if path.suffix.lower() in PDF_EXTENSIONS:
        return {}
    groups: dict[str, dict[str, str]] = {}
    try:
        with PillowImage.open(path) as image:
            exif = image.getexif()
            try:
                exif_ifd = exif.get_ifd(0x8769)
            except Exception:
                exif_ifd = {}
            exif_fields: dict[str, str] = {}
            for tag, value in exif.items():
                if tag == 34853:
                    continue
                text = (
                    "vorhanden (nicht dekodiert)" if tag == 37500 else _raw_metadata_text(value)
                )
                if text is not None:
                    exif_fields[_metadata_tag_name(ExifTags.TAGS, tag)] = text
            for tag, value in exif_ifd.items():
                text = "vorhanden (nicht dekodiert)" if tag == 37500 else _raw_metadata_text(value)
                if text is not None:
                    exif_fields.setdefault(_metadata_tag_name(ExifTags.TAGS, tag), text)
            if exif_fields:
                groups["EXIF"] = dict(sorted(exif_fields.items(), key=lambda item: item[0].casefold()))
            try:
                gps_ifd = exif.get_ifd(0x8825)
            except Exception:
                gps_ifd = {}
            if gps_ifd:
                gps_fields = ((
                    _metadata_tag_name(ExifTags.GPSTAGS, tag), _raw_metadata_text(value)
                ) for tag, value in gps_ifd.items())
                groups["GPS"] = dict(sorted(
                    ((name, text) for name, text in gps_fields if text is not None),
                    key=lambda item: item[0].casefold(),
                ))
                if not groups["GPS"]:
                    del groups["GPS"]
            try:
                iptc = IptcImagePlugin.getiptcinfo(image) or {}
            except Exception:
                iptc = {}
            if iptc:
                groups["IPTC"] = dict(sorted(
                    ((f"{tag[0]}:{tag[1]}", text) for tag, value in iptc.items() if (text := _raw_metadata_text(value)) is not None),
                    key=lambda item: item[0],
                ))
                if not groups["IPTC"]:
                    del groups["IPTC"]
            other_fields = {
                str(key): text
                for key, value in image.info.items()
                if key != "exif"
                and "xmp" not in str(key).casefold()
                and (text := _raw_metadata_text(value)) is not None
            }
            if other_fields:
                groups["Datei / Sonstige"] = dict(sorted(other_fields.items(), key=lambda item: item[0].casefold()))
    except Exception:
        return {}
    return groups


class ImageIndexSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(int, bool)
    failed = Signal(str)


class ImageIndexTask(QRunnable):
    def __init__(self, folders: list[tuple[Path, bool]], database_path: Path | None = None) -> None:
        super().__init__()
        self.folders = folders
        self.database_path = database_path
        self.signals = ImageIndexSignals()
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        indexed = 0
        try:
            for folder, recursive in self.folders:
                if self._cancelled.is_set(): break
                indexed += index_folder(
                    folder, recursive, read_manual_image_metadata,
                    path=self.database_path,
                    progress=self.signals.progress.emit,
                    cancelled=self._cancelled.is_set,
                )
        except Exception as error:
            self.signals.failed.emit(str(error))
            return
        self.signals.finished.emit(indexed, self._cancelled.is_set())


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

        self.setWindowTitle(t("Bilder verkleinert exportieren"))
        self.setMinimumSize(590, 650)
        self.resize(670, 720)
        self.setStyleSheet(message_box_stylesheet(colors))
        main_layout = QVBoxLayout(self)
        heading = QLabel(t("{count} Bilder ausgewählt").format(count=len(paths)), self)
        heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        main_layout.addWidget(heading)

        size_group = QGroupBox(t("Zielgröße"), self)
        size_form = QFormLayout(size_group)
        self.preset_combo = QComboBox(size_group)
        for label, _size in self.PRESETS:
            self.preset_combo.addItem(t(label))
        size_form.addRow(t("Voreinstellung:"), self.preset_combo)
        size_row = QHBoxLayout()
        self.width_spin = QSpinBox(size_group)
        self.height_spin = QSpinBox(size_group)
        for spin in (self.width_spin, self.height_spin):
            spin.setRange(100, 20000)
            spin.setSuffix(t(" Pixel"))
        self.width_spin.setValue(
            settings.value(EXPORT_WIDTH_KEY, 1920, type=int)
        )
        self.height_spin.setValue(
            settings.value(EXPORT_HEIGHT_KEY, 1080, type=int)
        )
        size_row.addWidget(self.width_spin)
        size_row.addWidget(QLabel("×", size_group))
        size_row.addWidget(self.height_spin)
        size_form.addRow(t("Maximale Breite × Höhe:"), size_row)
        self.enlarge_checkbox = QCheckBox(t("Kleinere Bilder vergrößern"), size_group)
        self.enlarge_checkbox.setChecked(
            settings.value(EXPORT_ENLARGE_KEY, False, type=bool)
        )
        size_form.addRow("", self.enlarge_checkbox)
        main_layout.addWidget(size_group)

        quality_group = QGroupBox(t("JPEG-Qualität"), self)
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
                t("70: kleine Dateien · 85: gute Qualität · 90: sehr gute Qualität · 95: sehr hohe Qualität"),
                quality_group,
            )
        )
        main_layout.addWidget(quality_group)

        naming_group = QGroupBox(t("Dateinamen und Zielordner"), self)
        naming_form = QFormLayout(naming_group)
        self.suffix_edit = QLineEdit(
            settings.value(EXPORT_SUFFIX_KEY, "-klein", type=str), naming_group
        )
        naming_form.addRow(t("Dateinamen-Zusatz:"), self.suffix_edit)
        destination_row = QHBoxLayout()
        saved_directory = settings.value(EXPORT_DIRECTORY_KEY, "", type=str)
        suggested_directory = (
            Path(saved_directory).expanduser()
            if saved_directory
            else default_directory / "Export"
        )
        self.destination_edit = QLineEdit(str(suggested_directory), naming_group)
        browse_button = QPushButton(t("Durchsuchen …"), naming_group)
        browse_button.clicked.connect(self._browse_destination)
        destination_row.addWidget(self.destination_edit, 1)
        destination_row.addWidget(browse_button)
        naming_form.addRow(t("Zielordner:"), destination_row)
        main_layout.addWidget(naming_group)

        metadata_group = QGroupBox(t("Metadaten"), self)
        metadata_layout = QVBoxLayout(metadata_group)
        self.metadata_checkbox = QCheckBox(
            t("Aufnahmedaten übernehmen"), metadata_group
        )
        self.metadata_checkbox.setChecked(
            settings.value(EXPORT_METADATA_KEY, True, type=bool)
        )
        self.gps_checkbox = QCheckBox(t("GPS-Daten entfernen"), metadata_group)
        self.gps_checkbox.setChecked(
            settings.value(EXPORT_REMOVE_GPS_KEY, True, type=bool)
        )
        metadata_layout.addWidget(self.metadata_checkbox)
        metadata_layout.addWidget(self.gps_checkbox)
        main_layout.addWidget(metadata_group)

        estimate_group = QGroupBox(t("Größenabschätzung"), self)
        estimate_layout = QVBoxLayout(estimate_group)
        self.estimate_label = QLabel(t("Dateigröße wird geschätzt …"), estimate_group)
        self.average_label = QLabel("", estimate_group)
        estimate_layout.addWidget(self.estimate_label)
        estimate_layout.addWidget(self.average_label)
        main_layout.addWidget(estimate_group)

        progress_group = QGroupBox(t("Exportfortschritt"), self)
        progress_layout = QVBoxLayout(progress_group)
        self.progress_bar = QProgressBar(progress_group)
        self.progress_bar.setRange(0, len(paths))
        self.progress_label = QLabel(t("Bereit zum Exportieren"), progress_group)
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.progress_label)
        main_layout.addWidget(progress_group)

        buttons = QDialogButtonBox(self)
        self.export_button = buttons.addButton(
            t("Exportieren"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.cancel_button = buttons.addButton(
            t("Abbrechen"), QDialogButtonBox.ButtonRole.RejectRole
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
            t("JPEG-Qualität: {quality} %").format(quality=self.quality_slider.value())
        )

    def _schedule_estimate(self) -> None:
        self._estimate_generation += 1
        self.estimate_label.setText(t("Dateigröße wird geschätzt …"))
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
            self.estimate_label.setText(t("Größe konnte nicht geschätzt werden."))
            self.estimate_label.setToolTip(error)
            self.average_label.clear()
            return
        size = int(estimated_size)
        self.estimate_label.setText(
            t("Geschätzte Gesamtgröße: ca. {size}").format(size=format_file_size(size))
        )
        average = round(size / len(self.paths)) if self.paths else 0
        self.average_label.setText(
            t("Durchschnittlich ca. {size} pro Bild").format(size=format_file_size(average))
        )

    def _browse_destination(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            t("Zielordner auswählen"),
            self.destination_edit.text() or str(self.default_directory),
        )
        if directory:
            self.destination_edit.setText(directory)

    def _start_export(self) -> None:
        destination_text = self.destination_edit.text().strip()
        suffix = self.suffix_edit.text().strip()
        if not destination_text:
            self._show_input_error(t("Bitte wähle einen Zielordner aus."))
            return
        if "/" in suffix or "\0" in suffix:
            self._show_input_error(
                t("Der Dateinamen-Zusatz darf weder „/“ noch Nullzeichen enthalten.")
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
                t("Der Zielordner kann nicht angelegt oder beschrieben werden.")
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
        self.cancel_button.setText(t("Abbrechen"))
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
        self.progress_label.setText(t("Bild {current} von {total}: {name}").format(current=current, total=total, name=filename))

    def _cancel_or_close(self) -> None:
        if self._export_running and self.export_task is not None:
            self.export_task.cancel()
            self.cancel_button.setEnabled(False)
            self.progress_label.setText(t("Export wird abgebrochen …"))
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
        self.cancel_button.setText(t("Schließen"))
        self.export_button.setEnabled(True)
        successful = list(result["successful"])
        skipped = list(result["skipped"])
        failures = list(result["failures"])
        if result["cancelled"]:
            self.progress_label.setText(t("Export abgebrochen"))
        else:
            self.progress_bar.setValue(self.progress_bar.maximum())
            self.progress_label.setText(t("Export abgeschlossen"))
        dialog = QMessageBox(self)
        dialog.setWindowTitle(t("Bilder verkleinert exportieren"))
        dialog.setIcon(QMessageBox.Icon.Information if not failures else QMessageBox.Icon.Warning)
        dialog.setText(
            t("{count} Bilder wurden erfolgreich exportiert.").format(count=len(successful))
        )
        dialog.setInformativeText(
            t("Zielordner: {path}\nTatsächliche Gesamtgröße: {size}\nÜbersprungen: {skipped}\nFehlgeschlagen: {failed}").format(path=result["destination"], size=format_file_size(int(result["total_size"])), skipped=len(skipped), failed=len(failures)) + ("\n" + t("Der Export wurde abgebrochen.") if result["cancelled"] else "")
        )
        details = skipped + failures
        if details:
            dialog.setDetailedText(
                t("Exportfehler: {detail}").format(detail="\n".join(details))
            )
        open_button = dialog.addButton(
            t("Zielordner öffnen"), QMessageBox.ButtonRole.ActionRole
        )
        close_button = dialog.addButton(
            t("Schließen"), QMessageBox.ButtonRole.RejectRole
        )
        dialog.setDefaultButton(close_button)
        dialog.exec()
        if dialog.clickedButton() is open_button:
            self.open_folder_callback(Path(str(result["destination"])))

    def _show_input_error(self, message: str) -> None:
        dialog = QMessageBox(self)
        dialog.setWindowTitle(t("Bilder verkleinert exportieren"))
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(message)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.button(QMessageBox.StandardButton.Ok).setText(t("OK"))
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
        self.setWindowTitle(t("Bilder vergleichen"))
        self.setModal(True)
        self.resize(1200, 760)
        self.setMinimumSize(800, 500)
        self._paths = [left_path, right_path]

        layout = QVBoxLayout(self)
        self.coupling_checkbox = QCheckBox(t("Zoom und Verschieben koppeln"))
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
        self.fit_button = QPushButton(t("Einpassen"))
        self.actual_size_button = QPushButton("100 %")
        self.swap_button = QPushButton(t("Bilder tauschen"))
        self.close_button = QPushButton(t("Schließen"))
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
    folder_changed = Signal(object)

    def __init__(
        self,
        startup_directory: Path | None = None,
        startup_image: Path | None = None,
    ) -> None:
        super().__init__()
        self.settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)
        self._migrate_legacy_settings()
        self.language_manager = LanguageManager(self.settings)
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
        saved_thumbnail_position = self.settings.value(
            THUMBNAIL_POSITION_KEY, "top", type=str
        )
        self._thumbnail_position = (
            saved_thumbnail_position
            if saved_thumbnail_position in THUMBNAIL_POSITIONS
            else "top"
        )
        saved_last_visible_position = self.settings.value(
            LAST_VISIBLE_THUMBNAIL_POSITION_KEY, "top", type=str
        )
        self._last_visible_thumbnail_position = (
            self._thumbnail_position
            if self._thumbnail_position != "hidden"
            else (
                saved_last_visible_position
                if saved_last_visible_position in {"top", "left", "right"}
                else "top"
            )
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
        self._system_tooltip_palette = QPalette(QToolTip.palette())
        self.status_bar = self.window.statusBar()
        self.status_bar.setSizeGripEnabled(False)
        self.status_bar.setContentsMargins(4, 0, 4, 0)
        self.status_info_label = QLabel(t("Kein Bild ausgewählt"), self.status_bar)
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
        self._status_full_text = t("Kein Bild ausgewählt")
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
        self.previous_button.setToolTip(t("Vorheriges Bild"))
        self.previous_button.setAccessibleName(t("Vorheriges Bild"))
        self.next_button.setText("›")
        self.next_button.setToolTip(t("Nächstes Bild"))
        self.next_button.setAccessibleName(t("Nächstes Bild"))
        self.file_name_label = self._widget(QLabel, "fileNameLabel")
        self.previous_button.setFixedSize(22, 18)
        self.next_button.setFixedSize(22, 18)
        self._file_name_text = ""
        self._directory_path_text = ""
        self.splitter = self._widget(QSplitter, "mainSplitter")
        self.right_splitter = self._widget(QSplitter, "rightSplitter")
        self.directory_panel = self.directory_tree.parentWidget()
        self.preview_panel = self.image_scroll_area.parentWidget()
        self._install_network_navigation()
        self._install_pdf_page_navigation()
        self._install_thumbnail_size_controls()
        self._install_information_panel()
        self._install_fullscreen_pdf_thumbnail_bar()
        self._apply_thumbnail_position(save=False)
        self.current_directory: Path | None = None
        self.current_image: Path | None = None
        self._search_mode = False
        self._search_return_directory: Path | None = None
        self._search_return_image: Path | None = None
        self.manual_metadata = {"comment": "", "people": "", "place": "", "gps": ""}
        self._manual_metadata_path: Path | None = None
        self.manual_metadata_dirty = False
        self._pdf_document = None
        self._pdf_link_model = QPdfLinkModel(self.window)
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
        self._directory_loading_generation: int | None = None
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
        self._all_metadata_cache: dict[tuple[str, int, int], dict[str, dict[str, str]]] = {}
        self._all_metadata_expanded = False
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
        self.thumbnail_list.setWrapping(self._thumbnail_position == "top")
        self.thumbnail_list.setWordWrap(True)
        self.thumbnail_list.setIconSize(self._thumbnail_size)
        self.thumbnail_list.setGridSize(self._thumbnail_grid_size)
        if self._thumbnail_position in {"left", "right"}:
            self.thumbnail_panel.setFixedWidth(
                max(220, self._thumbnail_grid_size.width() + 30)
            )
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
        self.image_label.setText(t("Bild anklicken, um es anzuzeigen"))
        self.image_label.resize(self.image_scroll_area.viewport().size())
        image_tooltip = """🖱 Bedienung

• Mausrad: Zoomen
• Linke Maustaste ziehen: Bild verschieben
• Klick: Vollbild ein/aus
• 0: Bild einpassen
• 1: Originalgröße
• F11: Vollbild"""
        self.image_label.setToolTip(t(image_tooltip))
        self.image_scroll_area.viewport().setToolTip(t(image_tooltip))
        self.zoom_indicator = QLabel(self.image_scroll_area.viewport())
        self.zoom_indicator.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self.zoom_indicator.setStyleSheet(ZOOM_INDICATOR_STYLESHEET)
        self.zoom_indicator.hide()

        self.pdf_fullscreen_navigation_hint = QLabel(
            self.image_scroll_area.viewport()
        )
        self.pdf_fullscreen_navigation_hint.setObjectName(
            "pdfFullscreenNavigationHint"
        )
        self.pdf_fullscreen_navigation_hint.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        # This overlay sits on arbitrary PDF content.  Its contrast must not
        # depend on a desktop theme or on the fullscreen window stylesheet.
        self.pdf_fullscreen_navigation_hint.setStyleSheet(
            "QLabel#pdfFullscreenNavigationHint {"
            " background-color: rgba(20, 20, 20, 220); color: #ffffff;"
            " border: 1px solid rgba(255, 255, 255, 90); border-radius: 6px;"
            " padding: 7px 12px; font-size: 12pt; font-weight: normal; }"
        )
        self.pdf_fullscreen_navigation_hint.hide()
        self.pdf_fullscreen_navigation_hint_timer = QTimer(self)
        self.pdf_fullscreen_navigation_hint_timer.setSingleShot(True)
        self.pdf_fullscreen_navigation_hint_timer.timeout.connect(
            self.pdf_fullscreen_navigation_hint.hide
        )

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

        # QFileSystemModel populates directories asynchronously.  In particular,
        # a volume mounted after the application started may not yet have an
        # index when it is first selected as the startup directory.
        self._pending_tree_path: Path | None = None
        self._tree_path_retry_timer = QTimer(self.window)
        self._tree_path_retry_timer.setSingleShot(True)
        self._tree_path_retry_timer.timeout.connect(self._retry_pending_tree_path)
        self._create_directory_model()
        self._install_network_mount_watcher()

        # Initial proportions only; the splitters remain fully user-adjustable.
        self.splitter.setSizes([250, 950])
        self.right_splitter.setSizes([185, 515])
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
        self.pdf_previous_page_shortcut = QShortcut(
            QKeySequence(Qt.Key.Key_Up), self.window
        )
        self.pdf_next_page_shortcut = QShortcut(
            QKeySequence(Qt.Key.Key_Down), self.window
        )
        for shortcut, offset in (
            (self.pdf_previous_page_shortcut, -1),
            (self.pdf_next_page_shortcut, 1),
        ):
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(
                lambda value=offset: self._navigate_fullscreen_pdf_page(value)
            )
        self._create_application_menus()
        self.language_manager.translate_widget_tree(self.window)
        self.information_toggle_action = QAction(self.window)
        self.information_toggle_action.setShortcut(QKeySequence("I"))
        self.information_toggle_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.information_toggle_action.triggered.connect(
            self._toggle_information_panel
        )
        self.window.addAction(self.information_toggle_action)
        self.view_menu.addSeparator()
        self.view_menu.addAction(self.information_toggle_action)
        self._install_quick_switches()
        self._create_directory_navigation_buttons()
        self.refresh_i18n()
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
        self.previous_pdf_page_button.setAccessibleName(t("Vorherige PDF-Seite"))
        self.pdf_page_label = QLabel("", self.pdf_page_navigation)
        self.pdf_page_label.setObjectName("pdfPageLabel")
        self.pdf_page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_pdf_page_button = QPushButton("›", self.pdf_page_navigation)
        self.next_pdf_page_button.setObjectName("nextPdfPageButton")
        self.next_pdf_page_button.setToolTip("Nächste PDF-Seite")
        self.next_pdf_page_button.setAccessibleName(t("Nächste PDF-Seite"))
        for button in (self.previous_pdf_page_button, self.next_pdf_page_button):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setFixedSize(22, 20)
        layout.addStretch(1)
        layout.addWidget(self.previous_pdf_page_button)
        layout.addWidget(self.pdf_page_label)
        layout.addWidget(self.next_pdf_page_button)
        layout.addStretch(1)
        self.pdf_page_navigation.hide()
        self._pdf_page_navigation_layout_index: int | None = None

    def _install_fullscreen_pdf_thumbnail_bar(self) -> None:
        """Create the PDF-only page navigator shown beside a fullscreen page."""
        self.pdf_thumbnail_panel = QWidget(self.preview_content)
        self.pdf_thumbnail_panel.setObjectName("fullscreenPdfThumbnailPanel")
        thumbnail_layout = QVBoxLayout(self.pdf_thumbnail_panel)
        thumbnail_layout.setContentsMargins(0, 0, 0, 0)
        thumbnail_layout.setSpacing(0)
        self.pdf_thumbnail_bar = QListWidget(self.pdf_thumbnail_panel)
        self.pdf_thumbnail_bar.setObjectName("fullscreenPdfThumbnailBar")
        self.pdf_thumbnail_bar.setViewMode(QListView.ViewMode.IconMode)
        self.pdf_thumbnail_bar.setFlow(QListView.Flow.TopToBottom)
        self.pdf_thumbnail_bar.setWrapping(False)
        self.pdf_thumbnail_bar.setResizeMode(QListView.ResizeMode.Adjust)
        self.pdf_thumbnail_bar.setIconSize(QSize(132, 176))
        self.pdf_thumbnail_bar.setGridSize(QSize(140, 212))
        self.pdf_thumbnail_bar.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.pdf_thumbnail_bar.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.pdf_thumbnail_bar.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.pdf_thumbnail_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pdf_thumbnail_content = QWidget(self.pdf_thumbnail_panel)
        pdf_thumbnail_content_layout = QHBoxLayout(self.pdf_thumbnail_content)
        pdf_thumbnail_content_layout.setContentsMargins(0, 0, 0, 0)
        pdf_thumbnail_content_layout.setSpacing(0)
        self.pdf_print_checkbox_column = QWidget(self.pdf_thumbnail_content)
        self.pdf_print_checkbox_column.setObjectName("pdfPrintCheckboxColumn")
        checkbox_probe = QCheckBox(self.pdf_print_checkbox_column)
        self._pdf_print_checkbox_column_width = max(
            28, checkbox_probe.sizeHint().width() + 12
        )
        checkbox_probe.deleteLater()
        self.pdf_print_checkbox_column.setFixedWidth(
            self._pdf_print_checkbox_column_width
        )
        self.pdf_thumbnail_panel.setFixedWidth(
            174 + self._pdf_print_checkbox_column_width
        )
        self.pdf_thumbnail_bar.setParent(self.pdf_thumbnail_content)
        pdf_thumbnail_content_layout.addWidget(self.pdf_print_checkbox_column)
        pdf_thumbnail_content_layout.addWidget(self.pdf_thumbnail_bar, 1)
        # Navigate on press, not release: the first click must never be only a
        # selection when the bar is still receiving its lazy-render updates.
        self.pdf_thumbnail_bar.itemPressed.connect(self._select_pdf_thumbnail_page)
        self.pdf_thumbnail_bar.verticalScrollBar().valueChanged.connect(
            lambda _value: self._schedule_visible_pdf_thumbnails()
        )
        self.pdf_thumbnail_bar.verticalScrollBar().valueChanged.connect(
            lambda _value: self._update_pdf_print_checkbox_positions()
        )
        self.pdf_thumbnail_bar.verticalScrollBar().rangeChanged.connect(
            lambda _minimum, _maximum: self._update_pdf_print_checkbox_positions()
        )
        self.pdf_thumbnail_viewport = self.pdf_thumbnail_bar.viewport()
        self.pdf_thumbnail_viewport.installEventFilter(self)
        thumbnail_layout.addWidget(self.pdf_thumbnail_content, 1)
        self.pdf_thumbnail_busy = QWidget(self.pdf_thumbnail_panel)
        self.pdf_thumbnail_busy.setObjectName("fullscreenPdfThumbnailBusy")
        busy_layout = QHBoxLayout(self.pdf_thumbnail_busy)
        busy_layout.setContentsMargins(6, 3, 6, 3)
        busy_layout.setSpacing(5)
        self.pdf_thumbnail_spinner = QLabel("◷", self.pdf_thumbnail_busy)
        self.pdf_thumbnail_spinner.setFixedWidth(16)
        self.pdf_thumbnail_busy_label = QLabel(t("Wird geladen …"), self.pdf_thumbnail_busy)
        busy_layout.addWidget(self.pdf_thumbnail_spinner)
        busy_layout.addWidget(self.pdf_thumbnail_busy_label, 1)
        thumbnail_layout.addWidget(self.pdf_thumbnail_busy)
        self.pdf_thumbnail_busy.hide()
        self.pdf_print_bar = QWidget(self.pdf_thumbnail_panel)
        self.pdf_print_bar.setObjectName("fullscreenPdfPrintBar")
        pdf_print_layout = QVBoxLayout(self.pdf_print_bar)
        pdf_print_layout.setContentsMargins(6, 5, 6, 6)
        self.pdf_print_button = QPushButton(t("Drucken …"), self.pdf_print_bar)
        self.pdf_print_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pdf_print_button.clicked.connect(self._choose_pdf_pages_to_print)
        pdf_print_layout.addWidget(self.pdf_print_button)
        self.pdf_print_bar.setFixedHeight(
            self.pdf_print_button.sizeHint().height() + 11
        )
        thumbnail_layout.addWidget(self.pdf_print_bar)
        self._pdf_busy_frames = ("◷", "◴", "◶", "◵")
        self._pdf_busy_frame = 0
        self._pdf_busy_timer = QTimer(self.pdf_thumbnail_panel)
        self._pdf_busy_timer.setInterval(120)
        self._pdf_busy_timer.timeout.connect(self._advance_pdf_busy_indicator)
        self.preview_content_layout.insertWidget(0, self.pdf_thumbnail_panel)
        self.pdf_thumbnail_bar.hide()
        self.pdf_thumbnail_panel.hide()
        self._pdf_thumbnail_cache: dict[int, QPixmap] = {}
        self._pdf_thumbnail_pending: set[int] = set()
        self._pdf_thumbnail_render_scheduled = False
        self._pdf_thumbnail_document = None
        self._pdf_thumbnail_suspended = False
        self._pdf_print_selection: set[int] = set()
        self._pdf_print_checkboxes: dict[int, QCheckBox] = {}

    def _update_pdf_print_footer_height(self) -> None:
        margins = self.pdf_print_bar.layout().contentsMargins()
        self.pdf_print_bar.setFixedHeight(
            self.pdf_print_button.sizeHint().height()
            + margins.top()
            + margins.bottom()
        )

    def _detach_pdf_page_navigation(self) -> None:
        layout = self.preview_panel.layout()
        if not isinstance(layout, QVBoxLayout):
            return
        index = layout.indexOf(self.pdf_page_navigation)
        if index >= 0:
            self._pdf_page_navigation_layout_index = index
            self.pdf_page_navigation.hide()
            layout.removeWidget(self.pdf_page_navigation)
            self.pdf_page_navigation.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )

    def _restore_pdf_page_navigation_to_layout(self) -> None:
        layout = self.preview_panel.layout()
        if not isinstance(layout, QVBoxLayout):
            return
        if layout.indexOf(self.pdf_page_navigation) < 0:
            index = self._pdf_page_navigation_layout_index
            layout.insertWidget(index if index is not None else layout.count(), self.pdf_page_navigation)
        self.pdf_page_navigation.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, False
        )
        self._pdf_page_navigation_layout_index = None

    def _reset_pdf_thumbnails(self) -> None:
        self._pdf_thumbnail_cache.clear()
        self._pdf_thumbnail_pending.clear()
        self._pdf_thumbnail_render_scheduled = False
        self._pdf_thumbnail_document = None
        self._pdf_thumbnail_suspended = False
        self._pdf_print_selection.clear()
        for checkbox in self._pdf_print_checkboxes.values():
            checkbox.deleteLater()
        self._pdf_print_checkboxes.clear()
        self.pdf_thumbnail_bar.clear()

    def _show_fullscreen_pdf_thumbnails(self) -> None:
        document = self._pdf_document
        if not self._fullscreen_mode or document is None or document.pageCount() < 1:
            self._hide_fullscreen_pdf_thumbnails()
            return
        page_count = document.pageCount()
        if self.pdf_thumbnail_bar.count() != page_count:
            self._reset_pdf_thumbnails()
            for page in range(page_count):
                item = QListWidgetItem(
                    t("Seite {page}").format(page=page + 1)
                )
                item.setData(Qt.ItemDataRole.UserRole, page)
                # A missing icon must occupy exactly the same space as a
                # rendered page.  Otherwise QListView recalculates rows while
                # the lazy queue is running and a click can land in a moving
                # item rectangle.
                item.setSizeHint(QSize(140, 212))
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
                self.pdf_thumbnail_bar.addItem(item)
                checkbox = QCheckBox(self.pdf_print_checkbox_column)
                checkbox.setObjectName("pdfPrintPageCheckbox")
                checkbox.setAccessibleName(
                    t("Seite {page}").format(page=page + 1)
                )
                checkbox.toggled.connect(
                    lambda checked, page_index=page: self._toggle_pdf_print_page(
                        page_index, checked
                    )
                )
                self._pdf_print_checkboxes[page] = checkbox
        if self._pdf_thumbnail_document is None and self.current_image is not None:
            thumbnail_result = load_pdf(self.current_image)
            self._pdf_thumbnail_document = thumbnail_result.document
        self.pdf_thumbnail_bar.show()
        self.pdf_thumbnail_panel.show()
        self._update_pdf_print_footer_height()
        self._sync_pdf_thumbnail_selection()
        self._refresh_pdf_thumbnail_text()
        QTimer.singleShot(0, self._update_pdf_print_checkbox_positions)
        self._schedule_visible_pdf_thumbnails()

    def _hide_fullscreen_pdf_thumbnails(self) -> None:
        self._set_pdf_thumbnail_busy(False)
        self.pdf_thumbnail_bar.hide()
        self.pdf_thumbnail_panel.hide()

    def _navigate_fullscreen_pdf_page(self, offset: int) -> None:
        if self._fullscreen_mode and self._pdf_document is not None:
            self._change_pdf_page(offset)

    def _advance_pdf_busy_indicator(self) -> None:
        self._pdf_busy_frame = (self._pdf_busy_frame + 1) % len(self._pdf_busy_frames)
        self.pdf_thumbnail_spinner.setText(self._pdf_busy_frames[self._pdf_busy_frame])

    def _set_pdf_thumbnail_busy(self, busy: bool) -> None:
        visible = bool(busy and self._fullscreen_mode and self._pdf_document is not None)
        self.pdf_thumbnail_busy.setVisible(visible)
        if visible:
            if not self._pdf_busy_timer.isActive():
                self._pdf_busy_frame = 0
                self.pdf_thumbnail_spinner.setText(self._pdf_busy_frames[0])
                self._pdf_busy_timer.start()
        else:
            self._pdf_busy_timer.stop()

    def _select_pdf_thumbnail_page(self, item: QListWidgetItem) -> None:
        page = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(page, int):
            self._pause_pdf_thumbnail_rendering()
            self._render_pdf_page(page)

    def _toggle_pdf_print_page(self, page: int, checked: bool) -> None:
        if checked:
            self._pdf_print_selection.add(page)
        else:
            self._pdf_print_selection.discard(page)

    def selected_pdf_pages(self) -> list[int]:
        return sorted(self._pdf_print_selection)

    def _update_pdf_print_checkbox_positions(self) -> None:
        if not hasattr(self, "_pdf_print_checkboxes"):
            return
        try:
            viewport = self.pdf_thumbnail_viewport
            viewport_rect = viewport.rect()
        except RuntimeError:
            return
        for page, checkbox in self._pdf_print_checkboxes.items():
            item = self.pdf_thumbnail_bar.item(page)
            if item is None:
                checkbox.hide()
                continue
            item_rect = self.pdf_thumbnail_bar.visualItemRect(item)
            visible = item_rect.intersects(viewport_rect)
            if visible:
                mapped = self.pdf_print_checkbox_column.mapFromGlobal(
                    viewport.mapToGlobal(item_rect.topLeft())
                )
                checkbox.move(
                    max(0, (self._pdf_print_checkbox_column_width - checkbox.sizeHint().width()) // 2),
                    mapped.y() + max(0, (item_rect.height() - checkbox.sizeHint().height()) // 2),
                )
                checkbox.show()
                checkbox.raise_()
            else:
                checkbox.hide()

    def _choose_pdf_pages_to_print(self) -> None:
        document = self._pdf_document
        if document is None:
            return
        dialog = QMessageBox(self.window)
        dialog.setObjectName("pdfPrintChoiceDialog")
        dialog.setWindowTitle(t("PDF-Seiten drucken"))
        dialog.setText(t("Was möchten Sie drucken?"))
        dialog.setStyleSheet(
            "QMessageBox#pdfPrintChoiceDialog { background: #f4f4f4; color: #171717; }"
            "QMessageBox#pdfPrintChoiceDialog QLabel { color: #171717; background: transparent; }"
            "QMessageBox#pdfPrintChoiceDialog QPushButton { color: #171717; background: white; border: 1px solid #666; min-width: 105px; padding: 6px 10px; }"
            "QMessageBox#pdfPrintChoiceDialog QPushButton:hover, QMessageBox#pdfPrintChoiceDialog QPushButton:focus { color: white; background: #245a9b; border-color: #163e6d; }"
        )
        current_button = dialog.addButton(
            t("Aktuelle Seite"), QMessageBox.ButtonRole.AcceptRole
        )
        all_button = dialog.addButton(
            t("Alle Seiten"), QMessageBox.ButtonRole.ActionRole
        )
        selection_button = dialog.addButton(
            t("Auswahl"), QMessageBox.ButtonRole.ActionRole
        )
        selection_button.setEnabled(bool(self._pdf_print_selection))
        dialog.addButton(t("Abbrechen"), QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is current_button:
            pages = [self._pdf_page]
        elif dialog.clickedButton() is all_button:
            pages = list(range(document.pageCount()))
        elif dialog.clickedButton() is selection_button:
            pages = self.selected_pdf_pages()
        else:
            return
        self._print_pdf_pages(pages)

    def _print_pdf_pages(self, pages: list[int]) -> None:
        document = self._pdf_document
        if document is None:
            return
        pages = sorted({page for page in pages if 0 <= page < document.pageCount()})
        if not pages:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        print_dialog = QPrintDialog(printer)
        print_dialog.setWindowTitle(t("PDF-Seiten drucken"))
        print_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        if run_without_application_stylesheet(print_dialog.exec) != QDialog.DialogCode.Accepted:
            return
        self.set_status(STATUS_BUSY, "Bitte warten …")
        painter = QPainter()
        try:
            if not painter.begin(printer):
                raise RuntimeError(t("Der Druckauftrag konnte nicht gestartet werden."))
            for output_index, page in enumerate(pages):
                if output_index and not printer.newPage():
                    raise RuntimeError(t("Eine neue Druckseite konnte nicht erzeugt werden."))
                printable_size = painter.viewport().size()
                image = render_pdf_page_for_printer(document, page, printable_size)
                if image.isNull():
                    raise RuntimeError(t("Die PDF-Seite konnte nicht gerendert werden"))
                target = image.size().scaled(
                    printable_size, Qt.AspectRatioMode.KeepAspectRatio
                )
                target_rect = QRectF(
                    (printable_size.width() - target.width()) / 2,
                    (printable_size.height() - target.height()) / 2,
                    target.width(), target.height(),
                )
                painter.drawImage(target_rect, image)
        except Exception as error:
            QMessageBox.critical(
                self.window,
                t("Drucken fehlgeschlagen"),
                t("Druckfehler: {detail}").format(detail=str(error)),
            )
        finally:
            if painter.isActive():
                painter.end()
            self.set_status(STATUS_READY)

    def _pause_pdf_thumbnail_rendering(self) -> None:
        """Give an explicit page selection priority over background previews."""
        self._pdf_thumbnail_suspended = True
        self._pdf_thumbnail_render_scheduled = False
        QTimer.singleShot(75, self._resume_pdf_thumbnail_rendering)

    def _resume_pdf_thumbnail_rendering(self) -> None:
        self._pdf_thumbnail_suspended = False
        self._schedule_visible_pdf_thumbnails()

    def _sync_pdf_thumbnail_selection(self) -> None:
        if not self.pdf_thumbnail_bar.isVisible() or self._pdf_document is None:
            return
        if not 0 <= self._pdf_page < self.pdf_thumbnail_bar.count():
            return
        item = self.pdf_thumbnail_bar.item(self._pdf_page)
        with QSignalBlocker(self.pdf_thumbnail_bar):
            self.pdf_thumbnail_bar.setCurrentItem(item)
        self.pdf_thumbnail_bar.scrollToItem(
            item, QAbstractItemView.ScrollHint.EnsureVisible
        )

    def _refresh_pdf_thumbnail_text(self) -> None:
        document = self._pdf_document
        if document is None:
            return
        page_count = document.pageCount()
        for page in range(min(page_count, self.pdf_thumbnail_bar.count())):
            item = self.pdf_thumbnail_bar.item(page)
            item.setText(t("Seite {page}").format(page=page + 1))
            checkbox = self._pdf_print_checkboxes.get(page)
            if checkbox is not None:
                checkbox.setAccessibleName(
                    t("Seite {page}").format(page=page + 1)
                )
        self.pdf_thumbnail_busy_label.setText(t("Wird geladen …"))
        self.pdf_print_button.setText(t("Drucken …"))

    def _position_pdf_fullscreen_navigation_hint(self) -> None:
        if not self.pdf_fullscreen_navigation_hint.isVisible():
            return
        viewport = self.image_scroll_area.viewport()
        margin = 20
        self.pdf_fullscreen_navigation_hint.move(
            max(margin, (viewport.width() - self.pdf_fullscreen_navigation_hint.width()) // 2),
            max(margin, viewport.height() - self.pdf_fullscreen_navigation_hint.height() - margin),
        )

    def _show_pdf_fullscreen_navigation_hint(self) -> None:
        if not self._fullscreen_mode or self._pdf_document is None:
            return
        self.pdf_fullscreen_navigation_hint.setText(
            t("↑ / ↓ – vorherige/nächste Seite")
        )
        self.pdf_fullscreen_navigation_hint.adjustSize()
        self.pdf_fullscreen_navigation_hint.show()
        self.pdf_fullscreen_navigation_hint.raise_()
        self._position_pdf_fullscreen_navigation_hint()
        self.pdf_fullscreen_navigation_hint_timer.start(
            PDF_FULLSCREEN_NAVIGATION_HINT_DURATION
        )

    def _hide_pdf_fullscreen_navigation_hint(self) -> None:
        self.pdf_fullscreen_navigation_hint_timer.stop()
        self.pdf_fullscreen_navigation_hint.hide()

    def _schedule_visible_pdf_thumbnails(self) -> None:
        if (
            not self.pdf_thumbnail_bar.isVisible()
            or self._pdf_document is None
            or self._pdf_thumbnail_render_scheduled
            or self._pdf_thumbnail_suspended
        ):
            return
        for index in range(self.pdf_thumbnail_bar.count()):
            item = self.pdf_thumbnail_bar.item(index)
            if self.pdf_thumbnail_bar.visualItemRect(item).intersects(
                self.pdf_thumbnail_bar.viewport().rect()
            ):
                self._pdf_thumbnail_pending.add(index)
        for index in range(max(0, self._pdf_page - 2), min(
            self.pdf_thumbnail_bar.count(), self._pdf_page + 3
        )):
            self._pdf_thumbnail_pending.add(index)
        # Continue lazily after visible pages and neighbours; scrolling must
        # not be required before later pages receive a real thumbnail.
        self._pdf_thumbnail_pending.update(
            range(self.pdf_thumbnail_bar.count())
        )
        self._pdf_thumbnail_render_scheduled = True
        QTimer.singleShot(0, self._render_next_pdf_thumbnail)

    def _render_next_pdf_thumbnail(self) -> None:
        self._pdf_thumbnail_render_scheduled = False
        document = self._pdf_thumbnail_document
        if (
            document is None
            or not self.pdf_thumbnail_bar.isVisible()
            or self._pdf_thumbnail_suspended
        ):
            return
        candidates = sorted(
            page for page in self._pdf_thumbnail_pending
            if page not in self._pdf_thumbnail_cache
        )
        self._pdf_thumbnail_pending.clear()
        if not candidates:
            return
        page = min(candidates, key=lambda value: abs(value - self._pdf_page))
        self._pdf_thumbnail_pending.update(candidate for candidate in candidates if candidate != page)
        image = render_pdf_page(document, page, QSize(132, 176))
        if not image.isNull():
            pixmap = QPixmap.fromImage(image)
            self._pdf_thumbnail_cache[page] = pixmap
            item = self.pdf_thumbnail_bar.item(page)
            if item is not None:
                item.setIcon(QIcon(pixmap))
        if self._pdf_thumbnail_pending:
            self._pdf_thumbnail_render_scheduled = True
            QTimer.singleShot(8, self._render_next_pdf_thumbnail)

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

        controls = QWidget(self.status_bar)
        controls.setObjectName("thumbnailSizeControls")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
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
        self.thumbnail_size_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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
        self.information_toggle_button = QToolButton(controls)
        self.information_toggle_button.setObjectName("informationToggleButton")
        self.information_toggle_button.setText("i")
        self.information_toggle_button.setToolTip("Bildinformationen (I)")
        self.information_toggle_button.setAccessibleName("Bildinformationen")
        self.information_toggle_button.setCheckable(True)
        self.information_toggle_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.information_toggle_button.clicked.connect(self._toggle_information_panel)
        controls_layout.addWidget(self.information_toggle_button)
        self.right_splitter.insertWidget(thumbnail_index, thumbnail_panel)

        self._install_bottom_control_bar(controls)

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

    def _install_bottom_control_bar(self, thumbnail_controls: QWidget) -> None:
        """Compose the persistent bottom bar from the existing controls."""

        self.status_bar.removeWidget(self.status_info_label)
        self.status_bar.removeWidget(self.status_zoom_label)
        self.status_bar.setFixedHeight(BOTTOM_CONTROL_BAR_HEIGHT)
        bottom_bar = QWidget(self.status_bar)
        bottom_bar.setObjectName("bottomControlBar")
        self.bottom_control_bar = bottom_bar
        layout = QHBoxLayout(bottom_bar)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(10)

        status_dot = QLabel("●", bottom_bar)
        status_dot.setObjectName("bottomStatusDot")
        self.bottom_status_dot = status_dot
        layout.addWidget(status_dot)
        self.status_info_label.setParent(bottom_bar)
        self.status_info_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.status_info_label.setMaximumWidth(260)
        layout.addWidget(self.status_info_label)
        layout.addWidget(thumbnail_controls)
        self.status_zoom_label.setParent(bottom_bar)
        layout.addWidget(self.status_zoom_label)

        separator = QWidget(bottom_bar)
        separator.setObjectName("bottomBarSeparator")
        separator.setFixedWidth(1)
        layout.addWidget(separator)
        layout.addStretch(1)
        self.previous_button.setFixedSize(36, 28)
        self.next_button.setFixedSize(36, 28)
        layout.addWidget(self.previous_button)
        layout.addWidget(self.file_name_label, 1)
        layout.addWidget(self.next_button)
        layout.addStretch(1)
        separator = QWidget(bottom_bar)
        separator.setObjectName("bottomBarSeparator")
        separator.setFixedWidth(1)
        layout.addWidget(separator)
        self.information_toggle_button.setFixedSize(24, 24)
        layout.addWidget(self.information_toggle_button)
        self.status_bar.addWidget(bottom_bar, 1)
        self._bottom_control_bar_active = False
        self.bottom_control_bar_hide_timer = QTimer(self)
        self.bottom_control_bar_hide_timer.setSingleShot(True)
        self.bottom_control_bar_hide_timer.timeout.connect(self._hide_bottom_control_bar)
        self.bottom_control_bar_start_timer = QTimer(self)
        self.bottom_control_bar_start_timer.setSingleShot(True)
        self.bottom_control_bar_start_timer.timeout.connect(
            self._schedule_bottom_control_bar_hide
        )
        self.bottom_control_bar_start_timer.start(BOTTOM_CONTROL_BAR_START_DELAY_MS)
        self.set_status(STATUS_READY)
        self._bottom_control_bar_watch_widgets = (
            self.window,
            self.window.centralWidget(),
            self.directory_tree.viewport(),
            self.thumbnail_list.viewport(),
            self.image_scroll_area.viewport(),
            bottom_bar,
            *bottom_bar.findChildren(QWidget),
        )
        for widget in self._bottom_control_bar_watch_widgets:
            widget.setMouseTracking(True)
            widget.installEventFilter(self)

    def _show_bottom_control_bar(self) -> None:
        self.bottom_control_bar_hide_timer.stop()
        self.status_bar.show()
        self.bottom_control_bar.show()

    def _hide_bottom_control_bar(self) -> None:
        if (
            getattr(self, "_status_state", STATUS_READY) != STATUS_READY
            or self._bottom_control_bar_active
            or self.bottom_control_bar.underMouse()
        ):
            return
        self.status_bar.hide()

    def _schedule_bottom_control_bar_hide(self) -> None:
        if (
            getattr(self, "_status_state", STATUS_READY) == STATUS_READY
            and self.status_bar.isVisible()
            and not self._bottom_control_bar_active
        ):
            self.bottom_control_bar_hide_timer.start(BOTTOM_CONTROL_BAR_HIDE_DELAY_MS)

    def _directory_loading_in_progress(self) -> bool:
        """Whether the current folder's scan or thumbnail work is unfinished."""
        if getattr(self, "_directory_loading_generation", None) != getattr(
            self, "_load_generation", None
        ):
            return False
        pending_images = getattr(self, "_pending_images", [])
        return (
            getattr(self, "_directory_iterator", None) is not None
            or getattr(self, "_prepare_index", 0) < len(pending_images)
            or getattr(self, "_next_job_index", 0) < len(pending_images)
            or getattr(self, "_active_jobs", 0) > 0
            or getattr(self, "_completed_jobs", 0) < len(pending_images)
        )

    def _status_with_directory_loading_guard(
        self, state: str, text: str | None
    ) -> tuple[str, str | None]:
        """Prevent unrelated image updates from marking folder loading ready."""
        if state == STATUS_READY and self._directory_loading_in_progress():
            return STATUS_BUSY, text or "Lade Vorschaubilder …"
        return state, text

    def set_status(self, state: str, text: str | None = None) -> None:
        """Set the shared bottom-bar status and its auto-hide behaviour."""

        if state not in STATUS_STATES:
            raise ValueError(f"Unbekannter Status: {state!r}")
        state, text = self._status_with_directory_loading_guard(state, text)
        defaults = {
            STATUS_READY: "Bereit",
            STATUS_BUSY: "Bitte warten …",
            STATUS_ERROR: "Fehler",
        }
        colors = {
            STATUS_READY: "#20c977",
            STATUS_BUSY: "#f59e0b",
            STATUS_ERROR: "#ef4444",
        }
        previous_state = getattr(self, "_status_state", None)
        self._status_state = state
        self._status_text_source = text or defaults[state]
        self._refresh_status_text()
        self.bottom_status_dot.setStyleSheet(
            f"color: {colors[state]}; font-size: 18px;"
        )
        self._update_bottom_control_bar_layout()
        if getattr(self, "_fullscreen_mode", False):
            self.bottom_control_bar_hide_timer.stop()
            self.bottom_control_bar_start_timer.stop()
            self.status_bar.hide()
            return
        if state == STATUS_READY and previous_state == STATUS_READY:
            if (
                self.status_bar.isVisible()
                and not self.bottom_control_bar_start_timer.isActive()
                and not self.bottom_control_bar_hide_timer.isActive()
            ):
                self.bottom_control_bar_start_timer.start(
                    BOTTOM_CONTROL_BAR_START_DELAY_MS
                )
            return
        self.bottom_control_bar_hide_timer.stop()
        if state == STATUS_READY:
            self._show_bottom_control_bar()
            self.bottom_control_bar_start_timer.start(BOTTOM_CONTROL_BAR_START_DELAY_MS)
        else:
            self.bottom_control_bar_start_timer.stop()
            self._show_bottom_control_bar()

    def _refresh_status_text(self) -> None:
        """Translate the current shared status without changing its state."""
        status_text = t(getattr(self, "_status_text_source", "Bereit"))
        self.status_info_label.setText(status_text)
        self.status_info_label.setToolTip(status_text)
        self._update_bottom_control_bar_layout()

    def _update_bottom_control_bar_layout(self) -> None:
        if not hasattr(self, "bottom_control_bar"):
            return
        status_width = self.status_info_label.fontMetrics().horizontalAdvance(
            self.status_info_label.text()
        )
        self.status_info_label.setMaximumWidth(
            max(140, min(320, self.window.width() // 3))
        )
        self.thumbnail_size_slider.setVisible(
            self.window.width() >= 680 and status_width < 190
        )

    def _update_bottom_control_bar_visibility(self, global_position=None) -> None:
        if getattr(self, "_fullscreen_mode", False) and self._pdf_document is not None:
            self._hide_normal_controls_for_pdf_fullscreen()
            return
        if global_position is None:
            global_position = QCursor.pos()
        local_position = self.window.mapFromGlobal(global_position)
        in_zone = (
            self.window.rect().contains(local_position)
            and local_position.y() >= self.window.height() - BOTTOM_CONTROL_BAR_ACTIVATION_ZONE_PX
        )
        self._bottom_control_bar_active = in_zone or self.bottom_control_bar.underMouse()
        if self._bottom_control_bar_active:
            self._show_bottom_control_bar()
        else:
            self._schedule_bottom_control_bar_hide()

    def _set_thumbnail_position(self, position: str) -> None:
        if position not in THUMBNAIL_POSITIONS:
            position = "top"
        self._thumbnail_position = position
        if position != "hidden":
            self._last_visible_thumbnail_position = position
            self.settings.setValue(LAST_VISIBLE_THUMBNAIL_POSITION_KEY, position)
        self.settings.setValue(THUMBNAIL_POSITION_KEY, position)
        self.settings.sync()
        self._apply_thumbnail_position(save=False)

    def _toggle_thumbnail_visibility(self) -> None:
        """Hide thumbnails or restore their most recently visible position."""
        if self._thumbnail_position == "hidden":
            self._set_thumbnail_position(self._last_visible_thumbnail_position)
        else:
            self._set_thumbnail_position("hidden")

    def _apply_thumbnail_position(self, *, save: bool) -> None:
        position = self._thumbnail_position
        if position not in THUMBNAIL_POSITIONS:
            position = "top"
            self._thumbnail_position = position
        vertical = position in {"left", "right"}
        self.right_splitter.setOrientation(
            Qt.Orientation.Horizontal if vertical else Qt.Orientation.Vertical
        )
        self.right_splitter.insertWidget(
            1 if position == "right" else 0, self.thumbnail_panel
        )
        self.thumbnail_list.setFlow(
            QListView.Flow.TopToBottom if vertical else QListView.Flow.LeftToRight
        )
        # A top thumbnail strip uses the available width for a regular grid;
        # side strips stay a single vertical column.
        self.thumbnail_list.setWrapping(not vertical)
        if vertical:
            self.thumbnail_panel.setFixedWidth(
                max(220, self._thumbnail_grid_size.width() + 30)
            )
        else:
            self.thumbnail_panel.setMinimumWidth(0)
            self.thumbnail_panel.setMaximumWidth(16777215)
        self.thumbnail_panel.setProperty("thumbnailPosition", position)
        # Dynamic properties are used by the system-theme stylesheet to give
        # only the upper thumbnail strip its subtle own surface and divider.
        self.thumbnail_panel.style().unpolish(self.thumbnail_panel)
        self.thumbnail_panel.style().polish(self.thumbnail_panel)
        self.thumbnail_panel.update()
        visible = position != "hidden" and not getattr(self, "_fullscreen_mode", False) and not getattr(self, "_pdf_preview_mode", False)
        self.thumbnail_panel.setVisible(visible)
        if hasattr(self, "thumbnail_position_actions"):
            self.thumbnail_position_actions[position].setChecked(True)
        self._sync_quick_switches()
        if save:
            self.settings.setValue(THUMBNAIL_POSITION_KEY, position)
            self.settings.sync()
        if hasattr(self, "_image_render_pending"):
            self._schedule_image_render()

    def _install_quick_switches(self) -> None:
        """Place compact stateful shortcuts in the menu bar's top-right corner."""
        quick_switches = QWidget(self.window.menuBar())
        quick_switches.setObjectName("quickSwitches")
        layout = QHBoxLayout(quick_switches)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        self.thumbnail_quick_toggle = QToolButton(quick_switches)
        self.thumbnail_quick_toggle.setObjectName("thumbnailQuickToggle")
        self.thumbnail_quick_toggle.setCheckable(True)
        self.thumbnail_quick_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.thumbnail_quick_toggle.clicked.connect(self._toggle_thumbnail_visibility)
        layout.addWidget(self.thumbnail_quick_toggle)

        self.details_quick_toggle = QToolButton(quick_switches)
        self.details_quick_toggle.setObjectName("detailsQuickToggle")
        self.details_quick_toggle.setCheckable(True)
        self.details_quick_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.details_quick_toggle.clicked.connect(self.information_toggle_action.trigger)
        layout.addWidget(self.details_quick_toggle)

        self.fullscreen_quick_toggle = QToolButton(quick_switches)
        self.fullscreen_quick_toggle.setObjectName("fullscreenQuickToggle")
        self.fullscreen_quick_toggle.setCheckable(True)
        self.fullscreen_quick_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.fullscreen_quick_toggle.clicked.connect(self.fullscreen_action.trigger)
        layout.addWidget(self.fullscreen_quick_toggle)

        self.window.menuBar().setCornerWidget(
            quick_switches, Qt.Corner.TopRightCorner
        )
        self._update_quick_switches_layout()
        self._sync_quick_switches()

    def _update_quick_switches_layout(self) -> None:
        """Reserve the size each translated quick-switch label actually needs."""
        if not hasattr(self, "thumbnail_quick_toggle"):
            return
        layout = self.thumbnail_quick_toggle.parentWidget().layout()
        if not isinstance(layout, QHBoxLayout):
            return
        for button in (
            self.thumbnail_quick_toggle,
            self.details_quick_toggle,
            self.fullscreen_quick_toggle,
        ):
            # The menu bar does not reliably relayout its corner widget after
            # a live language change.  Size every button explicitly so longer
            # labels such as Spanish "Pantalla completa" stay fully visible.
            button.setFixedWidth(button.fontMetrics().horizontalAdvance(button.text()) + 14)
        layout.activate()
        width = layout.sizeHint().width()
        quick_switches = self.thumbnail_quick_toggle.parentWidget()
        quick_switches.setFixedWidth(width)
        quick_switches.updateGeometry()

    def _sync_quick_switches(self) -> None:
        if not hasattr(self, "thumbnail_quick_toggle"):
            return
        self.thumbnail_quick_toggle.setChecked(self._thumbnail_position != "hidden")
        self.details_quick_toggle.setChecked(self.information_panel.isVisible())
        self.fullscreen_quick_toggle.setChecked(
            getattr(self, "_fullscreen_mode", False)
        )

    def _install_information_panel(self) -> None:
        """Add a hidden, fixed-width details pane beside the image viewport."""
        preview_layout = self.preview_panel.layout()
        if not isinstance(preview_layout, QVBoxLayout):
            return
        preview_layout.removeWidget(self.image_scroll_area)
        self.preview_content = QWidget(self.preview_panel)
        preview_content_layout = QHBoxLayout(self.preview_content)
        self.preview_content_layout = preview_content_layout
        preview_content_layout.setContentsMargins(0, 0, 0, 0)
        preview_content_layout.setSpacing(0)
        preview_content_layout.addWidget(self.image_scroll_area, 1)

        self.information_panel = QWidget(self.preview_content)
        self.information_panel.setObjectName("informationPanel")
        self.information_panel.setMinimumWidth(300)
        self.information_panel.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        panel_layout = QVBoxLayout(self.information_panel)
        panel_layout.setContentsMargins(10, 7, 8, 8)
        panel_layout.setSpacing(4)
        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 0, 0)
        title = QLabel("Bildinformationen", self.information_panel)
        title.setObjectName("informationPanelTitle")
        close_button = QToolButton(self.information_panel)
        close_button.setObjectName("informationCloseButton")
        close_button.setText("×")
        close_button.setToolTip("Bildinformationen schließen (I)")
        close_button.setAccessibleName(t("Bildinformationen schließen"))
        close_button.setAutoRaise(True)
        close_button.setFixedSize(20, 20)
        self.information_close_button = close_button
        close_button.clicked.connect(self._hide_information_panel)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(close_button)
        panel_layout.addLayout(header)

        self._install_manual_metadata_editor(panel_layout)

        self.information_scroll_area = QScrollArea(self.information_panel)
        self.information_scroll_area.setWidgetResizable(True)
        self.information_scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.information_scroll_area.viewport().installEventFilter(self)
        self.information_content = QWidget(self.information_scroll_area)
        self.information_content_layout = QVBoxLayout(self.information_content)
        self.information_content_layout.setContentsMargins(2, 0, 2, 2)
        self.information_content_layout.setSpacing(5)
        self.information_content_layout.addStretch(1)
        self.information_scroll_area.setWidget(self.information_content)
        panel_layout.addWidget(self.information_scroll_area, 1)
        preview_content_layout.addWidget(self.information_panel)
        preview_layout.insertWidget(0, self.preview_content, 1)
        self.information_panel.hide()

    def _install_manual_metadata_editor(self, panel_layout: QVBoxLayout) -> None:
        """Create the pinned editor; persistence is intentionally deferred."""
        section = QWidget(self.information_panel)
        section.setObjectName("manualMetadataSection")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 1, 0, 2)
        layout.setSpacing(2)
        self.manual_metadata_section = section
        self.manual_metadata_fields: dict[str, QLineEdit | QTextEdit] = {}
        self.manual_metadata_labels: dict[str, QLabel] = {}
        self.manual_metadata_placeholders: dict[str, str] = {}
        specifications = (
            ("comment", "Bemerkungen", "Bemerkung hinzufügen …", True),
            ("people", "Personen", "Personen hinzufügen …", False),
            ("place", "Aufnahmeort", "Ort hinzufügen …", False),
            ("gps", "GPS", "GPS-Koordinaten hinzufügen …", False),
        )
        for key, label_text, placeholder, multiline in specifications:
            label = QLabel(t(label_text), section)
            label.setObjectName("manualMetadataLabel")
            self.manual_metadata_labels[key] = label
            self.manual_metadata_placeholders[key] = placeholder
            if multiline:
                field = QTextEdit(section)
                field.setFixedHeight(40)
                field.setAcceptRichText(False)
            else:
                field = QLineEdit(section)
            field.setObjectName("manualMetadataField")
            field.setPlaceholderText(t(placeholder))
            field.setAccessibleName(t(label_text))
            # These are explicit because the editor lives beside a scroll area
            # with several event filters.  JPEG fields must remain genuine text
            # inputs, not merely visually enabled controls.
            field.setReadOnly(False)
            field.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            field.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self.manual_metadata_fields[key] = field
            if isinstance(field, QTextEdit):
                field.textChanged.connect(self._mark_manual_metadata_dirty)
            else:
                field.textChanged.connect(self._mark_manual_metadata_dirty)
            if multiline:
                layout.addWidget(label)
                layout.addWidget(field)
            else:
                row = QHBoxLayout()
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(7)
                label.setMinimumWidth(74)
                row.addWidget(label)
                row.addWidget(field, 1)
                layout.addLayout(row)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 3, 0, 0)
        self.manual_metadata_reset_button = QPushButton(t("Zurücksetzen"), section)
        self.manual_metadata_reset_button.setMaximumHeight(24)
        self.manual_metadata_reset_button.clicked.connect(self.clear_manual_metadata_fields)
        self.manual_metadata_save_button = QPushButton(t("Speichern"), section)
        self.manual_metadata_save_button.setMaximumHeight(24)
        self.manual_metadata_save_button.clicked.connect(self._capture_manual_metadata)
        buttons.addWidget(self.manual_metadata_reset_button)
        buttons.addWidget(self.manual_metadata_save_button)
        layout.addLayout(buttons)
        panel_layout.addWidget(section)
        separator = QFrame(self.information_panel)
        separator.setObjectName("manualMetadataSeparator")
        separator.setFrameShape(QFrame.Shape.HLine)
        panel_layout.addWidget(separator)
        self._install_manual_metadata_completers()

    def _install_manual_metadata_completers(self) -> None:
        self._people_completer = PersonCompleter([], self.information_panel)
        self._people_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._people_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        people = self.manual_metadata_fields["people"]
        assert isinstance(people, QLineEdit)
        people.setCompleter(self._people_completer)
        people.textEdited.connect(self._update_people_completions)
        self._place_completer = QCompleter([], self.information_panel)
        self._place_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._place_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        place = self.manual_metadata_fields["place"]
        assert isinstance(place, QLineEdit)
        place.setCompleter(self._place_completer)
        place.textEdited.connect(lambda text: self._place_completer.setModel(QStringListModel(suggest_places(text), self._place_completer)))

    def _update_people_completions(self, text: str) -> None:
        prefix = text.rsplit(",", 1)[-1].strip()
        self._people_completer.setModel(QStringListModel(suggest_people(prefix), self._people_completer))

    def collect_manual_metadata_from_fields(self) -> dict[str, str]:
        """Return editor values for a future metadata persistence layer."""
        return {
            key: field.toPlainText() if isinstance(field, QTextEdit) else field.text()
            for key, field in self.manual_metadata_fields.items()
        }

    def load_manual_metadata_into_fields(self, metadata: dict[str, str] | None = None) -> None:
        """Load a metadata mapping into the pinned editor without file access."""
        self.manual_metadata = {"comment": "", "people": "", "place": "", "gps": ""}
        self.manual_metadata.update(metadata or {})
        for key, field in self.manual_metadata_fields.items():
            value = self.manual_metadata[key]
            if isinstance(field, QTextEdit):
                field.setPlainText(value)
            else:
                field.setText(value)
        self.manual_metadata_dirty = False
        self.manual_metadata_save_button.setEnabled(False)

    def clear_manual_metadata_fields(self) -> None:
        """Discard unsaved editor values for the current image."""
        self.load_manual_metadata_into_fields(self.manual_metadata)

    def set_manual_metadata_editable(self, editable: bool) -> None:
        for field in self.manual_metadata_fields.values():
            field.setEnabled(editable)
            field.setReadOnly(not editable)
            field.setFocusPolicy(
                Qt.FocusPolicy.StrongFocus if editable else Qt.FocusPolicy.NoFocus
            )
        self.manual_metadata_save_button.setEnabled(editable and self.manual_metadata_dirty)
        self.manual_metadata_reset_button.setEnabled(editable)

    def _mark_manual_metadata_dirty(self) -> None:
        if self._manual_metadata_path is None:
            return
        self.manual_metadata_dirty = True
        self.manual_metadata_save_button.setEnabled(True)

    def _capture_manual_metadata(self) -> None:
        """Validate and persist standardized JPEG metadata through ExifTool."""
        path = self.current_image
        if path is None or not path.is_file() or path.suffix.lower() not in JPEG_EXTENSIONS:
            return
        metadata = self.collect_manual_metadata_from_fields()
        try:
            self.set_status(STATUS_BUSY, t("Bildinformationen werden gespeichert …"))
            write_manual_image_metadata(path, metadata)
            saved = read_manual_image_metadata(path)
        except (OSError, RuntimeError, ValueError) as error:
            self.set_status(STATUS_ERROR, str(error))
            QMessageBox.warning(self.window, t("Bildinformationen"), str(error))
            return
        self.load_manual_metadata_into_fields(saved)
        try:
            for person in _manual_metadata_people(metadata.get("people", "")):
                upsert_person(person)
            latitude_longitude = _manual_metadata_gps(metadata.get("gps", ""))
            if metadata.get("place", "").strip():
                upsert_place(metadata["place"], *(latitude_longitude or (None, None)))
        except Exception:
            logging.exception("Could not update local metadata suggestions")
        try:
            update_indexed_image(path, saved)
        except Exception:
            logging.exception("JPEG metadata was saved, but its image-index entry could not be updated")
        self.set_status(STATUS_READY)

    def _refresh_manual_metadata_editor(self, path: Path | None) -> None:
        if path != self._manual_metadata_path:
            self._manual_metadata_path = path
            try:
                self.load_manual_metadata_into_fields(read_manual_image_metadata(path) if path and path.is_file() else None)
            except (OSError, RuntimeError, json.JSONDecodeError):
                self.load_manual_metadata_into_fields()
        editable = path is not None and path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}
        self.set_manual_metadata_editable(editable)

    def _retranslate_manual_metadata_editor(self) -> None:
        for key, label in self.manual_metadata_labels.items():
            source = {"comment": "Bemerkungen", "people": "Personen", "place": "Aufnahmeort", "gps": "GPS"}[key]
            label.setText(t(source))
            field = self.manual_metadata_fields[key]
            field.setPlaceholderText(t(self.manual_metadata_placeholders[key]))
            field.setAccessibleName(t(source))
        self.manual_metadata_reset_button.setText(t("Zurücksetzen"))
        self.manual_metadata_save_button.setText(t("Speichern"))

    def _confirm_manual_metadata_navigation(self) -> bool:
        if not self.manual_metadata_dirty:
            return True
        dialog = QMessageBox(self.window)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle(t("Bildinformationen"))
        dialog.setText(t("Die Bildinformationen wurden geändert."))
        save = dialog.addButton(t("Speichern"), QMessageBox.ButtonRole.AcceptRole)
        discard = dialog.addButton(t("Verwerfen"), QMessageBox.ButtonRole.DestructiveRole)
        dialog.addButton(t("Abbrechen"), QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is save:
            self._capture_manual_metadata()
            return not self.manual_metadata_dirty
        if dialog.clickedButton() is discard:
            self.clear_manual_metadata_fields()
            return True
        return False

    def _clear_information_content(self) -> None:
        while self.information_content_layout.count() > 1:
            item = self.information_content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _configure_information_form(self, form: QFormLayout) -> None:
        """Let metadata labels and values share a narrow panel gracefully."""
        form.setContentsMargins(0, 6, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(4)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

    def _update_information_column_widths(self) -> None:
        """Keep labels useful without starving the flexible value column."""
        if not hasattr(self, "information_scroll_area"):
            return
        available_width = self.information_scroll_area.viewport().width()
        label_width = max(96, min(180, round(available_width * 0.42)))
        for label in self.information_content.findChildren(
            QLabel, "informationFieldLabel"
        ):
            label.setMaximumWidth(label_width)

    def _update_information_panel(self) -> None:
        if not self.information_panel.isVisible():
            return
        self._refresh_manual_metadata_editor(self.current_image)
        self._clear_information_content()
        path = self.current_image
        if path is None or not path.is_file():
            empty = QLabel(t("Kein Bild ausgewählt"), self.information_content)
            empty.setObjectName("informationEmptyLabel")
            self.information_content_layout.insertWidget(0, empty)
            return
        for title, fields in build_information_metadata(path).items():
            group = QGroupBox(title, self.information_content)
            group.setObjectName("informationSection")
            form = QFormLayout(group)
            self._configure_information_form(form)
            for label_text, value_text in fields.items():
                label = QLabel(f"{label_text}:", group)
                label.setObjectName("informationFieldLabel")
                label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                label.setWordWrap(True)
                label.setSizePolicy(
                    QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
                )
                value = QLabel(value_text, group)
                value.setObjectName("informationValueLabel")
                value.setWordWrap(True)
                value.setToolTip(value_text)
                value.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
                )
                value.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
                form.addRow(label, value)
            self.information_content_layout.insertWidget(
                self.information_content_layout.count() - 1, group
            )
        self._update_information_column_widths()
        self.all_metadata_toggle = QToolButton(self.information_content)
        self.all_metadata_toggle.setObjectName("allMetadataToggle")
        self.all_metadata_toggle.setCheckable(True)
        self.all_metadata_toggle.setChecked(self._all_metadata_expanded)
        self.all_metadata_toggle.toggled.connect(self._toggle_all_metadata)
        self.information_content_layout.insertWidget(
            self.information_content_layout.count() - 1, self.all_metadata_toggle
        )
        self.all_metadata_content = QWidget(self.information_content)
        self.all_metadata_layout = QVBoxLayout(self.all_metadata_content)
        self.all_metadata_layout.setContentsMargins(0, 0, 0, 0)
        self.all_metadata_layout.setSpacing(8)
        self.information_content_layout.insertWidget(
            self.information_content_layout.count() - 1, self.all_metadata_content
        )
        self._refresh_all_metadata_toggle()
        if self._all_metadata_expanded:
            self._populate_all_metadata()
        self.information_scroll_area.verticalScrollBar().setValue(0)

    def _refresh_all_metadata_toggle(self) -> None:
        self.all_metadata_toggle.setText(
            ("▼ " if self._all_metadata_expanded else "▶ ") + t("Alle Metadaten")
        )
        self.all_metadata_content.setVisible(self._all_metadata_expanded)

    def _toggle_all_metadata(self, expanded: bool) -> None:
        self._all_metadata_expanded = expanded
        self._refresh_all_metadata_toggle()
        if expanded:
            self._populate_all_metadata()

    def _populate_all_metadata(self) -> None:
        while self.all_metadata_layout.count():
            item = self.all_metadata_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        path = self.current_image
        fields_by_group: dict[str, dict[str, str]] = {}
        if path is not None and path.is_file() and path.suffix.lower() not in PDF_EXTENSIONS:
            try:
                info = path.stat()
                key = (str(path.resolve(strict=False)), info.st_mtime_ns, info.st_size)
                fields_by_group = self._all_metadata_cache.get(key, {})
                if not fields_by_group:
                    fields_by_group = build_all_image_metadata(path)
                    self._all_metadata_cache[key] = fields_by_group
            except OSError:
                pass
        if not fields_by_group:
            empty = QLabel(t("Keine weiteren Metadaten vorhanden"), self.all_metadata_content)
            empty.setObjectName("informationEmptyLabel")
            empty.setWordWrap(True)
            self.all_metadata_layout.addWidget(empty)
            return
        for title, fields in fields_by_group.items():
            group = QGroupBox(title, self.all_metadata_content)
            group.setObjectName("informationSection")
            form = QFormLayout(group)
            self._configure_information_form(form)
            for tag, value_text in fields.items():
                label = QLabel(f"{tag}:", group)
                label.setObjectName("informationFieldLabel")
                label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                label.setWordWrap(True)
                label.setSizePolicy(
                    QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
                )
                value = QLabel(value_text, group)
                value.setObjectName("informationValueLabel")
                value.setWordWrap(True)
                value.setToolTip(value_text)
                value.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
                )
                value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                form.addRow(label, value)
            self.all_metadata_layout.addWidget(group)
        self._update_information_column_widths()

    def _show_information_panel(self) -> None:
        self.information_panel.show()
        self._update_information_panel()
        self.information_toggle_button.setChecked(True)
        self._sync_quick_switches()
        self._schedule_image_render()

    def _hide_information_panel(self) -> None:
        self.information_panel.hide()
        self.information_toggle_button.setChecked(False)
        self._sync_quick_switches()
        self._schedule_image_render()

    def _toggle_information_panel(self) -> None:
        if self.information_panel.isVisible():
            self._hide_information_panel()
        else:
            self._show_information_panel()

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
        self.directory_tree.setProperty("showHiddenDirectories", checked)
        self.directory_tree_indicator_delegate.invalidate()
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

    def _invalidate_directory_indicator(self, index: QModelIndex) -> None:
        if not index.isValid():
            self.directory_tree_indicator_delegate.invalidate()
            return
        self.directory_tree_indicator_delegate.invalidate(
            self.directory_model.filePath(index)
        )

    def _start_directory(self) -> Path:
        saved_value = self.settings.value(LAST_DIRECTORY_KEY, "", type=str)
        if saved_value:
            saved_directory = Path(saved_value).expanduser()
            if saved_directory.is_dir():
                return saved_directory
        return START_DIRECTORY

    def _create_application_menus(self) -> None:
        self.file_menu = self.window.menuBar().addMenu(t("Datei"))
        self.rename_image_action = QAction(t("Umbenennen …"), self.window)
        self.rename_image_action.setShortcut(QKeySequence("F2"))
        self.rename_image_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.rename_image_action.triggered.connect(
            lambda: self._rename_image(self._rename_context_path)
        )
        self.export_resized_action = QAction(
            t("Ausgewählte Bilder verkleinert exportieren …"), self.window
        )
        self.export_resized_action.triggered.connect(
            lambda: self._show_resized_export_dialog(self._export_context_path)
        )
        self.file_menu.addAction(self.export_resized_action)
        self.print_action = QAction(t("Drucken …"), self.window)
        self.print_action.setShortcut(QKeySequence.StandardKey.Print)
        self.print_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.print_action.triggered.connect(self._show_wysiwyg_print_dialog)
        self.file_menu.addAction(self.print_action)
        self.multi_print_action = QAction(t("Mehrere Bilder drucken …"), self.window)
        self.multi_print_action.triggered.connect(self._show_multi_wysiwyg_print_dialog)
        self.file_menu.addAction(self.multi_print_action)
        self.file_menu.addSeparator()
        self.window.addAction(self.rename_image_action)

        self.quit_action = QAction(t("Beenden"), self.window)
        self.quit_action.setShortcut(QKeySequence("Alt+F4"))
        self.quit_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.quit_action.triggered.connect(self.window.close)
        self.file_menu.addAction(self.quit_action)

        self.edit_menu = self.window.menuBar().addMenu(t("Bearbeiten"))
        self.select_all_action = QAction(t("Alles auswählen"), self.window)
        self.select_all_action.setShortcut(QKeySequence("Ctrl+A"))
        self.select_all_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.select_all_action.triggered.connect(self._select_all_images)
        self.edit_menu.addAction(self.select_all_action)

        self.copy_image_action = QAction(t("Kopieren"), self.window)
        self.copy_image_action.setShortcut(QKeySequence("Ctrl+C"))
        self.copy_image_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.copy_image_action.triggered.connect(
            lambda: self._put_current_image_on_clipboard("copy")
        )
        self.edit_menu.addAction(self.copy_image_action)

        self.cut_image_action = QAction(t("Ausschneiden"), self.window)
        self.cut_image_action.setShortcut(QKeySequence("Ctrl+X"))
        self.cut_image_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.cut_image_action.triggered.connect(
            lambda: self._put_current_image_on_clipboard("cut")
        )
        self.edit_menu.addAction(self.cut_image_action)

        self.paste_image_action = QAction(t("Einfügen"), self.window)
        self.paste_image_action.setShortcut(QKeySequence("Ctrl+V"))
        self.paste_image_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.paste_image_action.triggered.connect(self._paste_image_from_clipboard)
        self.edit_menu.addAction(self.paste_image_action)
        self.edit_menu.addSeparator()
        self.edit_menu.addAction(self.rename_image_action)
        for action in (
            self.select_all_action,
            self.copy_image_action,
            self.cut_image_action,
            self.paste_image_action,
        ):
            self.window.addAction(action)

        self.trash_image_action = QAction(
            t("In den Papierkorb verschieben"), self.window
        )
        self.trash_image_action.setShortcut(QKeySequence("Delete"))
        self.trash_image_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.trash_image_action.triggered.connect(self._move_current_image_to_trash)
        self.window.addAction(self.trash_image_action)
        self.edit_menu.addAction(self.trash_image_action)

        self.show_in_file_manager_action = QAction(
            t("Im Dateimanager anzeigen"), self.window
        )
        self.show_in_file_manager_action.triggered.connect(
            lambda: self.show_in_file_manager(
                self._file_manager_context_path
            )
        )
        self.edit_menu.addAction(self.show_in_file_manager_action)

        display_rotation_tooltip = (
            "Dreht nur die Anzeige. Die Originaldatei bleibt unverändert."
        )
        self.rotate_left_action = QAction(t("Nach links drehen"), self.window)
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

        self.rotate_right_action = QAction(t("Nach rechts drehen"), self.window)
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
            t("Drehung zurücksetzen"), self.window
        )
        self.reset_rotation_action.setToolTip(display_rotation_tooltip)
        self.reset_rotation_action.triggered.connect(
            lambda: self._reset_current_rotation(self._rotation_context_path)
        )

        self.edit_menu.addSeparator()
        for action in (
            self.rotate_left_action,
            self.rotate_right_action,
            self.reset_rotation_action,
        ):
            self.edit_menu.addAction(action)
            self.window.addAction(action)

        self.edit_menu.addSeparator()
        self.save_rotated_copy_action = QAction(
            t("Gedrehte Kopie speichern …"), self.window
        )
        self.save_rotated_copy_action.triggered.connect(
            lambda: self._save_rotated_copy(self._rotation_context_path)
        )
        self.edit_menu.addAction(self.save_rotated_copy_action)

        self.save_rotation_to_original_action = QAction(
            t("Drehung im Original speichern …"), self.window
        )
        self.save_rotation_to_original_action.triggered.connect(
            lambda: self._save_rotation_to_original(
                self._rotation_context_path
            )
        )
        self.edit_menu.addAction(self.save_rotation_to_original_action)

        self.compare_images_action = QAction(
            t("Bilder vergleichen …"), self.window
        )
        self.compare_images_action.triggered.connect(self._compare_selected_images)
        image_placeholder_action = QAction(t("Weitere Bildfunktionen folgen …"), self.window)
        image_placeholder_action.setEnabled(False)
        self.edit_menu.addAction(image_placeholder_action)

        self.view_menu = self.window.menuBar().addMenu(t("Ansicht"))
        self.fullscreen_action = QAction(t("Vollbild"), self.window)
        self.fullscreen_action.setCheckable(True)
        self.fullscreen_action.setShortcut(QKeySequence("F11"))
        self.fullscreen_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.fullscreen_action.triggered.connect(self._toggle_fullscreen)
        self.view_menu.addAction(self.fullscreen_action)

        self.leave_pdf_preview_action = QAction("PDF-Vorschau verlassen", self.window)
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
            t("Versteckte Dateien und Ordner anzeigen"), self.window
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

        self.language_menu = self.view_menu.addMenu(t("Sprache"))
        self.language_action_group = QActionGroup(self.window)
        self.language_action_group.setExclusive(True)
        self.language_actions: dict[str, QAction] = {}
        for code, label in LANGUAGES.items():
            action = QAction(label, self.window)
            action.setCheckable(True)
            action.setChecked(code == self.language_manager.code)
            action.triggered.connect(lambda checked=False, value=code: self._set_language(value))
            self.language_action_group.addAction(action)
            self.language_menu.addAction(action)
            self.language_actions[code] = action

        self.view_menu.addSeparator()
        self.fit_image_action = QAction(t("Bild einpassen"), self.window)
        self.fit_image_action.setShortcut(QKeySequence("0"))
        self.fit_image_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.fit_image_action.triggered.connect(self._fit_image_to_window)
        self.view_menu.addAction(self.fit_image_action)

        self.actual_size_action = QAction(t("Originalgröße"), self.window)
        self.actual_size_action.setShortcut(QKeySequence("1"))
        self.actual_size_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.actual_size_action.triggered.connect(self._show_image_at_actual_size)
        self.view_menu.addAction(self.actual_size_action)

        self.view_menu.addSeparator()
        self.thumbnail_size_action = QAction(
            t("Größe der Vorschaubilder …"), self.window
        )
        self.thumbnail_size_action.triggered.connect(
            self._show_thumbnail_size_dialog
        )
        self.view_menu.addAction(self.thumbnail_size_action)

        self.thumbnail_position_menu = self.view_menu.addMenu(t("Vorschaubilder"))
        self.thumbnail_position_action_group = QActionGroup(self.window)
        self.thumbnail_position_action_group.setExclusive(True)
        self.thumbnail_position_actions: dict[str, QAction] = {}
        for position, label in (
            ("top", "Oben"), ("left", "Links"),
            ("right", "Rechts"), ("hidden", "Ausblenden"),
        ):
            action = QAction(t(label), self.window)
            action.setCheckable(True)
            action.setChecked(position == self._thumbnail_position)
            action.triggered.connect(
                lambda checked=False, value=position: self._set_thumbnail_position(value)
            )
            self.thumbnail_position_action_group.addAction(action)
            self.thumbnail_position_menu.addAction(action)
            self.thumbnail_position_actions[position] = action

        self.increase_thumbnail_size_action = QAction(
            t("Vorschaubilder vergrößern"), self.window
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
            t("Vorschaubilder verkleinern"), self.window
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
            t("Vorschaubildgröße zurücksetzen"), self.window
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
        self.sort_menu = self.view_menu.addMenu(t("Sortieren nach"))
        self.sort_criterion_action_group = QActionGroup(self.window)
        self.sort_criterion_action_group.setExclusive(True)
        for criterion, label in (
            ("name", "Dateiname"),
            ("recording_date", "Aufnahmedatum"),
            ("modified", t("Änderungsdatum")),
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
        self.color_scheme_menu = self.view_menu.addMenu(t("Farbschema"))
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

        self.go_to_menu = self.window.menuBar().addMenu(t("Gehe zu"))
        self.navigation_menu = self.go_to_menu
        self.previous_folder_action = QAction(t("Vorheriger Ordner"), self.window)
        self.previous_folder_action.setShortcut(QKeySequence("Alt+Left"))
        self.previous_folder_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.previous_folder_action.setToolTip("Vorheriger Ordner (Alt+Links)")
        self.previous_folder_action.triggered.connect(self._go_to_previous_folder)
        self.navigation_menu.addAction(self.previous_folder_action)

        self.next_folder_action = QAction(t("Nächster Ordner"), self.window)
        self.next_folder_action.setShortcut(QKeySequence("Alt+Right"))
        self.next_folder_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.next_folder_action.setToolTip("Nächster Ordner (Alt+Rechts)")
        self.next_folder_action.triggered.connect(self._go_to_next_folder)
        self.navigation_menu.addAction(self.next_folder_action)

        self.parent_folder_action = QAction(t("Übergeordneter Ordner"), self.window)
        self.parent_folder_action.setShortcut(QKeySequence("Alt+Up"))
        self.parent_folder_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.parent_folder_action.setToolTip("Übergeordneter Ordner (Alt+Oben)")
        self.parent_folder_action.triggered.connect(self._go_to_parent_folder)
        self.navigation_menu.addAction(self.parent_folder_action)
        self.navigation_menu.addSeparator()

        self.first_image_action = QAction(t("Erstes Bild"), self.window)
        self.first_image_action.setShortcut(QKeySequence("Home"))
        self.first_image_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.first_image_action.triggered.connect(
            lambda: self._select_slideshow_endpoint(False)
            if self._slideshow_running
            else self._select_image(0)
        )
        self.navigation_menu.addAction(self.first_image_action)

        self.previous_image_action = QAction(t("Vorheriges Bild"), self.window)
        self.previous_image_action.setShortcut(QKeySequence("Left"))
        self.previous_image_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.previous_image_action.triggered.connect(
            lambda: self._select_relative_image(-1)
        )
        self.navigation_menu.addAction(self.previous_image_action)

        self.next_image_action = QAction(t("Nächstes Bild"), self.window)
        self.next_image_action.setShortcut(QKeySequence("Right"))
        self.next_image_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.next_image_action.triggered.connect(lambda: self._select_relative_image(1))
        self.navigation_menu.addAction(self.next_image_action)

        self.last_image_action = QAction(t("Letztes Bild"), self.window)
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

        self.tools_menu = self.window.menuBar().addMenu(t("Werkzeuge"))
        self.tools_menu.addAction(self.compare_images_action)
        self.tools_menu.addSeparator()
        self.find_duplicates_action = QAction(
            t("Doppelte Bilder finden …"), self.window
        )
        self.find_duplicates_action.triggered.connect(
            self._show_duplicate_finder
        )
        self.tools_menu.addAction(self.find_duplicates_action)
        self.tools_menu.addSeparator()
        self.index_current_folder_action = QAction(t("Diesen Ordner in die Bildsuche aufnehmen …"), self.window)
        self.index_current_folder_action.setObjectName("indexCurrentFolderAction")
        self.index_current_folder_action.triggered.connect(self._show_index_current_folder_dialog)
        self.search_images_action = QAction(t("Bilder suchen …"), self.window)
        self.search_images_action.setObjectName("searchImagesAction")
        self.search_images_action.triggered.connect(self._show_image_search_dialog)
        self.manage_image_index_action = QAction(t("Bildindex verwalten …"), self.window)
        self.manage_image_index_action.setObjectName("manageImageIndexAction")
        self.manage_image_index_action.triggered.connect(self._show_image_index_manager)
        self.end_image_search_action = QAction(t("Suche beenden"), self.window)
        self.end_image_search_action.triggered.connect(self._end_image_search)
        self.end_image_search_action.setVisible(False)
        self.tools_menu.addActions((self.index_current_folder_action, self.search_images_action, self.manage_image_index_action, self.end_image_search_action))

        self.help_menu = self.window.menuBar().addMenu(t("Hilfe"))
        self.controls_help_action = QAction(
            t("Bedienung und Tastenkürzel"), self.window
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

    def _show_index_current_folder_dialog(self) -> None:
        folder = self.current_directory
        if folder is None or not folder.is_dir():
            QMessageBox.information(self.window, t("Bildindex"), t("Bitte wähle zuerst einen Ordner aus."))
            return
        dialog = QDialog(self.window)
        dialog.setWindowTitle(t("Diesen Ordner in die Bildsuche aufnehmen …"))
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"{t('Ordner')}:\n{folder}"))
        recursive = QCheckBox(t("Unterordner einschließen"), dialog)
        layout.addWidget(recursive)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, dialog)
        index_button = buttons.addButton(t("Indexieren"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(dialog.reject); index_button.clicked.connect(dialog.accept)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        self._start_image_indexing([(folder, recursive.isChecked())])

    def _start_image_indexing(self, folders: list[tuple[Path, bool]]) -> None:
        if not folders or getattr(self, "_image_index_task", None) is not None:
            return
        self.set_status(STATUS_BUSY, t("Bildindex wird aktualisiert …"))
        progress = QProgressDialog(t("Bildindex wird aktualisiert …"), t("Abbrechen"), 0, 0, self.window)
        progress.setWindowTitle(t("Bildindex")); progress.setWindowModality(Qt.WindowModality.NonModal)
        progress.setMinimumDuration(0); progress.setAutoClose(False); progress.setAutoReset(False)
        task = ImageIndexTask(folders)
        self._image_index_task, self._image_index_progress = task, progress
        task.signals.progress.connect(self._image_index_progress_changed)
        task.signals.finished.connect(self._image_index_finished)
        task.signals.failed.connect(self._image_index_failed)
        progress.canceled.connect(task.cancel)
        progress.show(); self.thread_pool.start(task)

    def _image_index_progress_changed(self, current: int, total: int) -> None:
        progress = self._image_index_progress
        progress.setRange(0, max(0, total)); progress.setValue(current)
        progress.setLabelText(t("{current} von {total} Bildern").format(current=current, total=total))

    def _image_index_finished(self, count: int, cancelled: bool) -> None:
        self._image_index_progress.close()
        self._image_index_task = self._image_index_progress = None
        self.set_status(STATUS_READY, t("Indexierung abgebrochen") if cancelled else t("{count} Bilder indexiert").format(count=count))

    def _image_index_failed(self, detail: str) -> None:
        logging.error("Image indexing failed: %s", detail)
        self._image_index_progress.close()
        self._image_index_task = self._image_index_progress = None
        self.set_status(STATUS_ERROR, detail)

    def _show_image_index_manager(self) -> None:
        dialog = QDialog(self.window); dialog.setWindowTitle(t("Bildindex verwalten …"))
        dialog.setObjectName("imageIndexManagerDialog")
        layout = QVBoxLayout(dialog); tree = QTreeWidget(dialog)
        tree.setObjectName("indexedFoldersTree")
        tree.setColumnCount(3); tree.setHeaderLabels((t("Ordner"), t("Unterordner"), t("Letzter Scan")))
        folder_entries = indexed_folders()
        for folder, recursive, last_scan in folder_entries:
            item = QTreeWidgetItem((str(folder), t("Ja") if recursive else t("Nein"), last_scan))
            item.setData(0, Qt.ItemDataRole.UserRole, (str(folder), recursive)); tree.addTopLevelItem(item)
        if not folder_entries:
            empty = QTreeWidgetItem((t("Noch keine Ordner im Bildindex."), "", ""))
            empty.setFlags(Qt.ItemFlag.NoItemFlags); tree.addTopLevelItem(empty)
        layout.addWidget(tree)
        row = QHBoxLayout(); update = QPushButton(t("Aktualisieren"), dialog)
        update_all = QPushButton(t("Alle aktualisieren"), dialog)
        remove = QPushButton(t("Aus Index entfernen"), dialog); close = QPushButton(t("Schließen"), dialog)
        update.setObjectName("updateIndexedFolderButton")
        update_all.setObjectName("updateAllIndexedFoldersButton")
        remove.setObjectName("removeIndexedFolderButton")
        close.setObjectName("closeImageIndexManagerButton")
        for button in (update, update_all, remove, close): row.addWidget(button)
        layout.addLayout(row); close.clicked.connect(dialog.accept)
        def selected_folder():
            item = tree.currentItem(); return item.data(0, Qt.ItemDataRole.UserRole) if item else None
        def refresh_buttons():
            selected = selected_folder() is not None
            update.setEnabled(selected); remove.setEnabled(selected)
            update_all.setEnabled(bool(folder_entries))
        tree.currentItemChanged.connect(lambda *_: refresh_buttons())
        if folder_entries: tree.setCurrentItem(tree.topLevelItem(0))
        refresh_buttons()
        update.clicked.connect(lambda: self._start_image_indexing([(Path(value[0]), bool(value[1]))]) if (value := selected_folder()) else None)
        update_all.clicked.connect(lambda: self._start_image_indexing([(folder, recursive) for folder, recursive, _ in indexed_folders()]))
        def remove_selected():
            value = selected_folder()
            if not value: return
            answer = QMessageBox.question(dialog, t("Aus Index entfernen"), t("Den ausgewählten Ordner nur aus dem Bildindex entfernen?"))
            if answer != QMessageBox.StandardButton.Yes: return
            remove_indexed_folder(Path(value[0])); tree.takeTopLevelItem(tree.indexOfTopLevelItem(tree.currentItem()))
            folder_entries[:] = [entry for entry in folder_entries if entry[0] != Path(value[0])]
            refresh_buttons()
        remove.clicked.connect(remove_selected); dialog.exec()

    def _show_image_search_dialog(self) -> None:
        dialog = QDialog(self.window); dialog.setWindowTitle(t("Bilder suchen …"))
        form = QFormLayout(dialog)
        person, place, comment = QLineEdit(dialog), QLineEdit(dialog), QLineEdit(dialog)
        form.addRow(t("Person"), person); form.addRow(t("Aufnahmeort"), place); form.addRow(t("Bemerkungen"), comment)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, dialog)
        reset = buttons.addButton(t("Zurücksetzen"), QDialogButtonBox.ButtonRole.ResetRole)
        search = buttons.addButton(t("Suchen"), QDialogButtonBox.ButtonRole.AcceptRole)
        reset.clicked.connect(lambda: (person.clear(), place.clear(), comment.clear()))
        buttons.rejected.connect(dialog.reject); search.clicked.connect(dialog.accept); form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        if not any((person.text().strip(), place.text().strip(), comment.text().strip())):
            QMessageBox.information(self.window, t("Bilder suchen …"), t("Bitte mindestens ein Suchkriterium eingeben.")); return
        self._show_image_search_results(search_images(person.text(), place.text(), comment.text()))

    def _show_image_search_results(self, paths: list[Path]) -> None:
        if not self._search_mode:
            self._search_return_directory, self._search_return_image = self.current_directory, self.current_image
        self._search_mode = True; self.end_image_search_action.setVisible(True)
        self.thread_pool.clear(); self._load_generation += 1; generation = self._load_generation
        self._pending_images = [path for path in paths if path.is_file()]
        self._prepare_index = self._next_job_index = self._completed_jobs = self._active_jobs = 0
        self.thumbnail_list.clear(); self.current_image = None
        self._set_file_name_text(t("Suchergebnisse – {count} Bilder").format(count=len(self._pending_images)))
        self.set_status(STATUS_READY, t("{count} Bilder gefunden").format(count=len(self._pending_images)))
        self._prepare_thumbnail_items(generation)

    def _end_image_search(self) -> None:
        if not self._search_mode: return
        self._search_mode = False; self.end_image_search_action.setVisible(False)
        if self._search_return_directory is not None:
            self._show_directory(self._search_return_directory, [self._search_return_image] if self._search_return_image else None)

    def _set_language(self, code: str) -> None:
        """Apply and persist one supported interface language immediately."""
        self.language_manager.set_language(code)
        for value, action in self.language_actions.items():
            action.setChecked(value == self.language_manager.code)
        self._retranslate_manual_metadata_editor()
        self._update_information_panel()
        self.language_manager.translate_widget_tree(self.window)
        self.refresh_i18n()

    def refresh_i18n(self) -> None:
        """Refresh generated main-window text after a live language switch."""
        for menu, source in (
            (self.file_menu, "Datei"), (self.edit_menu, "Bearbeiten"),
            (self.view_menu, "Ansicht"), (self.go_to_menu, "Gehe zu"),
            (self.tools_menu, "Werkzeuge"),
            (self.help_menu, "Hilfe"), (self.language_menu, "Sprache"),
            (self.sort_menu, "Sortieren nach"), (self.color_scheme_menu, "Farbschema"),
            (self.thumbnail_position_menu, "Vorschaubilder"),
        ):
            menu.setTitle(t(source))
        for action, source in (
            (self.leave_pdf_preview_action, "PDF-Vorschau verlassen"),
            (self.previous_pdf_page_action, "PDF-Seite zurück"),
            (self.next_pdf_page_action, "PDF-Seite weiter"),
            (self.previous_folder_action, "Vorheriger Ordner"),
            (self.next_folder_action, "Nächster Ordner"),
            (self.parent_folder_action, "Übergeordneter Ordner"),
            (self.first_image_action, "Erstes Bild"),
            (self.previous_image_action, "Vorheriges Bild"),
            (self.next_image_action, "Nächstes Bild"),
            (self.last_image_action, "Letztes Bild"),
            (self.about_action, "Über {name} …"),
        ):
            action.setText(t(source).format(name=APP_NAME))
        for position, source in (
            ("top", "Oben"), ("left", "Links"),
            ("right", "Rechts"), ("hidden", "Ausblenden"),
        ):
            self.thumbnail_position_actions[position].setText(t(source))
        self.thumbnail_quick_toggle.setText(t("Vorschaubilder"))
        self.details_quick_toggle.setText(t("Details"))
        self.fullscreen_quick_toggle.setText(t("Vollbild"))
        self.thumbnail_quick_toggle.setToolTip(t("Vorschaubilder"))
        self.details_quick_toggle.setToolTip(t("Details"))
        self.fullscreen_quick_toggle.setToolTip(t("Vollbild"))
        self._update_quick_switches_layout()
        self._sync_quick_switches()
        self.previous_button.setToolTip(t("Vorheriges Bild"))
        self.next_button.setToolTip(t("Nächstes Bild"))
        self.previous_button.setAccessibleName(t("Vorheriges Bild"))
        self.next_button.setAccessibleName(t("Nächstes Bild"))
        self.previous_pdf_page_button.setAccessibleName(t("Vorherige PDF-Seite"))
        self.next_pdf_page_button.setAccessibleName(t("Nächste PDF-Seite"))
        self.previous_pdf_page_button.setToolTip(t("Vorherige PDF-Seite"))
        self.next_pdf_page_button.setToolTip(t("Nächste PDF-Seite"))
        self._refresh_pdf_thumbnail_text()
        self._update_pdf_page_navigation()
        self._refresh_status_text()
        self._update_status_bar()

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
        self.compare_images_action.setEnabled(True)
        self.select_all_action.setEnabled(self.thumbnail_list.count() > 0)

    def _update_print_action_state(self) -> None:
        can_print = (
            self.current_image is not None
            and self.current_image.is_file()
            and not self.original_image.isNull()
        )
        self.print_action.setEnabled(can_print)

    def _show_wysiwyg_print_dialog(self) -> None:
        """Open the standard PagePlan-based single-image print dialog."""
        if not (self.current_image and self.current_image.is_file() and not self.original_image.isNull()):
            self._update_print_action_state()
            QMessageBox.information(self.window, t("Kein Bild geöffnet"), t("Bitte öffnen oder markieren Sie zuerst ein Bild."))
            return
        try:
            reader = QImageReader(str(self.current_image)); reader.setAutoTransform(True)
            image = reader.read()
            if image.isNull(): raise RuntimeError(reader.errorString() or t("Das Bild konnte nicht geladen werden."))
            image = rotated_display_image(image, self._current_display_rotation())
            if image.isNull(): raise RuntimeError(t("Das Druckbild konnte nicht gedreht werden."))
            source = ImageSourceInfo(self.current_image, image.width(), image.height(), image_print_dpi(self.current_image), image_print_dpi(self.current_image), self.current_image.name, capture_date_text(self.current_image))
            dialog = SingleImageWysiwygPrintDialog(
                image, source, self.settings, self.window,
                theme_colors=COLOR_SCHEMES[self._color_scheme],
            )
            if dialog.exec() != QDialog.DialogCode.Accepted: return
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            selected_plan = dialog.build_page_plan()
            # Seed the native dialog from the planned paper/orientation. A user
            # change there is honoured below through final printer geometry.
            orientation = (
                QPageLayout.Orientation.Landscape
                if selected_plan.page_size.width_mm > selected_plan.page_size.height_mm
                else QPageLayout.Orientation.Portrait
            )
            configure_printer_page_layout(printer, dialog._page_size(), orientation)
            print_dialog = QPrintDialog(printer, self.window); print_dialog.setWindowTitle(t("Bild drucken"))
            if run_without_application_stylesheet(print_dialog.exec) != QDialog.DialogCode.Accepted: return
            geometry = printer_geometry_mm(printer)
            plan = dialog.build_page_plan(geometry.paint_rect, geometry.page_size)
            painter = QPainter()
            if not painter.begin(printer): raise RuntimeError("Der Druckauftrag konnte nicht gestartet werden.")
            try:
                viewport = painter.viewport()
                target = printer_target_rect_for_painter(geometry, QRectF(0, 0, viewport.width(), viewport.height()))
                render_page_plan(painter, plan, target, lambda _source: image)
            finally:
                painter.end()
        except Exception as error:
            QMessageBox.critical(self.window, t("Drucken fehlgeschlagen"), t("Druckfehler: {detail}").format(detail=str(error)))

    def _show_multi_wysiwyg_print_dialog(self) -> None:
        """Open the standard PagePlan-based multi-image print dialog."""
        current = [self.current_image] if self.current_image and self.current_image.is_file() else []
        selected = [path for path in self._selected_thumbnail_paths_in_display_order() if path.is_file()]
        all_paths = self._all_thumbnail_image_paths()
        sources = {
            "current": multi_image_sources(current, include_capture_date=True),
            "selected": multi_image_sources(selected, include_capture_date=True),
            "all": multi_image_sources(all_paths, include_capture_date=True),
        }
        if not any(sources.values()):
            QMessageBox.information(self.window, t("Keine Bilder zum Drucken"), t("Es wurden keine gültigen Bilder gefunden."))
            return
        dialog = MultiImageWysiwygPrintDialog(
            sources, self.settings, self.window,
            theme_colors=COLOR_SCHEMES[self._color_scheme],
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = [source.path for source in dialog.selected_sources()]
        self._print_multiple_images(
            chosen, dialog.print_settings(), dialog._page_size(),
            folder_name=dialog.footer_folder_name(),
            print_date_text=dialog.print_date_text(),
        )

    def _all_thumbnail_image_paths(self) -> list[Path]:
        return [
            Path(self.thumbnail_list.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self.thumbnail_list.count())
            if Path(self.thumbnail_list.item(row).data(Qt.ItemDataRole.UserRole)).is_file()
        ]

    def _print_multiple_images(self, paths: list[Path], print_settings: MultiImagePrintSettings, page_size: PageSizeMm | None = None, *, folder_name: str | None = None, print_date_text: str | None = None) -> None:
        images_per_page = print_settings.effective_images_per_page
        first = QImageReader(str(paths[0])); first.setAutoTransform(True); first_image = first.read()
        orientation = QPageLayout.Orientation.Landscape if print_settings.orientation == "landscape" or (print_settings.orientation == "automatic" and images_per_page == 1 and first_image.width() > first_image.height()) else QPageLayout.Orientation.Portrait
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        configure_printer_page_layout(
            printer,
            page_size,
            orientation,
        )
        print_dialog = QPrintDialog(printer, self.window); print_dialog.setWindowTitle(t("Bilder drucken"))
        accepted = run_without_application_stylesheet(
            print_dialog.exec
        ) == QDialog.DialogCode.Accepted
        if not accepted: return
        failures: list[str] = []
        image_cache: dict[Path, QImage] = {}
        try:
            geometry = printer_geometry_mm(printer)
            document = multi_image_document_from_settings(
                multi_image_sources(paths, print_settings.show_capture_date),
                print_settings,
                source_kind=print_settings.source,
                folder_name=folder_name if folder_name is not None else print_settings.footer_folder_name,
                print_date_text=print_date_text if print_date_text is not None else current_print_date_text(),
                printer_geometry=geometry,
            )
            page_plans = plan_multi_image_pages(document)
            if not page_plans:
                raise ValueError(t("Es wurden keine gültigen Bilder zum Drucken gefunden."))
        except ValueError as error:
            QMessageBox.warning(self.window, t("Drucklayout nicht möglich"), t("Druckfehler: {detail}").format(detail=str(error)))
            return
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.critical(self.window, t("Drucken fehlgeschlagen"), t("Der Druckauftrag konnte nicht gestartet werden.")); return
        try:
            viewport = painter.viewport()
            target = printer_target_rect_for_painter(
                geometry, QRectF(0, 0, viewport.width(), viewport.height())
            )

            def image_provider(source: ImageSourceInfo) -> QImage:
                if source.path not in image_cache:
                    reader = QImageReader(str(source.path))
                    reader.setAutoTransform(True)
                    image_cache[source.path] = reader.read()
                    if image_cache[source.path].isNull():
                        failures.append(source.path.name)
                return image_cache[source.path]

            for page_index, page_plan in enumerate(page_plans):
                render_page_plan(painter, page_plan, target, image_provider)
                if page_index < len(page_plans) - 1 and not printer.newPage():
                    raise RuntimeError(t("Eine neue Druckseite konnte nicht erzeugt werden."))
        except Exception as error:
            QMessageBox.critical(self.window, t("Drucken fehlgeschlagen"), t("Druckfehler: {detail}").format(detail=str(error)))
        finally:
            if painter.isActive():
                painter.end()
        if failures:
            QMessageBox.warning(self.window, t("Einige Bilder konnten nicht geladen werden"), t("Druckfehler: {detail}").format(detail="\n".join(failures)))

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
            colors = COLOR_SCHEMES[self._color_scheme]
            indicator_color = (
                colors["text"]
                if colors is not None
                else application.palette().color(QPalette.ColorRole.Text).name()
            )
            self.directory_tree.setProperty(
                "directoryIndicatorColor", indicator_color
            )
            hierarchy_color = (
                colors["muted"]
                if colors is not None
                else application.palette().color(QPalette.ColorRole.Text).name()
            )
            self.directory_tree.setProperty(
                "directoryHierarchyColor", hierarchy_color
            )
            self.directory_tree.viewport().update()
            tooltip_palette = QPalette(self._system_tooltip_palette)
            if colors is not None:
                for color_group in (
                    QPalette.ColorGroup.Active,
                    QPalette.ColorGroup.Inactive,
                    QPalette.ColorGroup.Disabled,
                ):
                    tooltip_palette.setColor(
                        color_group,
                        QPalette.ColorRole.ToolTipBase,
                        QColor(colors["tooltip"]),
                    )
                    tooltip_palette.setColor(
                        color_group,
                        QPalette.ColorRole.ToolTipText,
                        QColor(colors["tooltip_text"]),
                    )
            QToolTip.setPalette(tooltip_palette)
            application.setStyleSheet(
                color_scheme_stylesheet(colors)
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
        dialog.setWindowTitle(t("Größe der Vorschaubilder"))
        dialog.setModal(True)
        dialog.setMinimumWidth(390)
        layout = QVBoxLayout(dialog)
        value_label = QLabel(t("{count} Pixel").format(count=self._thumbnail_pixels))
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(value_label)

        slider_row = QHBoxLayout()
        slider_row.addWidget(QLabel(t("Klein")))
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
                t("{count} Pixel").format(count=THUMBNAIL_MINIMUM + step * THUMBNAIL_STEP)
            )
        )
        slider_row.addWidget(slider, 1)
        slider_row.addWidget(QLabel(t("Groß")))
        layout.addLayout(slider_row)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        apply_button = QPushButton(t("Übernehmen"))
        cancel_button = QPushButton(t("Abbrechen"))
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
        self._directory_loading_generation = generation
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
        if mime_data.hasFormat(CLIPBOARD_OPERATION_MIME_TYPE):
            clipboard_data = bytes(
                mime_data.data(CLIPBOARD_OPERATION_MIME_TYPE)
            ).decode("utf-8", errors="replace")
            lines = [line.strip() for line in clipboard_data.splitlines() if line.strip()]
            if lines and lines[0] in ("copy", "cut"):
                operation = lines[0]
                urls = [QUrl(line) for line in lines[1:]]
        if mime_data.hasFormat("x-special/gnome-copied-files"):
            clipboard_data = bytes(
                mime_data.data("x-special/gnome-copied-files")
            ).decode("utf-8", errors="replace")
            lines = [line.strip() for line in clipboard_data.splitlines() if line.strip()]
            if not urls and lines and lines[0] in ("copy", "cut"):
                operation = lines[0]
                urls = [QUrl(line) for line in lines[1:]]
        if not urls and mime_data.hasUrls():
            urls = mime_data.urls()
        paths = []
        for url in urls:
            if url.isLocalFile():
                paths.append(Path(url.toLocalFile()))
        internal_paths = [
            path.resolve(strict=False) for path in self._clipboard_source_paths
        ]
        if (
            paths
            and self._clipboard_operation in ("copy", "cut")
            and [path.resolve(strict=False) for path in paths] == internal_paths
        ):
            operation = self._clipboard_operation
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
            target_directory = self._paste_target_directory()
            self.paste_image_action.setEnabled(
                any(
                    self._is_suitable_clipboard_image(path)
                    for path in clipboard_paths
                )
                and target_directory is not None
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
                t("Der Zielordner konnte nicht im Dateimanager geöffnet werden.")
                + (f"\n\n{'\n'.join(errors)}" if errors else ""),
            )

    def _rename_image(self, image_path: Path | None = None) -> None:
        source_path = image_path or self.current_image
        if source_path is None:
            return
        source_path = Path(source_path)
        if not source_path.is_file():
            self._show_rename_error(
                t("Die Bilddatei wurde nicht gefunden."), str(source_path)
            )
            return
        if source_path.suffix.lower() not in IMAGE_EXTENSIONS:
            self._show_rename_error(
                t("Dieses Bildformat wird nicht unterstützt."), str(source_path)
            )
            return
        if not (
            source_path.parent.is_dir()
            and os.access(source_path.parent, os.W_OK | os.X_OK)
        ):
            self._show_rename_error(
                t("Der Ordner ist schreibgeschützt oder nicht beschreibbar."),
                str(source_path.parent),
            )
            return

        extension = source_path.suffix
        base_name = source_path.name[: -len(extension)] if extension else source_path.name
        dialog = QDialog(self.window)
        dialog.setWindowTitle(t("Bild umbenennen"))
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(QLabel(t("Bisher: {name}").format(name=source_path.name), dialog))
        layout.addWidget(QLabel(t("Neuer Name:"), dialog))
        name_edit = QLineEdit(base_name, dialog)
        name_edit.selectAll()
        layout.addWidget(name_edit)
        extension_label = QLabel(
            t("Dateiendung: {extension}").format(extension=extension or t("(keine)")), dialog
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
                    t("Der neue Dateiname ist mit dem bisherigen Namen identisch."),
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
                    t("Eine Datei mit diesem Namen existiert bereits."),
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
                    t("Die Bilddatei konnte nicht umbenannt werden."),
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
            return t("Bitte gib einen Dateinamen ein.")
        if base_name in (".", ".."):
            return t("Dieser Dateiname ist nicht zulässig.")
        if "/" in base_name or "\0" in base_name:
            return t("Der Dateiname darf weder „/“ noch Nullzeichen enthalten.")
        extension = source_path.suffix
        old_base_name = (
            source_path.name[: -len(extension)] if extension else source_path.name
        )
        if base_name == old_base_name:
            return t("Der neue Dateiname ist mit dem bisherigen Namen identisch.")
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
        error_dialog.setWindowTitle(t("Bild umbenennen"))
        error_dialog.setIcon(QMessageBox.Icon.Warning)
        error_dialog.setText(message)
        if detail:
            error_dialog.setInformativeText(detail)
        error_dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        error_dialog.button(QMessageBox.StandardButton.Ok).setText(t("OK"))
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
                t("Der übergeordnete Ordner ist nicht erreichbar."),
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
            t("Weder Nemo noch ein anderer Dateimanager konnte gestartet werden.")
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
        dialog.setWindowTitle(t("Im Dateimanager anzeigen"))
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(t("Die Datei wurde nicht gefunden."))
        dialog.setInformativeText(str(image_path.absolute()))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.button(QMessageBox.StandardButton.Ok).setText(t("OK"))
        self._style_message_box(dialog)
        dialog.exec()

    def _show_file_manager_error(
        self, image_path: Path, detail: str
    ) -> None:
        dialog = QMessageBox(self.window)
        dialog.setWindowTitle(t("Im Dateimanager anzeigen"))
        dialog.setIcon(QMessageBox.Icon.Critical)
        dialog.setText(t("Der Speicherort konnte nicht geöffnet werden."))
        dialog.setInformativeText(f"{image_path}\n\n{detail}")
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.button(QMessageBox.StandardButton.Ok).setText(t("OK"))
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
                message = t("Bitte markieren Sie zuerst zwei Bilder.")
            elif selected_count == 1:
                message = t("Bitte markieren Sie noch ein zweites Bild.")
            else:
                message = t("Bitte markieren Sie genau zwei Bilder.\nAktuell sind {count} Bilder ausgewählt.").format(count=selected_count)
            dialog = QMessageBox(self.window)
            dialog.setWindowTitle(t("Bilder vergleichen"))
            dialog.setIcon(QMessageBox.Icon.Information)
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setText(message)
            dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
            dialog.button(QMessageBox.StandardButton.Ok).setText(t("OK"))
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
        mime_data.setData(
            CLIPBOARD_OPERATION_MIME_TYPE,
            operation.encode("utf-8")
            + b"\n"
            + b"\n".join(bytes(url.toEncoded()) for url in source_urls),
        )
        self._clipboard_operation = operation
        self._clipboard_source_paths = source_paths
        self.clipboard.setMimeData(mime_data)
        # Some platform clipboard backends notify dataChanged asynchronously.
        # Refresh explicitly so Paste is available immediately after Ctrl+C/X.
        self._clipboard_changed()
        if operation == "cut":
            for source_path in source_paths:
                item = self._thumbnail_item_for_path(source_path)
                if item is not None:
                    item.setForeground(QBrush(QColor("#888888")))

    def _show_file_operation_error(self, message: str, detail: str) -> None:
        error_dialog = QMessageBox(self.window)
        error_dialog.setWindowTitle(t("Dateivorgang fehlgeschlagen"))
        error_dialog.setIcon(QMessageBox.Icon.Critical)
        error_dialog.setTextFormat(Qt.TextFormat.PlainText)
        error_dialog.setText(message)
        error_dialog.setInformativeText(detail)
        error_dialog.setStandardButtons(QMessageBox.StandardButton.Close)
        error_dialog.button(QMessageBox.StandardButton.Close).setText(t("Schließen"))
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
        target_directory: Path,
        conflict_policy: str | None,
    ) -> tuple[Path | None, str, str | None]:
        destination = target_directory / source_path.name
        if not destination.exists():
            return destination, "proceed", conflict_policy
        if conflict_policy == "keep":
            return self._unused_destination_path(destination), "proceed", conflict_policy
        if conflict_policy == "replace":
            return destination, "proceed", conflict_policy
        if conflict_policy == "skip":
            return None, "skip", conflict_policy

        conflict_dialog = QMessageBox(self.window)
        conflict_dialog.setWindowTitle(t("Datei bereits vorhanden"))
        conflict_dialog.setIcon(QMessageBox.Icon.Warning)
        conflict_dialog.setTextFormat(Qt.TextFormat.PlainText)
        conflict_dialog.setText(
            t("Im Zielordner ist bereits eine Datei mit diesem Namen vorhanden.")
        )
        conflict_dialog.setInformativeText(destination.name)
        replace_button = conflict_dialog.addButton(
            t("Datei ersetzen"), QMessageBox.ButtonRole.DestructiveRole
        )
        keep_button = conflict_dialog.addButton(
            t("Beide behalten"), QMessageBox.ButtonRole.AcceptRole
        )
        skip_button = conflict_dialog.addButton(
            t("Überspringen"), QMessageBox.ButtonRole.ActionRole
        )
        cancel_button = conflict_dialog.addButton(
            t("Abbrechen"), QMessageBox.ButtonRole.RejectRole
        )
        apply_to_all = QCheckBox(t("Für alle weiteren Konflikte übernehmen"))
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
        replace_dialog.setWindowTitle(t("Zieldatei ersetzen"))
        replace_dialog.setIcon(QMessageBox.Icon.Warning)
        replace_dialog.setTextFormat(Qt.TextFormat.PlainText)
        replace_dialog.setText(t("Möchtest du diese Zieldatei wirklich ersetzen?"))
        replace_dialog.setInformativeText(str(destination))
        confirm_button = replace_dialog.addButton(
            t("Datei ersetzen"), QMessageBox.ButtonRole.DestructiveRole
        )
        replace_cancel_button = replace_dialog.addButton(
            t("Abbrechen"), QMessageBox.ButtonRole.RejectRole
        )
        replace_dialog.setDefaultButton(replace_cancel_button)
        replace_dialog.setEscapeButton(replace_cancel_button)
        self._style_message_box(replace_dialog)
        replace_dialog.exec()
        if replace_dialog.clickedButton() is not confirm_button:
            return None, "cancel", conflict_policy
        policy = "replace" if apply_to_all.isChecked() else None
        return destination, "proceed", policy

    def _paste_target_directory(self) -> Path | None:
        index = self.directory_tree.currentIndex()
        if index.isValid():
            selected_directory = Path(self.directory_model.filePath(index))
            if selected_directory.is_dir():
                return selected_directory
        if self.current_directory is not None and self.current_directory.is_dir():
            return self.current_directory
        return None

    def _paste_image_from_clipboard(self) -> None:
        source_paths, operation = self._clipboard_files()
        target_directory = self._paste_target_directory()
        if not source_paths or target_directory is None:
            self.paste_image_action.setEnabled(False)
            return
        inserted_paths = []
        successful_source_paths = set()
        failures = []
        conflict_policy = None
        for source_path in source_paths:
            if not self._is_suitable_clipboard_image(source_path):
                failures.append(t("{name}: nicht verfügbar oder nicht unterstützt").format(name=source_path.name))
                continue
            destination, decision, conflict_policy = self._resolve_destination_path(
                source_path, target_directory, conflict_policy
            )
            if decision == "cancel":
                break
            if decision == "skip" or destination is None:
                failures.append(t("{name}: übersprungen").format(name=source_path.name))
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
                failures.append(t("{name}: {detail}").format(name=source_path.name, detail=error))

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
                t("Einige Bilder konnten nicht eingefügt werden."),
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
        confirmation.setWindowTitle(t("Bild in den Papierkorb verschieben"))
        confirmation.setIcon(QMessageBox.Icon.Question)
        confirmation.setTextFormat(Qt.TextFormat.PlainText)
        if len(selected) == 1:
            confirmation.setText(
                t("Möchtest du dieses Bild in den Papierkorb verschieben?")
            )
            confirmation.setInformativeText(selected[0][1].name)
        else:
            confirmation.setText(
                t("Möchtest du die ausgewählten {count} Bilder in den Papierkorb verschieben?").format(count=len(selected))
            )
        trash_button = confirmation.addButton(
            t("In den Papierkorb"),
            QMessageBox.ButtonRole.AcceptRole,
        )
        cancel_button = confirmation.addButton(
            t("Abbrechen"),
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
                failures.append(t("{name}: {detail}").format(name=image_path.name, detail=error))
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
            self.image_label.setText(t("Bild anklicken, um es anzuzeigen"))
            self._set_file_name_text(t("{count} Bilder").format(count=0))
            self._update_view_actions()
            self._update_navigation_buttons()
        elif slideshow_was_running:
            self._restart_slideshow_timer()

        if failures:
            self._show_file_operation_error(
                t("Einige Bilder konnten nicht in den Papierkorb verschoben werden."),
                "\n".join(failures),
            )

    def _show_controls_help(self) -> None:
        help_dialog = QMessageBox(self.window)
        help_dialog.setWindowTitle(t("Bedienung und Tastenkürzel"))
        help_dialog.setIcon(QMessageBox.Icon.Information)
        help_dialog.setTextFormat(Qt.TextFormat.RichText)
        help_dialog.setText(t("__help_dialog_text__"))
        help_dialog.setStandardButtons(QMessageBox.StandardButton.Close)
        help_dialog.button(QMessageBox.StandardButton.Close).setText(t("Schließen"))
        self._style_message_box(help_dialog)
        help_dialog.exec()

    def _show_about(self) -> None:
        about_dialog = QDialog(self.window)
        about_dialog.setWindowTitle(t("Über {name}").format(name=APP_NAME))
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

        version_label = QLabel(t("Version {version}").format(version=APP_VERSION))
        version_label.setObjectName("aboutVersionLabel")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        layout.addWidget(version_label)

        description_label = QLabel(t(APP_DESCRIPTION))
        description_label.setObjectName("aboutDescriptionLabel")
        description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description_label.setWordWrap(True)
        layout.addWidget(description_label)

        technology_label = QLabel(t("Erstellt mit Python und PySide6"))
        technology_label.setObjectName("aboutTechnologyLabel")
        technology_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(technology_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_button = QPushButton(t("Schließen"))
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
        self.slideshow_menu = self.view_menu.addMenu(t("Diashow"))

        self.slideshow_action = QAction(t("Diashow starten / beenden"), self.window)
        self.slideshow_action.setShortcut(QKeySequence("F5"))
        self.slideshow_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.slideshow_action.triggered.connect(self._toggle_slideshow)
        self.slideshow_menu.addAction(self.slideshow_action)

        self.slideshow_pause_action = QAction(t("Pause / fortsetzen"), self.window)
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
            action = QAction(t(text), self.window)
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
        self.interval_menu = self.slideshow_menu.addMenu(t("Intervall"))
        self.interval_action_group = QActionGroup(self.window)
        self.interval_action_group.setExclusive(True)
        for seconds in SLIDESHOW_INTERVALS:
            action = QAction(t("{seconds} Sekunden").format(seconds=seconds), self.window)
            action.setCheckable(True)
            action.setData(seconds)
            action.setChecked(seconds == self._slideshow_interval)
            self.interval_action_group.addAction(action)
            self.interval_menu.addAction(action)
        self.interval_action_group.triggered.connect(self._set_slideshow_interval)

        self.slideshow_menu.addSeparator()
        self.slideshow_fullscreen_action = QAction(
            t("Im Vollbild starten"), self.window
        )
        self.slideshow_fullscreen_action.setCheckable(True)
        self.slideshow_fullscreen_action.setChecked(self._slideshow_fullscreen)
        self.slideshow_fullscreen_action.toggled.connect(
            self._set_slideshow_fullscreen
        )
        self.slideshow_menu.addAction(self.slideshow_fullscreen_action)

        self.slideshow_repeat_action = QAction(t("Wiederholen"), self.window)
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
            dialog.setWindowTitle(t("Diashow"))
            dialog.setIcon(QMessageBox.Icon.Information)
            dialog.setText(t("Bitte markieren Sie zuerst mindestens ein Bild."))
            dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
            dialog.button(QMessageBox.StandardButton.Ok).setText(t("OK"))
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
            self._show_slideshow_message(t("Diashow pausiert"))
        else:
            self._restart_slideshow_timer()
            self._show_slideshow_message(t("Diashow fortgesetzt"))
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
            t("Diashow beenden") if self._slideshow_running else t("Diashow starten")
        )
        self.slideshow_action.setText(action_text)
        self.slideshow_pause_action.setEnabled(self._slideshow_running)
        self.slideshow_pause_action.setText(
            t("Fortsetzen") if self._slideshow_paused else t("Pause / fortsetzen")
        )
        self.slideshow_selected_only_action.setEnabled(
            not self._slideshow_running
        )
        self.slideshow_random_action.setEnabled(not self._slideshow_running)
        self.slideshow_fullscreen_action.setEnabled(not self._slideshow_running)

    def _handle_escape(self) -> None:
        if self.information_panel.isVisible():
            self._hide_information_panel()
            return
        if self._slideshow_running:
            self._stop_slideshow()
        if self._fullscreen_mode:
            self._leave_fullscreen()
        elif self._pdf_preview_mode:
            self._leave_pdf_preview()

    def _install_network_navigation(self) -> None:
        """Add a compact alias view for desktop-managed network mounts."""
        self.network_navigation = QWidget(self.directory_panel)
        navigation_layout = QVBoxLayout(self.network_navigation)
        navigation_layout.setContentsMargins(0, 0, 0, 0)
        navigation_layout.setSpacing(4)

        header_row = QWidget(self.network_navigation)
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)
        self.network_toggle_button = QToolButton(header_row)
        self.network_toggle_button.setObjectName("networkToggleButton")
        self.network_toggle_button.setText(t("Netzwerk"))
        self.network_toggle_button.setCheckable(True)
        self.network_toggle_button.setChecked(False)
        self.network_toggle_button.setArrowType(Qt.ArrowType.RightArrow)
        self.network_toggle_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.network_toggle_button.setFixedHeight(28)
        self.network_toggle_button.setMinimumWidth(112)
        self.network_toggle_button.setStyleSheet(
            "QToolButton { border: 1px solid palette(mid); border-radius: 3px; "
            "padding: 1px 7px; }"
            "QToolButton:hover { background: palette(alternate-base); }"
        )
        self.network_toggle_button.toggled.connect(self._set_network_navigation_expanded)
        header_layout.addWidget(self.network_toggle_button)
        header_layout.addStretch()
        navigation_layout.addWidget(header_row)

        self.network_navigation_content = QWidget(self.network_navigation)
        content_layout = QVBoxLayout(self.network_navigation_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(2)
        self.network_tree = QTreeWidget(self.network_navigation_content)
        self.network_tree.setHeaderHidden(True)
        self.network_tree.setRootIsDecorated(False)
        self.network_tree.setIndentation(14)
        self.network_tree.setMaximumHeight(66)
        self.network_tree.setStyleSheet(
            "QTreeWidget { border: 0; }"
            "QTreeWidget::item { height: 22px; padding: 0 2px; }"
        )
        self.network_tree.setObjectName("networkTreeWidget")
        self.network_tree.itemClicked.connect(self._network_tree_item_clicked)
        self.network_tree.itemExpanded.connect(self._populate_network_tree_item)
        self.network_connect_button = QPushButton(t("Netzwerkort verbinden …"), self.directory_panel)
        self.network_connect_button.setMaximumHeight(24)
        self.network_connect_button.setStyleSheet("QPushButton { padding: 1px 6px; }")
        self.network_connect_button.clicked.connect(self._connect_network_location)
        content_layout.addWidget(self.network_tree)
        content_layout.addWidget(self.network_connect_button)
        navigation_layout.addWidget(self.network_navigation_content)
        layout = self.directory_panel.layout()
        layout.setSpacing(4)
        layout.insertWidget(1, self.network_navigation)
        self._refresh_network_navigation()
        self._set_network_navigation_expanded(False)

    def _set_network_navigation_expanded(self, expanded: bool) -> None:
        """Show mount controls only after the compact network header is opened."""
        self.network_navigation_content.setVisible(expanded)
        self.network_toggle_button.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )

    def _refresh_network_navigation(self) -> None:
        """Refresh aliases only; the real QFileSystemModel remains shared."""
        if not hasattr(self, "network_tree"):
            return
        self.network_tree.clear()
        for path in network_mount_paths():
            item = QTreeWidgetItem([network_mount_label(path)])
            item.setData(0, Qt.ItemDataRole.UserRole, str(path))
            item.setChildIndicatorPolicy(
                QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
            )
            self.network_tree.addTopLevelItem(item)

    def _populate_network_tree_item(self, item: QTreeWidgetItem) -> None:
        populated_role = Qt.ItemDataRole.UserRole.value + 1
        if item.data(0, populated_role):
            return
        value = item.data(0, Qt.ItemDataRole.UserRole)
        if not value:
            return
        path = Path(value)
        try:
            children = sorted(
                (child for child in path.iterdir() if child.is_dir()),
                key=lambda child: child.name.casefold(),
            )
        except OSError:
            return
        item.takeChildren()
        for child in children:
            child_item = QTreeWidgetItem([child.name])
            child_item.setData(0, Qt.ItemDataRole.UserRole, str(child))
            child_item.setChildIndicatorPolicy(
                QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
            )
            item.addChild(child_item)
        item.setData(0, populated_role, True)

    def _network_tree_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        value = item.data(0, Qt.ItemDataRole.UserRole)
        if not value:
            return
        directory = Path(value)
        if directory.is_dir():
            self._show_directory(directory)
            self._expand_initial_path(directory)

    def _connect_network_location(self) -> None:
        """Delegate connection and authentication to the desktop's GIO/GVFS."""
        dialog = QDialog(self.window)
        dialog.setWindowTitle(t("Netzwerkort verbinden"))
        layout = QFormLayout(dialog)
        address = QLineEdit(dialog)
        address.setPlaceholderText("sftp://mac.local/")
        layout.addRow(t("Adresse:"), address)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            parent=dialog,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("Verbinden"))
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted or not address.text().strip():
            return
        # gio invokes the existing GVFS/system authentication UI.  Credentials
        # are deliberately neither collected nor persisted by BildBlick.
        try:
            subprocess.Popen(["gio", "mount", address.text().strip()])
        except OSError as error:
            QMessageBox.warning(self.window, t("Netzwerkort verbinden"), str(error))

    def _create_directory_model(self) -> None:
        """Create a fresh model so mounts below /Volumes are rediscovered."""
        previous_model = getattr(self, "directory_model", None)
        self.directory_model = QFileSystemModel(self.window)
        self._set_directory_model_filter()
        self.directory_model.setReadOnly(True)
        self.directory_model.directoryLoaded.connect(
            lambda _path: self._retry_pending_tree_path()
        )
        if not hasattr(self, "directory_tree_indicator_delegate"):
            self.directory_tree.setProperty(
                "showHiddenDirectories", self._show_hidden_files
            )
            self.directory_tree_indicator_delegate = DirectoryTreeIndicatorDelegate(
                self.directory_tree
            )
            self.directory_tree.setItemDelegate(
                self.directory_tree_indicator_delegate
            )
        else:
            self.directory_tree_indicator_delegate.invalidate()
        self.directory_model.directoryLoaded.connect(
            self.directory_tree_indicator_delegate.invalidate
        )
        self.directory_model.rowsInserted.connect(
            lambda parent, _first, _last: self._invalidate_directory_indicator(parent)
        )
        self.directory_model.rowsRemoved.connect(
            lambda parent, _first, _last: self._invalidate_directory_indicator(parent)
        )
        root_index = self.directory_model.setRootPath(str(ROOT_DIRECTORY))
        self.directory_tree.setModel(self.directory_model)
        self.directory_tree.setRootIndex(root_index)
        for column in range(1, self.directory_model.columnCount()):
            self.directory_tree.hideColumn(column)
        if previous_model is not None:
            previous_model.deleteLater()

    def _network_mount_watch_paths(self) -> tuple[Path, ...]:
        """Return existing mount roots and the parent needed to notice GVFS."""
        paths = list(network_mount_roots())
        if sys.platform.startswith("linux"):
            gvfs_parent = Path(f"/run/user/{os.getuid()}")
            if gvfs_parent.is_dir() and gvfs_parent not in paths:
                paths.append(gvfs_parent)
        return tuple(paths)

    def _install_network_mount_watcher(self) -> None:
        """Refresh the tree when a macOS or Linux network mount changes."""
        watch_paths = self._network_mount_watch_paths()
        if not watch_paths:
            return
        self._volumes_refresh_timer = QTimer(self.window)
        self._volumes_refresh_timer.setSingleShot(True)
        self._volumes_refresh_timer.timeout.connect(self._refresh_network_mounts_tree)
        self._volumes_expand_retry_timer = QTimer(self.window)
        self._volumes_expand_retry_timer.setSingleShot(True)
        self._volumes_expand_retry_timer.timeout.connect(self._expand_network_mount_nodes)
        self._volumes_watcher = QFileSystemWatcher(
            [str(path) for path in watch_paths], self.window
        )
        self._network_mount_snapshot = network_mount_paths()
        self._volumes_watcher.directoryChanged.connect(self._schedule_volumes_refresh)
        self._expand_network_mount_nodes()

    def _schedule_volumes_refresh(self, _path: str = "") -> None:
        """Coalesce the several filesystem events a mount can generate."""
        self._volumes_refresh_timer.start(150)

    def _sync_network_mount_watch_paths(self) -> None:
        """Keep watches valid when GVFS itself appears or disappears."""
        desired = {str(path) for path in self._network_mount_watch_paths()}
        current = set(self._volumes_watcher.directories())
        stale = list(current - desired)
        if stale:
            self._volumes_watcher.removePaths(stale)
        added = list(desired - current)
        if added:
            self._volumes_watcher.addPaths(added)

    def _expand_network_mount_nodes(self) -> None:
        if sys.platform == "darwin":
            # Preserve the retry behaviour used while /Volumes is populated.
            self._expand_volumes_node()
            return
        expanded = False
        for mount_root in network_mount_roots():
            root_index = self.directory_model.index(str(mount_root))
            if root_index.isValid():
                self.directory_tree.expand(root_index)
                expanded = True
        if not expanded:
            self._volumes_expand_retry_timer.start(100)

    def _expand_volumes_node(self) -> None:
        volumes_index = self.directory_model.index(str(VOLUMES_DIRECTORY))
        if volumes_index.isValid():
            self.directory_tree.expand(volumes_index)
            return
        # The root model itself may still be loading when the application starts.
        self._volumes_expand_retry_timer.start(100)

    def _refresh_volumes_tree(self) -> None:
        """Backward-compatible name for the common mount refresh."""
        self._refresh_network_mounts_tree()

    def _refresh_network_mounts_tree(self) -> None:
        """Reload only after an actual mount-list change.

        GVFS and the user's runtime directory generate unrelated watcher
        events.  Recreating QFileSystemModel for those events discarded the
        tree's expansion state and made the view jump back to ``/``.
        """
        current_snapshot = network_mount_paths()
        previous_snapshot = getattr(self, "_network_mount_snapshot", ())
        self._sync_network_mount_watch_paths()
        if current_snapshot == previous_snapshot:
            return
        self._network_mount_snapshot = current_snapshot
        selected_directory = None
        selected_index = self.directory_tree.currentIndex()
        if selected_index.isValid():
            candidate = Path(self.directory_model.filePath(selected_index))
            if candidate.is_dir():
                selected_directory = candidate
        if selected_directory is None:
            current_directory = getattr(self, "current_directory", None)
            if current_directory is not None and current_directory.is_dir():
                selected_directory = current_directory

        self._create_directory_model()
        self._expand_network_mount_nodes()
        self._refresh_network_navigation()
        if selected_directory is not None:
            self._expand_initial_path(selected_directory)

    def _expand_initial_path(self, directory: Path) -> None:
        if not directory.is_dir():
            self._pending_tree_path = None
            self._tree_path_retry_timer.stop()
            return
        self._pending_tree_path = directory
        self._retry_pending_tree_path()

    def _retry_pending_tree_path(self) -> None:
        """Expand and select a pending path once QFileSystemModel knows it."""
        directory = self._pending_tree_path
        if directory is None:
            return
        if not directory.is_dir():
            self._pending_tree_path = None
            self._tree_path_retry_timer.stop()
            return

        # Expanding every already-known ancestor causes QFileSystemModel to load
        # the next level.  The target index can remain invalid for a short time
        # on newly mounted network volumes, so keep trying after directoryLoaded
        # as well as on a short timer.
        for parent in reversed(directory.parents):
            parent_index = self.directory_model.index(str(parent))
            if parent_index.isValid():
                self.directory_tree.expand(parent_index)

        target_index = self.directory_model.index(str(directory))
        if target_index.isValid():
            self.directory_tree.expand(target_index)
            self.directory_tree.setCurrentIndex(target_index)
            self.directory_tree.scrollTo(target_index)
            self._pending_tree_path = None
            self._tree_path_retry_timer.stop()
            return

        if not self._tree_path_retry_timer.isActive():
            self._tree_path_retry_timer.start(100)

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
        dialog.setWindowTitle(t("Ordner konnte nicht geöffnet werden"))
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(t("Der Ordner kann nicht geöffnet werden."))
        dialog.setInformativeText(f"{directory}\n\n{error}")
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.button(QMessageBox.StandardButton.Ok).setText(t("OK"))
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
                self._set_file_name_text(t("Ordner konnte nicht gelesen werden"))
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
        self._directory_loading_generation = generation
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
        self.set_status(STATUS_BUSY, "Suche nach Bildern …")
        self._update_navigation_buttons()
        self.current_image = None
        self.original_image = QImage()
        self._exif_oriented_image = QImage()
        self._update_view_actions()
        self._zoom_mode = "fit"
        self._zoom_factor = 1.0
        self.image_label.clear()
        self.image_label.resize(self.image_scroll_area.viewport().size())
        self.image_label.setText(t("Bild anklicken, um es anzuzeigen"))
        self._set_file_name_text(t("Suche nach Bildern …"))
        self._clipboard_changed()

        self.settings.setValue(LAST_DIRECTORY_KEY, str(directory.resolve(strict=False)))
        self.settings.sync()
        QTimer.singleShot(0, lambda: self._scan_directory_batch(generation))
        return True

    def _show_drop_hint(self) -> None:
        self.drop_hint_label.setText(t("Bild oder Ordner hier ablegen"))
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
            dialog.setWindowTitle(t("Ablage nicht möglich"))
            dialog.setIcon(QMessageBox.Icon.Warning)
            dialog.setText(t("Die abgelegten Elemente können nicht geöffnet werden."))
            dialog.setInformativeText(t("Technische Details: {detail}").format(detail=resolution.error_message))
            dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
            dialog.button(QMessageBox.StandardButton.Ok).setText(t("OK"))
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
            dialog.setWindowTitle(t("Nicht alle Elemente geöffnet"))
            dialog.setIcon(QMessageBox.Icon.Information)
            dialog.setText(
                t("Es wurden nur unterstützte Bilder aus dem Ordner des ersten Bildes geöffnet.")
            )
            dialog.setInformativeText(
                "Ignoriert:\n" + "\n".join(
                    str(path) for path in resolution.ignored_paths
                )
            )
            dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
            dialog.button(QMessageBox.StandardButton.Ok).setText(t("OK"))
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
            if self._directory_loading_generation == generation:
                self._directory_loading_generation = None
            self._set_file_name_text(t("Ordner konnte nicht vollständig gelesen werden"))
            self.set_status(STATUS_ERROR, "Ordner konnte nicht vollständig gelesen werden")
            self._set_thumbnail_size_actions_enabled(True)
            return

        self._set_file_name_text(t("Suche nach Bildern … ({count} gefunden)").format(count=len(self._pending_images)))
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
        self._directory_loading_generation = None
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
            self.set_status(STATUS_READY)
            return
        count = self.thumbnail_list.count()
        self._set_file_name_text(
            t("{count} Bild" if count == 1 else "{count} Bilder").format(count=count)
        )
        self.set_status(STATUS_READY)

    def _thumbnail_selected(
        self,
        item: QListWidgetItem | None,
        _previous_item: QListWidgetItem | None = None,
    ) -> None:
        if item is None:
            self._update_navigation_buttons()
            return
        if not self._confirm_manual_metadata_navigation():
            with QSignalBlocker(self.thumbnail_list):
                self.thumbnail_list.setCurrentItem(_previous_item)
            return
        self.current_image = Path(item.data(Qt.ItemDataRole.UserRole))
        self._set_file_name_text(self.current_image.name)
        self._load_current_image()
        self._update_information_panel()
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
        rotation_menu = context_menu.addMenu(t("Drehen"))
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

        directory_layout = self.directory_panel.layout()
        if isinstance(directory_layout, QVBoxLayout):
            directory_layout.insertWidget(1, self.directory_path_label)
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

    def _update_directory_heading(self) -> None:
        if self.current_directory is None:
            self.directory_heading_label.setText(t("Kein Ordner"))
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
            count_text = t("{count} Bild" if image_count == 1 else "{count} Bilder").format(count=image_count)
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
            self._status_full_text = t("Kein Bild ausgewählt")
            self.status_zoom_label.clear()
            self.status_zoom_label.setToolTip("")
            return

        resolved_path = self._resolved_sort_path(self.current_image)
        metadata = self._image_metadata_by_path.get(resolved_path, {})
        parts = [
            t("Bild {current} von {total}").format(current=current_row + 1, total=self.thumbnail_list.count()),
            t("{width} × {height} Pixel").format(width=self.original_image.width(), height=self.original_image.height()),
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
        zoom_text = t("Zoom {percent} %").format(percent=round(self._zoom_factor * 100))
        self.status_zoom_label.setText(zoom_text)

        tooltip_lines = [
            t("Datei: {name}").format(name=self.current_image.name),
            t("Pfad: {path}").format(path=self.current_image),
            t("Position: Bild {current} von {total}").format(current=current_row + 1, total=self.thumbnail_list.count()),
            t("Abmessungen: {width} × {height} Pixel").format(width=self.original_image.width(), height=self.original_image.height()),
        ]
        if self._current_file_size is not None:
            tooltip_lines.append(
                t("Dateigröße: {size}").format(size=format_file_size(self._current_file_size))
            )
        for key, label in (
            ("recording_time", "Aufnahmezeit: {value}"),
            ("camera", "Kamera: {value}"),
            ("lens", "Objektiv: {value}"),
            ("exposure", "Belichtungszeit"),
            ("aperture", "Blende"),
            ("focal_length", "Brennweite"),
            ("iso", "ISO {value}"),
        ):
            value = metadata.get(key)
            if value:
                tooltip_lines.append(t(label).format(value=value) if "{value}" in label else f"{label}: {value}")
        if metadata.get("gps_detail"):
            tooltip_lines.append(metadata["gps_detail"])
        tooltip_lines.append(zoom_text)
        complete_tooltip = "\n".join(tooltip_lines)
        self.status_zoom_label.setToolTip(complete_tooltip)

    def _refresh_status_info_text(self) -> None:
        self._update_bottom_control_bar_layout()

    def _load_current_image(self) -> None:
        self._hide_zoom_indicator()
        if self.current_image is None:
            self._exif_oriented_image = QImage()
            self._current_file_size = None
            self._clear_pdf_state()
            self._update_status_bar()
            self.set_status(STATUS_READY)
            return
        self.set_status(STATUS_BUSY, "Bild wird geladen …")
        if self.current_image.suffix.lower() in PDF_EXTENSIONS:
            result = load_pdf(self.current_image)
            if result.document is None:
                self._clear_pdf_state()
                self.original_image = QImage()
                self.image_label.setText(result.error or t("Die PDF konnte nicht geöffnet werden."))
                self._update_view_actions()
                self.set_status(STATUS_ERROR, "Datei konnte nicht geöffnet werden")
                return
            # QPdfLinkModel retains a reference to its document.  Detach it
            # before releasing the previous document; otherwise QtPdf can
            # access a deleted document while switching files.
            self._pdf_link_model.setDocument(None)
            self._pdf_document = result.document
            self._pdf_link_model.setDocument(result.document)
            self._pdf_link_model.setPage(0)
            self._pdf_page = 0
            self._pdf_render_size = QSize()
            self._reset_pdf_thumbnails()
            self._zoom_mode = "fit"
            self._zoom_factor = 1.0
            self._render_pdf_page()
            return
        if self._pdf_preview_mode:
            self._leave_pdf_preview()
        self._pdf_link_model.setDocument(None)
        self._pdf_document = None
        self._pdf_page = 0
        self._pdf_render_size = QSize()
        self._reset_pdf_thumbnails()
        self._update_pdf_page_navigation()
        self._sync_pdf_thumbnail_selection()
        self._schedule_visible_pdf_thumbnails()
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
            self.image_label.setText(t("Bild konnte nicht geladen werden"))
            self._update_view_actions()
            self._update_status_bar()
            self.set_status(STATUS_ERROR, "Bild konnte nicht geladen werden")
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
        self.set_status(STATUS_READY)

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
            self.image_label.setText(t("Die PDF enthält keine Seiten."))
            return False
        page = self._pdf_page if requested_page is None else requested_page
        page = max(0, min(page_count - 1, page))
        viewport = self.image_scroll_area.viewport().size()
        render_scale = self._zoom_factor if self._zoom_mode == "manual" else 1.0
        target = pdf_display_target_size(
            viewport,
            render_scale,
            self.image_scroll_area.viewport().devicePixelRatioF(),
        )
        self._set_pdf_thumbnail_busy(True)
        render_started = perf_counter()
        try:
            image = render_pdf_page_with_fallback(self._pdf_document, page, target)
        finally:
            self._set_pdf_thumbnail_busy(False)
        if image.isNull() or image.width() <= 0 or image.height() <= 0:
            self.original_image = QImage()
            self.image_label.clear()
            self.image_label.resize(self.image_scroll_area.viewport().size())
            self.image_label.setText(t("Die PDF-Seite konnte nicht gerendert werden"))
            self._update_pdf_page_navigation()
            return False
        self._pdf_page = page
        self._pdf_link_model.setPage(page)
        self._diagnose_pdf_links()
        device_pixel_ratio = max(
            1.0, self.image_scroll_area.viewport().devicePixelRatioF()
        )
        # ``render`` returns physical pixels.  Mark them accordingly before
        # creating the pixmap so Qt exposes the intended logical page size.
        image.setDevicePixelRatio(device_pixel_ratio)
        self.original_image = image
        self._pdf_render_size = image.size()
        if self._zoom_mode != "manual":
            self._zoom_mode = "fit"
            self._zoom_factor = 1.0
        self._render_current_image()
        page_points = self._pdf_document.pagePointSize(page)
        LOGGER.info(
            "PDF render: page=%s points=%sx%s zoom=%.3f viewport=%sx%s "
            "dpr=%.2f target_physical=%sx%s rendered=%sx%s displayed=%sx%s "
            "time_ms=%.1f",
            page + 1,
            round(page_points.width(), 2), round(page_points.height(), 2),
            self._zoom_factor,
            viewport.width(), viewport.height(),
            self.image_scroll_area.viewport().devicePixelRatioF(),
            target.width(), target.height(), image.width(), image.height(),
            self.image_label.width(), self.image_label.height(),
            (perf_counter() - render_started) * 1000,
        )
        self._set_file_name_text(self.current_image.name)
        self._update_pdf_page_navigation()
        if schedule_quality_refresh:
            self._schedule_pdf_quality_refresh()
        self.set_status(STATUS_READY)
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
        self._hide_pdf_fullscreen_navigation_hint()
        self._pdf_link_model.setDocument(None)
        self._pdf_document = None
        self._pdf_page = 0
        self._pdf_render_size = QSize()
        self._pdf_quality_refresh_pending = False
        self._reset_pdf_thumbnails()
        self._hide_fullscreen_pdf_thumbnails()
        self._update_pdf_page_navigation()

    def _diagnose_pdf_links(self) -> None:
        """Log the annotations Qt found, without attempting URL text detection."""
        if self._pdf_document is None:
            return
        links = self._pdf_link_model
        diagnostics = []
        row_count = links.rowCount(QModelIndex())
        for row in range(row_count):
            index = links.index(row, 0)
            link = links.data(index, QPdfLinkModel.Role.Link.value)
            diagnostics.append(
                {
                    "rectangle": links.data(index, QPdfLinkModel.Role.Rectangle.value),
                    "url": links.data(index, QPdfLinkModel.Role.Url.value),
                    "page": links.data(index, QPdfLinkModel.Role.Page.value),
                    "location": links.data(index, QPdfLinkModel.Role.Location.value),
                    "valid": bool(link and link.isValid()),
                }
            )
        LOGGER.debug(
            "PDF page %s: QPdfLinkModel rowCount=%s links=%s",
            self._pdf_page,
            row_count,
            diagnostics,
        )

    def _pdf_link_at_widget_position(self, global_position):
        """Return the real PDF link below a global mouse position, if any.

        QPdfLinkModel uses PDF page points.  The rendered pixmap fills
        ``image_label`` exactly, so its size is the visible page rectangle even
        when the scroll area centers it, is zoomed, or is fullscreen.
        """
        if self._pdf_document is None or self.original_image.isNull():
            return None
        label_position = self.image_label.mapFromGlobal(global_position)
        label_rect = self.image_label.rect()
        if not label_rect.contains(label_position):
            return None
        page_size = self._pdf_document.pagePointSize(self._pdf_page)
        if page_size.isEmpty() or label_rect.width() <= 0 or label_rect.height() <= 0:
            return None
        page_position = QPointF(
            label_position.x() * page_size.width() / label_rect.width(),
            label_position.y() * page_size.height() / label_rect.height(),
        )
        link = self._pdf_link_model.linkAt(page_position)
        # Qt 6.8 reports ``isValid() == False`` for URI actions even though
        # the model exposes their URL and rectangle.  A real target is the
        # reliable criterion across Qt versions; isValid() remains logged.
        if link.isValid() or not link.url().isEmpty() or link.page() >= 0:
            return link
        return None

    @staticmethod
    def _pdf_link_tooltip(link) -> str:
        url = link.url()
        scheme = url.scheme().lower()
        if scheme in {"http", "https"}:
            return url.toString()
        if scheme == "mailto":
            return url.toString()[len("mailto:") :].split("?", 1)[0]
        if link.page() >= 0:
            return t("Seite {page}").format(page=link.page() + 1)
        return ""

    def _update_pdf_link_hover(self, global_position) -> None:
        link = self._pdf_link_at_widget_position(global_position)
        if link is None:
            self.image_label.unsetCursor()
            QToolTip.hideText()
            return
        self.image_label.setCursor(Qt.CursorShape.PointingHandCursor)
        tooltip = self._pdf_link_tooltip(link)
        if tooltip:
            QToolTip.showText(global_position, tooltip, self.image_label)

    def _open_pdf_link(self, link) -> bool:
        """Follow an embedded PDF link, allowing only safe external schemes."""
        url = link.url()
        scheme = url.scheme().lower()
        if scheme in {"http", "https", "mailto"}:
            return QDesktopServices.openUrl(url)
        if scheme:
            return False
        target_page = link.page()
        if target_page >= 0:
            return self._render_pdf_page(target_page)
        return False

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
                self.image_scroll_area.viewport().size(),
                render_scale,
                self.image_scroll_area.viewport().devicePixelRatioF(),
            ),
        )
        if pdf_render_size_matches(self._pdf_render_size, required_size):
            return
        self._render_pdf_page(
            self._pdf_page,
            schedule_quality_refresh=False,
        )

    def _update_pdf_page_navigation(self) -> None:
        document = self._pdf_document
        page_count = document.pageCount() if document is not None else 0
        is_pdf = page_count > 0
        self.pdf_page_navigation.setVisible(
            is_pdf
            and page_count > 1
            and not getattr(self, "_fullscreen_mode", False)
        )
        self.previous_pdf_page_action.setEnabled(is_pdf and self._pdf_page > 0)
        self.next_pdf_page_action.setEnabled(is_pdf and self._pdf_page + 1 < page_count)
        if not is_pdf:
            self.pdf_page_label.clear()
            self.previous_pdf_page_button.setEnabled(False)
            self.next_pdf_page_button.setEnabled(False)
            return
        self.pdf_page_label.setText(
            t("Seite {page} von {pages}").format(
                page=self._pdf_page + 1, pages=page_count
            )
        )
        self.previous_pdf_page_button.setEnabled(self._pdf_page > 0)
        self.next_pdf_page_button.setEnabled(self._pdf_page + 1 < page_count)
        self._sync_pdf_thumbnail_selection()

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
        dialog.setWindowTitle(t("Drehung speichern"))
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText(
            t("Das dauerhafte Drehen animierter GIF-Dateien wird derzeit nicht unterstützt.")
        )
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.button(QMessageBox.StandardButton.Ok).setText(t("OK"))
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
            t("Gedrehte Kopie speichern"),
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
                t("Für das Überschreiben der Originaldatei verwenden Sie bitte „Drehung im Original speichern …“.")
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
        dialog.setWindowTitle(t("Datei überschreiben"))
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(t("Die gewählte Datei ist bereits vorhanden."))
        dialog.setInformativeText(str(destination))
        overwrite_button = dialog.addButton(
            t("Überschreiben"), QMessageBox.ButtonRole.AcceptRole
        )
        cancel_button = dialog.addButton(
            t("Abbrechen"), QMessageBox.ButtonRole.RejectRole
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
                t("Die Originaldatei ist schreibgeschützt oder es fehlen Schreibrechte.")
            )
            return
        dialog = QMessageBox(self.window)
        dialog.setWindowTitle(t("Drehung im Original speichern"))
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(
            t("Möchtest du die Drehung dauerhaft in der Originaldatei speichern?\n\nDie Bilddaten werden neu gespeichert. Dieser Vorgang kann in BildBlick nicht direkt rückgängig gemacht werden.")
        )
        dialog.setInformativeText(
            f"Dateiname: {image_path.name}\n"
            f"Dateipfad: {image_path}\n"
            f"Aktuelle Drehung: {self._display_rotation_description()}"
        )
        overwrite_button = dialog.addButton(
            t("Original überschreiben"), QMessageBox.ButtonRole.DestructiveRole
        )
        cancel_button = dialog.addButton(
            t("Abbrechen"), QMessageBox.ButtonRole.RejectRole
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
        dialog.setWindowTitle(t("Drehung konnte nicht gespeichert werden"))
        dialog.setIcon(QMessageBox.Icon.Critical)
        dialog.setText(t("Das gedrehte Bild konnte nicht gespeichert werden."))
        dialog.setInformativeText(detail)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.button(QMessageBox.StandardButton.Ok).setText(t("OK"))
        self._style_message_box(dialog)
        dialog.exec()

    def _show_metadata_save_warning(self, warnings: list[str]) -> None:
        dialog = QMessageBox(self.window)
        dialog.setWindowTitle(t("Bild mit eingeschränkten Metadaten gespeichert"))
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(
            t("Das Bild wurde gespeichert, einige Metadaten konnten jedoch nicht vollständig erhalten werden.")
        )
        dialog.setDetailedText("\n".join(warnings))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.button(QMessageBox.StandardButton.Ok).setText(t("OK"))
        self._style_message_box(dialog)
        dialog.exec()

    def _show_rotation_saved_confirmation(self) -> None:
        dialog = QMessageBox(self.window)
        dialog.setWindowTitle(t("Drehung gespeichert"))
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText(t("Die Drehung wurde im Original gespeichert."))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.button(QMessageBox.StandardButton.Ok).setText(t("OK"))
        self._style_message_box(dialog)
        dialog.exec()

    def _render_current_image(self) -> None:
        self._image_render_pending = False
        if self.original_image.isNull():
            return
        viewport_size = self.image_scroll_area.viewport().size()
        if viewport_size.width() <= 1 or viewport_size.height() <= 1:
            return
        if self._pdf_document is not None:
            # The PDF renderer already produced this pixmap at the visible
            # page size.  Do not send small text through the generic image
            # downscaler, which would soften its rasterized edges.
            pixmap = QPixmap.fromImage(self.original_image)
            logical_size = pixmap.deviceIndependentSize().toSize()
            if logical_size.isEmpty():
                logical_size = self.original_image.size()
            self.image_label.resize(logical_size)
            self.image_label.setPixmap(pixmap)
            if self._zoom_mode == "fit":
                self.image_scroll_area.horizontalScrollBar().setValue(0)
                self.image_scroll_area.verticalScrollBar().setValue(0)
            self._update_status_bar()
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
        self._zoom_factor = 1.0
        if self._pdf_document is not None:
            self._render_pdf_page(schedule_quality_refresh=False)
        else:
            self._render_current_image()
        self._show_zoom_indicator()

    def _show_image_at_actual_size(self) -> None:
        if self.original_image.isNull():
            return
        self._zoom_mode = "manual"
        self._zoom_factor = 1.0
        if self._pdf_document is not None:
            self._render_pdf_page(schedule_quality_refresh=False)
        else:
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
        if self._pdf_document is not None:
            self._render_pdf_page(schedule_quality_refresh=False)
        else:
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
        if (
            not self._fullscreen_mode
            or self._pdf_document is not None
            or self._fullscreen_tooltip_visible
        ):
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
        self._apply_thumbnail_position(save=False)
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
        self._sync_quick_switches()
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
        self._show_fullscreen_pdf_thumbnails()
        self._bottom_control_bar_active = False
        self.bottom_control_bar_hide_timer.stop()
        self.bottom_control_bar_start_timer.stop()
        self.bottom_control_bar.hide()
        self.status_bar.hide()
        if self._pdf_document is not None:
            self._detach_pdf_page_navigation()
        self._update_pdf_page_navigation()
        self.window.menuBar().hide()
        self.splitter.handle(1).hide()
        self.right_splitter.handle(1).hide()
        self.splitter.setSizes([0, max(1, self.splitter.width())])
        self.right_splitter.setSizes([0, max(1, self.right_splitter.width())])
        self.window.setStyleSheet("background-color: black;")
        self.image_label.setStyleSheet("background-color: black;")
        self.window.showFullScreen()
        # Qt can restore child visibility during the fullscreen transition.
        # Reassert the PDF-only fullscreen contract after that event cycle.
        if self._pdf_document is not None:
            QTimer.singleShot(0, self._hide_normal_controls_for_pdf_fullscreen)
        # The list can be temporarily not visible while the window changes
        # state.  Start the lazy queue again once Qt has processed that change.
        QTimer.singleShot(0, self._schedule_visible_pdf_thumbnails)
        self._schedule_image_render()
        if self._pdf_document is not None:
            self._show_pdf_fullscreen_navigation_hint()
            QTimer.singleShot(0, self._position_pdf_fullscreen_navigation_hint)
        else:
            self._show_fullscreen_tooltip(QCursor.pos())
        self._position_slideshow_overlays()
        self._restart_slideshow_cursor_timer()

    def _leave_fullscreen(self) -> None:
        if not self._fullscreen_mode:
            return

        self._fullscreen_mode = False
        self._hide_pdf_fullscreen_navigation_hint()
        self._hide_fullscreen_pdf_thumbnails()
        self._restore_slideshow_cursor()
        self.fullscreen_tooltip_timer.stop()
        self._hide_fullscreen_tooltip()
        self.fullscreen_action.setChecked(False)
        self._sync_quick_switches()
        self.window.setStyleSheet(self._normal_window_style)
        self.image_label.setStyleSheet(self._normal_image_style)
        central_layout = self.window.centralWidget().layout()
        if central_layout is not None and self._normal_central_margins is not None:
            central_layout.setContentsMargins(*self._normal_central_margins)

        if not self._pdf_preview_mode:
            self.directory_panel.show()
            self._apply_thumbnail_position(save=False)
        self._show_bottom_control_bar()
        self.bottom_control_bar_start_timer.start(BOTTOM_CONTROL_BAR_START_DELAY_MS)
        self._restore_pdf_page_navigation_to_layout()
        self._update_pdf_page_navigation()
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

    def _hide_normal_controls_for_pdf_fullscreen(self) -> None:
        if self._fullscreen_mode and self._pdf_document is not None:
            self.bottom_control_bar_hide_timer.stop()
            self.bottom_control_bar_start_timer.stop()
            self.bottom_control_bar.hide()
            self.status_bar.hide()

    def eventFilter(self, watched, event) -> bool:
        if (
            hasattr(self, "pdf_thumbnail_viewport")
            and watched is self.pdf_thumbnail_viewport
            and event.type() == QEvent.Type.Resize
        ):
            QTimer.singleShot(0, self._update_pdf_print_checkbox_positions)
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
        if (
            hasattr(self, "information_scroll_area")
            and watched is self.information_scroll_area.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            QTimer.singleShot(0, self._update_information_column_widths)
        if watched in getattr(self, "_bottom_control_bar_watch_widgets", ()):
            if watched is self.window and event.type() == QEvent.Type.Resize:
                self._update_bottom_control_bar_layout()
            if event.type() in (QEvent.Type.Enter, QEvent.Type.MouseMove):
                global_position = (
                    event.globalPosition().toPoint()
                    if event.type() == QEvent.Type.MouseMove
                    else QCursor.pos()
                )
                self._update_bottom_control_bar_visibility(global_position)
            elif event.type() == QEvent.Type.Leave:
                self._bottom_control_bar_active = False
                self._schedule_bottom_control_bar_hide()
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
        if (
            getattr(self, "_fullscreen_mode", False)
            and self._pdf_document is None
            and watched in image_widgets
        ):
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
        if (
            getattr(self, "_fullscreen_mode", False)
            and self._pdf_document is not None
            and watched in image_widgets
        ):
            # The PDF navigation hint is a dedicated overlay.  Suppress both
            # native widget tooltips and link-hover tooltips here; otherwise a
            # MouseMove can still create a second, empty-looking tooltip box.
            if event.type() == QEvent.Type.ToolTip:
                QToolTip.hideText()
                return True
            if event.type() in (QEvent.Type.Enter, QEvent.Type.MouseMove):
                QToolTip.hideText()
        if watched in image_widgets and event.type() == QEvent.Type.ContextMenu:
            self._restore_slideshow_cursor()
            self._show_image_context_menu(event.globalPos())
            self._restart_slideshow_cursor_timer()
            return True
        if watched in image_widgets and event.type() == QEvent.Type.Leave:
            self.image_label.unsetCursor()
            QToolTip.hideText()
        elif (
            watched in image_widgets
            and event.type() == QEvent.Type.MouseMove
            and not (
                getattr(self, "_fullscreen_mode", False)
                and self._pdf_document is not None
            )
        ):
            self._update_pdf_link_hover(event.globalPosition().toPoint())
        if (
            watched is self.image_scroll_area.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            if self.drop_hint_label.isVisible():
                self.drop_hint_label.setGeometry(
                    self.image_scroll_area.viewport().rect()
                )
            self._position_zoom_indicator()
            self._position_pdf_fullscreen_navigation_hint()
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
            pdf_link = self._pdf_link_at_widget_position(
                event.globalPosition().toPoint()
            )
            if pdf_link is not None:
                self._open_pdf_link(pdf_link)
                return True
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
            t("Die angegebene Datei hat kein unterstütztes Bild- oder PDF-Format:\n{path}").format(path=candidate),
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
            None, [], None, [], t("Es wurden keine Dateien oder Ordner abgelegt.")
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
                t("Bitte legen Sie entweder einen einzelnen Ordner oder Bilddateien ab."),
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
    dialog.setText(t("Der übergebene Pfad konnte nicht geöffnet werden."))
    dialog.setInformativeText(message)
    dialog.setStandardButtons(QMessageBox.StandardButton.Close)
    dialog.button(QMessageBox.StandardButton.Close).setText(t("Schließen"))
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
    # A release binary must be able to report its version in headless shells.
    # QCommandLineParser normally handles this only after QApplication has
    # selected a platform plugin.
    if "--version" in sys.argv[1:]:
        print(f"{APP_NAME} {APP_VERSION}")
        return 0
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
        startup_error = t("Bitte nur eine Bilddatei oder einen Ordner angeben.")
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
