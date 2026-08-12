import hashlib
import os
import threading
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from PIL import Image as PillowImage
from PIL import ImageOps
from send2trash import send2trash
from PySide6.QtCore import QObject, QRunnable, QSettings, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QButtonGroup,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QAbstractItemView,
    QListWidget,
    QListWidgetItem,
    QComboBox,
    QFrame,
    QGridLayout,
)
from i18n import t


HASH_BLOCK_SIZE = 1024 * 1024
PREVIEW_SIZE = QSize(72, 54)
TRASH_DEBUG = False
DUPLICATE_COLUMN_WIDTHS_KEY = "duplicateFinder/columnWidths"
DEFAULT_COLUMN_WIDTHS = (260, 360, 105, 150, 130, 180, 170, 170)
MINIMUM_COLUMN_WIDTHS = (150, 180, 90, 120, 120, 150, 145, 145)
VISUAL_THRESHOLDS = {"strict": 2, "normal": 5, "generous": 8}


def dhash(path: Path) -> int:
    """Return a 64-bit difference hash after EXIF orientation correction."""
    with PillowImage.open(path) as image:
        gray = ImageOps.exif_transpose(image).convert("L").resize((9, 8))
        pixels = list(gray.get_flattened_data())
    value = 0
    for row in range(8):
        for column in range(8):
            value = (value << 1) | (pixels[row * 9 + column] > pixels[row * 9 + column + 1])
    return value


def hamming_distance(first: int, second: int) -> int:
    return (first ^ second).bit_count()


def _trash_debug(message: str) -> None:
    if TRASH_DEBUG:
        print(f"[BildBlick Papierkorb] {message}", flush=True)


def _same_content(first: Path, second: Path, cancel_event: threading.Event) -> bool:
    with first.open("rb") as left, second.open("rb") as right:
        while not cancel_event.is_set():
            left_block = left.read(HASH_BLOCK_SIZE)
            right_block = right.read(HASH_BLOCK_SIZE)
            if left_block != right_block:
                return False
            if not left_block:
                return True
    return False


def _hash_file(path: Path, cancel_event: threading.Event) -> str | None:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while not cancel_event.is_set():
            block = source.read(HASH_BLOCK_SIZE)
            if not block:
                return digest.hexdigest()
            digest.update(block)
    return None


def _is_readable_image(path: Path) -> bool:
    try:
        with PillowImage.open(path) as image:
            image.verify()
        return True
    except Exception:
        return False


def normalized_filename(path: Path) -> str:
    """Platform-friendly, Unicode-normalized case-insensitive file name."""
    return unicodedata.normalize("NFC", path.name).casefold()


def image_details(path: Path) -> tuple[str, str]:
    """Return display-ready dimensions and capture date, without failing search."""
    try:
        with PillowImage.open(path) as image:
            width, height = image.size
            exif = image.getexif()
            raw_date = exif.get(36867) or exif.get(36868) or exif.get(306)
        capture = ""
        if raw_date:
            try: capture = datetime.strptime(str(raw_date), "%Y:%m:%d %H:%M:%S").strftime("%d.%m.%Y")
            except ValueError: capture = str(raw_date)
        return f"{width} × {height} px", capture
    except Exception:
        return "", ""


def find_duplicates(
    roots: list[Path] | Path,
    recursive: bool,
    extensions: set[str],
    cancel_event: threading.Event,
    progress_callback=None,
    total_callback=None,
    search_exact: bool = True,
    search_name: bool = False,
    search_visual: bool = False,
    visual_threshold: int = VISUAL_THRESHOLDS["normal"],
) -> dict:
    roots = [roots] if isinstance(roots, Path) else list(roots)
    paths: list[Path] = []
    seen_paths: set[Path] = set()
    missing_roots: list[Path] = []
    skipped = 0
    def record_walk_error(_error) -> None:
        nonlocal skipped
        skipped += 1

    for root in roots:
        root = root.resolve(strict=False)
        if not root.is_dir():
            missing_roots.append(root); continue
        try:
            if recursive:
                for directory, _subdirs, files in os.walk(root, onerror=record_walk_error):
                    if cancel_event.is_set(): return {"cancelled": True}
                    for name in files:
                        path = Path(directory) / name
                        if not name.startswith("._") and path.suffix.lower() in extensions:
                            resolved = path.resolve(strict=False)
                            if resolved not in seen_paths: seen_paths.add(resolved); paths.append(resolved)
            else:
                for entry in os.scandir(root):
                    if cancel_event.is_set(): return {"cancelled": True}
                    try:
                        path = Path(entry.path).resolve(strict=False)
                        if not entry.name.startswith("._") and entry.is_file() and path.suffix.lower() in extensions and path not in seen_paths:
                            seen_paths.add(path); paths.append(path)
                    except OSError: skipped += 1
        except OSError:
            skipped += 1

    paths.sort(key=lambda path: str(path).casefold())
    if total_callback:
        total_callback(len(paths))
    by_size: dict[int, list[Path]] = defaultdict(list)
    metadata: dict[Path, tuple[int, float, str, str]] = {}
    checked = 0
    for path in paths:
        if cancel_event.is_set():
            return {"cancelled": True}
        try:
            stat = path.stat()
            if not _is_readable_image(path):
                raise OSError("Bild ist nicht lesbar")
            dimensions, capture_date = image_details(path)
            metadata[path] = (stat.st_size, stat.st_mtime, dimensions, capture_date)
            by_size[stat.st_size].append(path)
        except (OSError, ValueError):
            skipped += 1
        checked += 1
        if progress_callback:
            progress_callback(checked)

    exact_groups: list[list[Path]] = []
    for same_size in by_size.values() if search_exact else ():
        if cancel_event.is_set():
            return {"cancelled": True}
        if len(same_size) < 2:
            continue
        by_hash: dict[str, list[Path]] = defaultdict(list)
        for path in same_size:
            try:
                file_hash = _hash_file(path, cancel_event)
                if file_hash is not None:
                    by_hash[file_hash].append(path)
            except OSError:
                skipped += 1
        for same_hash in by_hash.values():
            if len(same_hash) < 2:
                continue
            confirmed: list[list[Path]] = []
            for path in same_hash:
                if cancel_event.is_set():
                    return {"cancelled": True}
                try:
                    for group in confirmed:
                        if _same_content(group[0], path, cancel_event):
                            group.append(path)
                            break
                    else:
                        confirmed.append([path])
                except OSError:
                    skipped += 1
            exact_groups.extend(group for group in confirmed if len(group) >= 2)

    named: dict[str, list[Path]] = defaultdict(list)
    if search_name:
        for path in metadata:
            named[normalized_filename(path)].append(path)
    name_groups = [group for group in named.values() if len(group) >= 2]
    visual_groups: list[tuple[list[Path], str, int]] = []
    if search_visual:
        hashes: dict[Path, int] = {}
        for path in metadata:
            try: hashes[path] = dhash(path)
            except Exception: skipped += 1
        ungrouped = set(hashes)
        while ungrouped:
            reference = ungrouped.pop()
            group = [reference]
            for path in list(ungrouped):
                if hamming_distance(hashes[reference], hashes[path]) <= visual_threshold:
                    group.append(path); ungrouped.remove(path)
            if len(group) >= 2:
                distances = [
                    hamming_distance(hashes[reference], hashes[path])
                    for path in group[1:]
                ]
                visual_groups.append((group, "visual_equal" if all(distance == 0 for distance in distances) else "visual_similar", max(distances)))
    reasons: dict[tuple[Path, ...], set[str]] = {}
    visual_distances: dict[tuple[Path, ...], int] = {}
    for label, candidates in (("exact", exact_groups), ("name", name_groups)):
        for group in candidates:
            key = tuple(sorted(group, key=lambda path: str(path).casefold()))
            reasons.setdefault(key, set()).add(label)
    for group, label, distance in visual_groups:
        key = tuple(sorted(group, key=lambda path: str(path).casefold()))
        reasons.setdefault(key, set()).add(label)
        visual_distances[key] = distance
    groups = list(reasons)

    duplicate_files = sum(len(group) for group in groups)
    reclaimable = sum(metadata[group[0]][0] * (len(group) - 1) for group in groups)
    return {
        "cancelled": False,
        "examined": len(paths),
        "skipped": skipped,
        "groups": groups,
        "metadata": metadata,
        "duplicate_files": duplicate_files,
        "reclaimable": reclaimable,
        "missing_roots": missing_roots,
        "group_reasons": {group: reasons[group] for group in groups},
        "group_visual_distances": {group: visual_distances[group] for group in groups if group in visual_distances},
    }


class DuplicateSearchSignals(QObject):
    total = Signal(int)
    progress = Signal(int)
    finished = Signal(object)


class DuplicateSearchTask(QRunnable):
    def __init__(self, roots: list[Path], recursive: bool, extensions: set[str], cancel_event, search_exact=True, search_name=False, search_visual=False, visual_threshold=5):
        super().__init__()
        self.roots = roots
        self.recursive = recursive
        self.extensions = extensions
        self.cancel_event = cancel_event
        self.search_exact, self.search_name, self.search_visual, self.visual_threshold = search_exact, search_name, search_visual, visual_threshold
        self.signals = DuplicateSearchSignals()

    def run(self) -> None:
        result = find_duplicates(
            self.roots,
            self.recursive,
            self.extensions,
            self.cancel_event,
            self.signals.progress.emit,
            self.signals.total.emit,
            self.search_exact, self.search_name, self.search_visual, self.visual_threshold,
        )
        try:
            self.signals.finished.emit(result)
        except RuntimeError:
            pass


class DuplicateFinderDialog(QDialog):
    def __init__(
        self,
        parent,
        initial_directory: Path,
        extensions: set[str],
        files_trashed_callback=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(t("Doppelte Bilder finden"))
        self.setMinimumWidth(1100)
        self.resize(1600, 650)
        self._roots = [initial_directory.resolve(strict=False)]
        self._extensions = set(extensions)
        self._cancel_event: threading.Event | None = None
        self._task = None
        self._searching = False
        self._trash_in_progress = False
        self._confirming_trash = False
        self._files_trashed_callback = files_trashed_callback
        self._result = None
        self._group_controls: list[dict] = []
        self._freed_bytes = 0
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._column_resize_guard = False
        self._search_total = 0
        self._search_checked = 0
        self._settings = QSettings("BildBlick", "BildBlick")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(18)

        folders = QWidget(); folders_layout = QVBoxLayout(folders); folders_layout.setContentsMargins(0, 0, 0, 0)
        folders_layout.addWidget(QLabel(t("Suchordner")))
        folder_content = QHBoxLayout(); self.folder_list = QListWidget(); self.folder_list.addItem(str(self._roots[0])); self.folder_list.setMinimumHeight(105); folder_content.addWidget(self.folder_list, 1)
        folder_buttons = QVBoxLayout(); self.select_button = QPushButton(t("Ordner hinzufügen …")); self.select_button.clicked.connect(self._select_directory)
        self.remove_folder_button = QPushButton(t("Entfernen")); self.remove_folder_button.clicked.connect(self._remove_selected_directory); self.remove_folder_button.setEnabled(False)
        folder_buttons.addWidget(self.select_button); folder_buttons.addWidget(self.remove_folder_button); folder_buttons.addStretch(); folder_content.addLayout(folder_buttons)
        folders_layout.addLayout(folder_content); self.recursive_checkbox = QCheckBox(t("Unterordner einbeziehen")); folders_layout.addWidget(self.recursive_checkbox)
        self.folder_list.itemSelectionChanged.connect(lambda: self.remove_folder_button.setEnabled(bool(self.folder_list.selectedItems())))
        top.addWidget(folders, 4)

        types = QWidget(); types_layout = QVBoxLayout(types); types_layout.setContentsMargins(0, 0, 0, 0); types_layout.addWidget(QLabel(t("Sucharten")))
        self.name_checkbox = QCheckBox(t("Gleicher Dateiname")); self.exact_checkbox = QCheckBox(t("Exakt identischer Inhalt")); self.exact_checkbox.setChecked(True); self.visual_checkbox = QCheckBox(t("Visuell gleiche/ähnliche Bilder"))
        for checkbox in (self.name_checkbox, self.exact_checkbox, self.visual_checkbox): types_layout.addWidget(checkbox)
        types_layout.addStretch(); top.addWidget(types, 3)

        similarity_box = QWidget(); similarity_layout = QVBoxLayout(similarity_box); similarity_layout.setContentsMargins(0, 0, 0, 0); similarity_layout.addWidget(QLabel(t("Ähnlichkeit (dHash)")))
        self.similarity = QComboBox(); self.similarity.addItem(t("Streng"), "strict"); self.similarity.addItem(t("Normal"), "normal"); self.similarity.addItem(t("Großzügig"), "generous"); self.similarity.setCurrentIndex(1); self.similarity.setEnabled(False); self.visual_checkbox.toggled.connect(self.similarity.setEnabled)
        self.threshold_label = QLabel(); similarity_layout.addWidget(self.similarity); similarity_layout.addWidget(self.threshold_label); similarity_layout.addStretch(); self.similarity.currentIndexChanged.connect(self._update_threshold_label); self._update_threshold_label()
        top.addWidget(similarity_box, 2)

        actions = QVBoxLayout(); self.start_button = QPushButton(t("Suche starten")); self.start_button.setMinimumHeight(48); self.start_button.clicked.connect(self._start_search); actions.addWidget(self.start_button)
        self.cancel_button = QPushButton(t("Abbrechen")); self.cancel_button.clicked.connect(self._cancel_or_close); actions.addWidget(self.cancel_button); actions.addStretch(); top.addLayout(actions, 2)
        layout.addLayout(top)

        self.status_panel = QFrame(); self.status_panel.setObjectName("duplicateSearchStatus"); self.status_panel.setFrameShape(QFrame.Shape.StyledPanel); self.status_panel.setStyleSheet("QFrame#duplicateSearchStatus { border: 1px solid #198a35; border-radius: 12px; background: #f5fbf5; }")
        status_layout = QGridLayout(self.status_panel); status_layout.setContentsMargins(18, 14, 18, 14); status_layout.setColumnStretch(1, 3); status_layout.setColumnStretch(2, 2)
        self.activity_icon = QLabel("◔"); self.activity_icon.setAlignment(Qt.AlignmentFlag.AlignCenter); self.activity_icon.setStyleSheet("font-size: 42px; color: #16833a;"); status_layout.addWidget(self.activity_icon, 0, 0, 2, 1)
        self.status_title = QLabel(t("BildBlick sucht nach Duplikaten …")); self.status_title.setStyleSheet("font-size: 20px; font-weight: bold; color: #087020;"); status_layout.addWidget(self.status_title, 0, 1)
        self.status_hint = QLabel(t("Bitte warten – dies kann je nach Anzahl der Dateien einige Zeit dauern.")); status_layout.addWidget(self.status_hint, 1, 1)
        self.phase_label = QLabel(); self.phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter); status_layout.addWidget(self.phase_label, 0, 2, 2, 1)
        self.status_numbers = QLabel(); status_layout.addWidget(self.status_numbers, 0, 3, 2, 1)
        self.checked_label = QLabel(t("0 Dateien geprüft")); self.checked_label.hide()
        self._activity_frames = ("◔", "◑", "◕", "◐"); self._activity_frame = 0; self._activity_timer = QTimer(self); self._activity_timer.setInterval(180); self._activity_timer.timeout.connect(self._advance_activity_icon)
        self.status_panel.hide(); layout.addWidget(self.status_panel)

        self.result_overview = QLabel(t("Noch keine Suche ausgeführt.")); self.result_overview.setWordWrap(True); layout.addWidget(self.result_overview)

        self.results = QTreeWidget()
        self.results.setHeaderLabels(
            (
                t("Datei / Gruppe"), t("Pfad"), t("Größe"), t("Abmessungen"), t("Aufnahmedatum"), t("Geändert"),
                t("Behalten"), t("Papierkorb"),
            )
        )
        self.results.setIconSize(PREVIEW_SIZE)
        self.results.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.results.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.results.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        header = self.results.header()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(min(MINIMUM_COLUMN_WIDTHS))
        for column in range(len(DEFAULT_COLUMN_WIDTHS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        self._restore_column_widths()
        header.sectionResized.connect(self._column_resized)
        header.sectionHandleDoubleClicked.connect(self._resize_column_to_contents)
        layout.addWidget(self.results, 1)
        self.summary = QLabel(t("Noch keine Suche ausgeführt.")); self.summary.setWordWrap(True)
        self.safety_notice = QLabel(t("Es wurden keine Dateien verändert.")); self.safety_notice.setObjectName("safetyNotice"); self.safety_notice.hide()

        selection_row = QHBoxLayout()
        selection_row.addWidget(self.summary, 1)
        self.clear_all_button = QPushButton(t("Alle Markierungen aufheben"))
        self.clear_all_button.setEnabled(False)
        self.clear_all_button.clicked.connect(self._clear_all_marks)
        selection_row.addWidget(self.clear_all_button)
        self.trash_selected_button = QPushButton(
            t("Ausgewählte Dateien in den Papierkorb verschieben")
        )
        self.trash_selected_button.setMinimumWidth(self.trash_selected_button.sizeHint().width())
        self.trash_selected_button.setEnabled(False)
        self.trash_selected_button.setToolTip(
            t("Markiere zuerst mindestens eine Datei in der Spalte Papierkorb.")
        )
        self.trash_selected_button.clicked.connect(
            self._move_selected_duplicates_to_trash
        )
        selection_row.addWidget(self.trash_selected_button)
        self.close_button = QPushButton(t("Schließen")); self.close_button.clicked.connect(self.close)
        selection_row.addWidget(self.close_button)
        layout.addLayout(selection_row)

    def _restore_column_widths(self) -> None:
        stored = self._settings.value(DUPLICATE_COLUMN_WIDTHS_KEY)
        widths = DEFAULT_COLUMN_WIDTHS
        if isinstance(stored, (list, tuple)) and len(stored) == len(widths):
            try:
                widths = tuple(int(value) for value in stored)
            except (TypeError, ValueError):
                widths = DEFAULT_COLUMN_WIDTHS
        for column, width in enumerate(widths):
            self.results.setColumnWidth(
                column, max(MINIMUM_COLUMN_WIDTHS[column], width)
            )

    def _update_threshold_label(self) -> None:
        threshold = VISUAL_THRESHOLDS[str(self.similarity.currentData())]
        self.threshold_label.setText(t("Hamming-Distanz ≤ {threshold}").format(threshold=threshold))

    def _set_search_status(self, *, phase: str, examined: int = 0, candidates: int = 0, skipped: int = 0) -> None:
        self.phase_label.setText(t("Phase: {phase}").format(phase=phase))
        self.status_numbers.setText(
            t("Untersucht: {count} Dateien\nGefunden: {candidates} Kandidaten\nÜbersprungen (fehlerhaft): {skipped}").format(
                count=examined, candidates=candidates, skipped=skipped
            )
        )

    def _start_activity_animation(self) -> None:
        self._activity_frame = 0
        self.activity_icon.setText(self._activity_frames[0])
        self._activity_timer.start()

    def _stop_activity_animation(self) -> None:
        self._activity_timer.stop()

    def _advance_activity_icon(self) -> None:
        self._activity_frame = (self._activity_frame + 1) % len(self._activity_frames)
        self.activity_icon.setText(self._activity_frames[self._activity_frame])

    def _column_resized(self, column: int, _old_size: int, new_size: int) -> None:
        if self._column_resize_guard:
            return
        minimum = MINIMUM_COLUMN_WIDTHS[column]
        if new_size < minimum:
            self._column_resize_guard = True
            try:
                self.results.header().resizeSection(column, minimum)
            finally:
                self._column_resize_guard = False
        widths = [
            max(MINIMUM_COLUMN_WIDTHS[index], self.results.columnWidth(index))
            for index in range(len(DEFAULT_COLUMN_WIDTHS))
        ]
        self._settings.setValue(DUPLICATE_COLUMN_WIDTHS_KEY, widths)

    def _resize_column_to_contents(self, column: int) -> None:
        self.results.resizeColumnToContents(column)
        if self.results.columnWidth(column) < MINIMUM_COLUMN_WIDTHS[column]:
            self.results.setColumnWidth(column, MINIMUM_COLUMN_WIDTHS[column])

    def _select_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, t("Ordner hinzufügen …"), str(self._roots[0]) if self._roots else ""
        )
        if selected:
            path = Path(selected).resolve(strict=False)
            if path not in self._roots:
                self._roots.append(path); self.folder_list.addItem(str(path))

    def _remove_selected_directory(self) -> None:
        row = self.folder_list.currentRow()
        if row >= 0:
            self._roots.pop(row); self.folder_list.takeItem(row)

    def _start_search(self) -> None:
        if self._searching or self._trash_in_progress:
            return
        self.results.clear()
        self._group_controls = []
        self._result = None
        self._freed_bytes = 0
        self.safety_notice.setText(t("Es wurden keine Dateien verändert."))
        self.clear_all_button.setEnabled(False)
        self.trash_selected_button.setEnabled(False)
        self.summary.setText(t("Suche läuft …"))
        self.result_overview.setText(t("Suche läuft …"))
        self.checked_label.setText(t("Dateien werden ermittelt …"))
        self._search_total = 0
        self._search_checked = 0
        self.start_button.setEnabled(False)
        self.select_button.setEnabled(False)
        self.recursive_checkbox.setEnabled(False)
        self.cancel_button.setText(t("Abbrechen"))
        self._searching = True
        self._cancel_event = threading.Event()
        phase = t("Visuelle Ähnlichkeit prüfen") if self.visual_checkbox.isChecked() else t("Dateien vergleichen")
        self._set_search_status(phase=phase)
        self.status_panel.show()
        self._start_activity_animation()
        if not self._roots:
            self._show_information(t("Kein Suchordner ausgewählt"), t("Bitte fügen Sie mindestens einen Suchordner hinzu.")); return
        if not (self.exact_checkbox.isChecked() or self.name_checkbox.isChecked() or self.visual_checkbox.isChecked()):
            self._show_information(t("Keine Suchart ausgewählt"), t("Bitte wählen Sie mindestens eine Suchart aus.")); return
        self._task = DuplicateSearchTask(
            list(self._roots),
            self.recursive_checkbox.isChecked(),
            self._extensions,
            self._cancel_event,
            self.exact_checkbox.isChecked(), self.name_checkbox.isChecked(), self.visual_checkbox.isChecked(), VISUAL_THRESHOLDS[str(self.similarity.currentData())],
        )
        self._task.signals.total.connect(self._set_total)
        self._task.signals.progress.connect(self._set_progress)
        self._task.signals.finished.connect(self._search_finished)
        self._pool.start(self._task)

    def _set_total(self, total: int) -> None:
        self._search_total = max(1, total)
        self._search_checked = 0
        self.checked_label.setText(t("0 von {count} Dateien geprüft").format(count=total))
        self._set_search_status(phase=t("Dateien prüfen"), examined=0)

    def _set_progress(self, checked: int) -> None:
        self._search_checked = checked
        self.checked_label.setText(
            t("{checked} von {total} Dateien geprüft").format(checked=checked, total=self._search_total)
        )
        self._set_search_status(phase=t("Dateien prüfen"), examined=checked)

    def _search_finished(self, result: dict) -> None:
        self._searching = False
        self._stop_activity_animation()
        self.status_panel.hide()
        self._task = None
        self.start_button.setEnabled(True)
        self.select_button.setEnabled(True)
        self.recursive_checkbox.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText(t("Schließen"))
        if result.get("cancelled"):
            self.summary.setText(t("Suche abgebrochen. Es wurden keine Dateien verändert."))
            self.result_overview.setText(t("Suche abgebrochen. Es wurden keine Dateien verändert."))
            return
        self._show_results(result)

    def _show_results(self, result: dict) -> None:
        self._result = result
        metadata = result["metadata"]
        for number, group in enumerate(result["groups"], 1):
            reason = result.get("group_reasons", {}).get(tuple(group), {"exact"})
            size = metadata[group[0]][0]
            reclaimable = size * (len(group) - 1)
            labels = []
            if "exact" in reason: labels.append(t("Exakt identisch"))
            if "name" in reason: labels.append(t("Gleicher Dateiname"))
            if "visual_equal" in reason: labels.append(t("Visuell gleich"))
            if "visual_similar" in reason: labels.append(t("Visuell ähnlich"))
            visual_distance = result.get("group_visual_distances", {}).get(tuple(group))
            detail = t("Hamming-Distanz: {distance}").format(distance=visual_distance)
            if visual_distance is not None and visual_distance > 0:
                detail += t(" (≤ {threshold})").format(threshold=VISUAL_THRESHOLDS[str(self.similarity.currentData())])
            parent = QTreeWidgetItem(
                (
                    t("{reason}: {count}").format(reason=labels[0], count=len(group)),
                    (t("Zusätzlich: {reasons}").format(reasons=", ".join(labels[1:])) + (f" · {detail}" if visual_distance is not None else "")) if len(labels) > 1 else (detail if visual_distance is not None else t("Theoretisch einsparbar: {size}").format(size=_format_size(reclaimable))),
                    _format_size(size),
                    "", "", "", "", "",
                )
            )
            parent.setToolTip(0, t("Theoretisch einsparbar: {size}").format(size=_format_size(reclaimable)))
            self.results.addTopLevelItem(parent)
            controls = {
                "parent": parent,
                "entries": [],
                "keep_group": QButtonGroup(self),
                "size": size,
            }
            controls["keep_group"].setExclusive(True)
            for index, path in enumerate(group):
                _size, modified, dimensions, capture_date = metadata[path]
                item = QTreeWidgetItem(
                    (path.name, str(path), _format_size(_size), dimensions, capture_date, datetime.fromtimestamp(modified).strftime("%d.%m.%Y, %H:%M"))
                )
                item.setToolTip(0, path.name)
                item.setToolTip(1, str(path.resolve(strict=False)))
                reader = QImageReader(str(path))
                reader.setAutoTransform(True)
                reader.setScaledSize(reader.size().scaled(PREVIEW_SIZE, Qt.AspectRatioMode.KeepAspectRatio))
                image = reader.read()
                if not image.isNull():
                    item.setIcon(0, QIcon(QPixmap.fromImage(image)))
                parent.addChild(item)
                keep = QRadioButton(t("Behalten"))
                trash = QCheckBox(t("In den Papierkorb"))
                controls["keep_group"].addButton(keep)
                keep.setChecked(index == 0)
                trash.setEnabled(index != 0)
                self.results.setItemWidget(item, 6, keep)
                self.results.setItemWidget(item, 7, trash)
                entry = {
                    "path": path.resolve(strict=False),
                    "item": item,
                    "keep": keep,
                    "trash": trash,
                }
                controls["entries"].append(entry)
                keep.toggled.connect(
                    lambda checked, e=entry: self._keep_changed(e, checked)
                )
                trash.toggled.connect(
                    lambda checked, e=entry: self._trash_mark_changed(e, checked)
                )
            mark_others = QPushButton(t("Alle anderen markieren"))
            clear_group = QPushButton(t("Markierung aufheben"))
            mark_others.setMinimumWidth(mark_others.sizeHint().width())
            clear_group.setMinimumWidth(clear_group.sizeHint().width())
            self.results.setItemWidget(parent, 6, mark_others)
            self.results.setItemWidget(parent, 7, clear_group)
            mark_others.clicked.connect(
                lambda _checked=False, c=controls: self._mark_all_others(c)
            )
            clear_group.clicked.connect(
                lambda _checked=False, c=controls: self._clear_group_marks(c)
            )
            controls["mark_button"] = mark_others
            controls["clear_button"] = clear_group
            self._group_controls.append(controls)
            parent.setExpanded(True)
        overview = t("Ergebnisse: {groups} Gruppen ({files} Dateien) – {size} freigebbar (theoretisch)").format(groups=len(result["groups"]), files=result["duplicate_files"], size=_format_size(result["reclaimable"]))
        self.result_overview.setText(overview)
        self.summary.setText(t("{groups} Gruppen · {files} Dateien · Theoretisch freigebbar: {size}").format(groups=len(result["groups"]), files=result["duplicate_files"], size=_format_size(result["reclaimable"])))
        self.clear_all_button.setEnabled(bool(self._group_controls))
        self._update_trash_button()

    def _keep_changed(self, entry: dict, checked: bool) -> None:
        if checked and entry["trash"].isChecked():
            entry["trash"].setChecked(False)
        entry["trash"].setEnabled(not checked)
        self._update_trash_button()

    def _trash_mark_changed(self, entry: dict, checked: bool) -> None:
        if checked and entry["keep"].isChecked():
            entry["trash"].setChecked(False)
        self._update_trash_button()

    def _mark_all_others(self, controls: dict) -> None:
        for entry in controls["entries"]:
            entry["trash"].setChecked(not entry["keep"].isChecked())
        self._update_trash_button()

    def _clear_group_marks(self, controls: dict) -> None:
        for entry in controls["entries"]:
            entry["trash"].setChecked(False)
        self._update_trash_button()

    def _clear_all_marks(self) -> None:
        for controls in self._group_controls:
            self._clear_group_marks(controls)

    def _marked_entries(self) -> list[tuple[dict, dict]]:
        return [
            (controls, entry)
            for controls in self._group_controls
            for entry in controls["entries"]
            if entry["trash"].isChecked() and not entry["keep"].isChecked()
        ]

    def _update_trash_button(self) -> None:
        marked = bool(self._marked_entries())
        enabled = (
            marked
            and not self._searching
            and not self._trash_in_progress
            and not self._confirming_trash
        )
        self.trash_selected_button.setEnabled(enabled)
        self.trash_selected_button.setToolTip(
            ""
            if enabled
            else t("Markiere zuerst mindestens eine Datei in der Spalte Papierkorb.")
        )

    def _move_selected_duplicates_to_trash(self) -> None:
        _trash_debug("Papierkorbfunktion aufgerufen")
        if self._searching or self._trash_in_progress or self._confirming_trash:
            return
        marked = self._marked_entries()
        _trash_debug(f"Anzahl markierter Dateien: {len(marked)}")
        for _controls, entry in marked:
            path = entry["path"]
            _trash_debug(f"Markiert: {path} (vorhanden: {path.is_file()})")
        if not marked:
            self._show_information(
                t("Keine Auswahl"),
                t("Es sind keine Dateien für den Papierkorb ausgewählt."),
            )
            return
        selected_size = sum(controls["size"] for controls, _entry in marked)
        self._confirming_trash = True
        self._update_trash_button()
        confirmation = QMessageBox(self)
        confirmation.setWindowTitle(t("Dateien in den Papierkorb verschieben"))
        confirmation.setIcon(QMessageBox.Icon.Question)
        confirmation.setTextFormat(Qt.TextFormat.PlainText)
        confirmation.setText(
            t("Möchtest du die ausgewählten {count} Dateien in den Papierkorb verschieben?\n\nMindestens eine Datei jeder Duplikatgruppe bleibt erhalten.").format(count=len(marked))
        )
        confirmation.setInformativeText(
            t("Theoretisch freigebbarer Speicherplatz: {size}").format(size=_format_size(selected_size))
        )
        confirmation.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        trash_button = confirmation.button(QMessageBox.StandardButton.Yes)
        cancel_button = confirmation.button(QMessageBox.StandardButton.Cancel)
        trash_button.setText(t("In den Papierkorb"))
        cancel_button.setText(t("Abbrechen"))
        confirmation.setDefaultButton(cancel_button)
        confirmation.setEscapeButton(cancel_button)
        confirmation.setStyleSheet(self.styleSheet())
        try:
            result = confirmation.exec()
            confirmed = result == QMessageBox.StandardButton.Yes
        finally:
            self._confirming_trash = False
            self._update_trash_button()
        if confirmed:
            self._trash_marked(marked)

    def _set_trash_busy(self, busy: bool) -> None:
        self._trash_in_progress = busy
        self.start_button.setEnabled(not busy and not self._searching)
        self.select_button.setEnabled(not busy and not self._searching)
        self.recursive_checkbox.setEnabled(not busy and not self._searching)
        self.clear_all_button.setEnabled(not busy and bool(self._group_controls))
        self.cancel_button.setEnabled(not busy)
        self.results.setEnabled(not busy)
        for controls in self._group_controls:
            controls["mark_button"].setEnabled(not busy)
            controls["clear_button"].setEnabled(not busy)
        self._update_trash_button()

    def _trash_marked(self, marked: list[tuple[dict, dict]]) -> None:
        if self._trash_in_progress or not marked:
            return
        # Revalidate the invariant immediately before the first file operation.
        marked_by_group = defaultdict(int)
        for controls, _entry in marked:
            marked_by_group[id(controls)] += 1
        if any(
            marked_by_group[id(controls)] >= len(controls["entries"])
            for controls in self._group_controls
        ):
            return
        self._set_trash_busy(True)
        successful: list[tuple[dict, dict]] = []
        failures: list[tuple[Path, str]] = []
        try:
            for controls, entry in marked:
                path = entry["path"].resolve(strict=False)
                _trash_debug(f"Pfad wird verschoben: {path}")
                if not path.is_file():
                    failures.append((path, "Datei ist nicht mehr vorhanden"))
                    _trash_debug(f"Fehler beim Verschieben: {path} ist keine Datei")
                    continue
                try:
                    send2trash(str(path))
                except Exception as error:
                    failures.append((path, str(error)))
                    _trash_debug(f"Fehler beim Verschieben: {path}: {error}")
                else:
                    successful.append((controls, entry))
                    self._freed_bytes += controls["size"]
                    _trash_debug(f"Verschieben erfolgreich: {path}")

            for controls, entry in successful:
                controls["entries"].remove(entry)
                controls["parent"].removeChild(entry["item"])
            for controls in list(self._group_controls):
                if len(controls["entries"]) < 2:
                    index = self.results.indexOfTopLevelItem(controls["parent"])
                    if index >= 0:
                        self.results.takeTopLevelItem(index)
                    self._group_controls.remove(controls)
                else:
                    self._update_group_heading(controls)

            successful_paths = [entry["path"] for _controls, entry in successful]
            if successful_paths and self._files_trashed_callback is not None:
                self._files_trashed_callback(successful_paths)
            self._update_after_trash(failures, len(successful))
        finally:
            self._set_trash_busy(False)

    def _update_group_heading(self, controls: dict) -> None:
        count = len(controls["entries"])
        reclaimable = controls["size"] * (count - 1)
        controls["parent"].setText(0, t("{count} identische Dateien").format(count=count))
        controls["parent"].setText(
            1, t("Theoretisch einsparbar: {size}").format(size=_format_size(reclaimable))
        )

    def _update_after_trash(
        self, failures: list[tuple[Path, str]], moved_count: int
    ) -> None:
        remaining_files = sum(
            len(controls["entries"]) for controls in self._group_controls
        )
        if not self._group_controls:
            summary = t("Keine doppelten Dateien mehr vorhanden.")
        else:
            summary = t("{groups} verbleibende Duplikatgruppen · {files} verbleibende doppelte Dateien · {size} freigewordener Speicherplatz").format(groups=len(self._group_controls), files=remaining_files, size=_format_size(self._freed_bytes))
        if moved_count:
            moved_text = t("{count} Datei wurde in den Papierkorb verschoben.").format(count=moved_count) if moved_count == 1 else t("{count} Dateien wurden in den Papierkorb verschoben.").format(count=moved_count)
            summary += f"\n{moved_text}"
            self.safety_notice.setText(moved_text)
        self.summary.setText(summary)
        self.clear_all_button.setEnabled(bool(self._group_controls))
        if failures:
            details = "\n".join(f"{path}: {error}" for path, error in failures)
            message = QMessageBox(self)
            message.setWindowTitle(
                t("Keine Datei verschoben")
                if not moved_count
                else t("Nicht alle Dateien wurden verschoben")
            )
            message.setIcon(
                QMessageBox.Icon.Critical
                if not moved_count
                else QMessageBox.Icon.Warning
            )
            message.setText(
                t("Keine Datei konnte in den Papierkorb verschoben werden.")
                if not moved_count
                else t("Einige Dateien konnten nicht in den Papierkorb verschoben werden.")
            )
            message.setDetailedText(details)
            message.setStandardButtons(QMessageBox.StandardButton.Close)
            message.setStyleSheet(self.styleSheet())
            message.exec()

    def _show_information(self, title: str, text: str) -> None:
        message = QMessageBox(self)
        message.setWindowTitle(title)
        message.setIcon(QMessageBox.Icon.Information)
        message.setText(text)
        message.setStandardButtons(QMessageBox.StandardButton.Close)
        message.setStyleSheet(self.styleSheet())
        message.exec()

    def _cancel_or_close(self) -> None:
        if self._searching:
            self._request_cancel()
            self._stop_activity_animation()
            self.cancel_button.setEnabled(False)
            self.summary.setText(t("Suche wird abgebrochen …"))
        else:
            self.close()

    def _request_cancel(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
        self._pool.clear()

    def closeEvent(self, event) -> None:
        if self._searching:
            self._request_cancel()
            self._stop_activity_animation()
            self.hide()
            self._pool.waitForDone()
        self._settings.sync()
        event.accept()


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1000 or unit == "TB":
            return f"{size} B" if unit == "B" else f"{value:.1f} {unit}".replace(".", ",")
        value /= 1000
    return f"{size} B"
