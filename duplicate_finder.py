import hashlib
import os
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from PIL import Image as PillowImage
from send2trash import send2trash
from PySide6.QtCore import QObject, QRunnable, QSettings, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QButtonGroup,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QAbstractItemView,
)


HASH_BLOCK_SIZE = 1024 * 1024
PREVIEW_SIZE = QSize(72, 54)
TRASH_DEBUG = False
DUPLICATE_COLUMN_WIDTHS_KEY = "duplicateFinder/columnWidths"
DEFAULT_COLUMN_WIDTHS = (300, 450, 120, 190, 250, 300)
MINIMUM_COLUMN_WIDTHS = (150, 180, 80, 120, 140, 170)


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


def find_duplicates(
    root: Path,
    recursive: bool,
    extensions: set[str],
    cancel_event: threading.Event,
    progress_callback=None,
    total_callback=None,
) -> dict:
    paths: list[Path] = []
    skipped = 0
    def record_walk_error(_error) -> None:
        nonlocal skipped
        skipped += 1

    try:
        if recursive:
            for directory, _subdirs, files in os.walk(root, onerror=record_walk_error):
                if cancel_event.is_set():
                    return {"cancelled": True}
                paths.extend(
                    Path(directory) / name
                    for name in files
                    if not name.startswith("._")
                    and Path(name).suffix.lower() in extensions
                )
        else:
            with os.scandir(root) as entries:
                for entry in entries:
                    if cancel_event.is_set():
                        return {"cancelled": True}
                    try:
                        if (
                            not entry.name.startswith("._")
                            and entry.is_file()
                            and Path(entry.name).suffix.lower() in extensions
                        ):
                            paths.append(Path(entry.path))
                    except OSError:
                        skipped += 1
    except OSError:
        skipped += 1

    paths.sort(key=lambda path: str(path).casefold())
    if total_callback:
        total_callback(len(paths))
    by_size: dict[int, list[Path]] = defaultdict(list)
    metadata: dict[Path, tuple[int, float]] = {}
    checked = 0
    for path in paths:
        if cancel_event.is_set():
            return {"cancelled": True}
        try:
            stat = path.stat()
            if not _is_readable_image(path):
                raise OSError("Bild ist nicht lesbar")
            metadata[path] = (stat.st_size, stat.st_mtime)
            by_size[stat.st_size].append(path)
        except (OSError, ValueError):
            skipped += 1
        checked += 1
        if progress_callback:
            progress_callback(checked)

    groups: list[list[Path]] = []
    for same_size in by_size.values():
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
            groups.extend(group for group in confirmed if len(group) >= 2)

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
    }


class DuplicateSearchSignals(QObject):
    total = Signal(int)
    progress = Signal(int)
    finished = Signal(object)


class DuplicateSearchTask(QRunnable):
    def __init__(self, root: Path, recursive: bool, extensions: set[str], cancel_event):
        super().__init__()
        self.root = root
        self.recursive = recursive
        self.extensions = extensions
        self.cancel_event = cancel_event
        self.signals = DuplicateSearchSignals()

    def run(self) -> None:
        result = find_duplicates(
            self.root,
            self.recursive,
            self.extensions,
            self.cancel_event,
            self.signals.progress.emit,
            self.signals.total.emit,
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
        self.setWindowTitle("Doppelte Bilder finden")
        self.setMinimumWidth(1100)
        self.resize(1600, 650)
        self._directory = initial_directory
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
        self._settings = QSettings("BildBlick", "BildBlick")

        layout = QVBoxLayout(self)
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Ordner:"))
        self.folder_label = QLabel(str(initial_directory))
        self.folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.folder_label.setWordWrap(True)
        folder_row.addWidget(self.folder_label, 1)
        self.select_button = QPushButton("Ordner auswählen …")
        self.select_button.clicked.connect(self._select_directory)
        folder_row.addWidget(self.select_button)
        layout.addLayout(folder_row)

        self.recursive_checkbox = QCheckBox("Unterordner einbeziehen")
        layout.addWidget(self.recursive_checkbox)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.checked_label = QLabel("0 Dateien geprüft")
        layout.addWidget(self.checked_label)

        self.results = QTreeWidget()
        self.results.setHeaderLabels(
            (
                "Datei / Gruppe",
                "Pfad",
                "Größe",
                "Geändert",
                "Behalten",
                "Papierkorb",
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

        self.summary = QLabel("Noch keine Suche ausgeführt.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.safety_notice = QLabel("Es wurden keine Dateien verändert.")
        self.safety_notice.setObjectName("safetyNotice")
        self.safety_notice.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.safety_notice)

        selection_row = QHBoxLayout()
        self.clear_all_button = QPushButton("Alle Markierungen aufheben")
        self.clear_all_button.setEnabled(False)
        self.clear_all_button.clicked.connect(self._clear_all_marks)
        selection_row.addWidget(self.clear_all_button)
        selection_row.addStretch(1)
        self.trash_selected_button = QPushButton(
            "Ausgewählte Dateien in den Papierkorb verschieben"
        )
        self.trash_selected_button.setEnabled(False)
        self.trash_selected_button.setToolTip(
            "Markiere zuerst mindestens eine Datei in der Spalte Papierkorb."
        )
        self.trash_selected_button.clicked.connect(
            self._move_selected_duplicates_to_trash
        )
        selection_row.addWidget(self.trash_selected_button)
        layout.addLayout(selection_row)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.start_button = QPushButton("Suche starten")
        self.start_button.clicked.connect(self._start_search)
        buttons.addWidget(self.start_button)
        self.cancel_button = QPushButton("Abbrechen")
        self.cancel_button.clicked.connect(self._cancel_or_close)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

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
            self, "Ordner auswählen", str(self._directory)
        )
        if selected:
            self._directory = Path(selected)
            self.folder_label.setText(selected)

    def _start_search(self) -> None:
        if self._searching or self._trash_in_progress:
            return
        self.results.clear()
        self._group_controls = []
        self._result = None
        self._freed_bytes = 0
        self.safety_notice.setText("Es wurden keine Dateien verändert.")
        self.clear_all_button.setEnabled(False)
        self.trash_selected_button.setEnabled(False)
        self.summary.setText("Suche läuft …")
        self.checked_label.setText("Dateien werden ermittelt …")
        self.progress.setRange(0, 0)
        self.start_button.setEnabled(False)
        self.select_button.setEnabled(False)
        self.recursive_checkbox.setEnabled(False)
        self.cancel_button.setText("Abbrechen")
        self._searching = True
        self._cancel_event = threading.Event()
        self._task = DuplicateSearchTask(
            self._directory,
            self.recursive_checkbox.isChecked(),
            self._extensions,
            self._cancel_event,
        )
        self._task.signals.total.connect(self._set_total)
        self._task.signals.progress.connect(self._set_progress)
        self._task.signals.finished.connect(self._search_finished)
        self._pool.start(self._task)

    def _set_total(self, total: int) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(0)
        self.checked_label.setText(f"0 von {total} Dateien geprüft")

    def _set_progress(self, checked: int) -> None:
        self.progress.setValue(checked)
        self.checked_label.setText(
            f"{checked} von {self.progress.maximum()} Dateien geprüft"
        )

    def _search_finished(self, result: dict) -> None:
        self._searching = False
        self._task = None
        self.start_button.setEnabled(True)
        self.select_button.setEnabled(True)
        self.recursive_checkbox.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("Schließen")
        if result.get("cancelled"):
            self.summary.setText("Suche abgebrochen. Es wurden keine Dateien verändert.")
            return
        self._show_results(result)

    def _show_results(self, result: dict) -> None:
        self._result = result
        metadata = result["metadata"]
        for number, group in enumerate(result["groups"], 1):
            size = metadata[group[0]][0]
            reclaimable = size * (len(group) - 1)
            parent = QTreeWidgetItem(
                (
                    f"Gruppe {number}: {len(group)} identische Dateien",
                    f"Theoretisch einsparbar: {_format_size(reclaimable)}",
                    _format_size(size),
                    "",
                )
            )
            parent.setToolTip(0, f"Theoretisch einsparbar: {_format_size(reclaimable)}")
            self.results.addTopLevelItem(parent)
            controls = {
                "parent": parent,
                "entries": [],
                "keep_group": QButtonGroup(self),
                "size": size,
            }
            controls["keep_group"].setExclusive(True)
            for index, path in enumerate(group):
                _size, modified = metadata[path]
                item = QTreeWidgetItem(
                    (path.name, str(path), _format_size(_size), datetime.fromtimestamp(modified).strftime("%d.%m.%Y, %H:%M"))
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
                keep = QRadioButton("Behalten")
                trash = QCheckBox("In den Papierkorb")
                controls["keep_group"].addButton(keep)
                keep.setChecked(index == 0)
                trash.setEnabled(index != 0)
                self.results.setItemWidget(item, 4, keep)
                self.results.setItemWidget(item, 5, trash)
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
            mark_others = QPushButton("Alle anderen markieren")
            clear_group = QPushButton("Markierung aufheben")
            self.results.setItemWidget(parent, 4, mark_others)
            self.results.setItemWidget(parent, 5, clear_group)
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
        self.summary.setText(
            f"{result['examined']} Bilddateien untersucht · "
            f"{len(result['groups'])} Duplikatgruppen · "
            f"{result['duplicate_files']} mehrfach vorhandene Dateien · "
            f"{_format_size(result['reclaimable'])} theoretisch freigebbar · "
            f"{result['skipped']} übersprungen oder fehlerhaft"
        )
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
            else "Markiere zuerst mindestens eine Datei in der Spalte Papierkorb."
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
                "Keine Auswahl",
                "Es sind keine Dateien für den Papierkorb ausgewählt.",
            )
            return
        selected_size = sum(controls["size"] for controls, _entry in marked)
        self._confirming_trash = True
        self._update_trash_button()
        confirmation = QMessageBox(self)
        confirmation.setWindowTitle("Dateien in den Papierkorb verschieben")
        confirmation.setIcon(QMessageBox.Icon.Question)
        confirmation.setTextFormat(Qt.TextFormat.PlainText)
        confirmation.setText(
            f"Möchtest du die ausgewählten {len(marked)} Dateien in den "
            "Papierkorb verschieben?\n\nMindestens eine Datei jeder "
            "Duplikatgruppe bleibt erhalten."
        )
        confirmation.setInformativeText(
            f"Theoretisch freigebbarer Speicherplatz: {_format_size(selected_size)}"
        )
        confirmation.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        trash_button = confirmation.button(QMessageBox.StandardButton.Yes)
        cancel_button = confirmation.button(QMessageBox.StandardButton.Cancel)
        trash_button.setText("In den Papierkorb")
        cancel_button.setText("Abbrechen")
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
        controls["parent"].setText(0, f"{count} identische Dateien")
        controls["parent"].setText(
            1, f"Theoretisch einsparbar: {_format_size(reclaimable)}"
        )

    def _update_after_trash(
        self, failures: list[tuple[Path, str]], moved_count: int
    ) -> None:
        remaining_files = sum(
            len(controls["entries"]) for controls in self._group_controls
        )
        if not self._group_controls:
            summary = "Keine doppelten Dateien mehr vorhanden."
        else:
            summary = (
                f"{len(self._group_controls)} verbleibende Duplikatgruppen · "
                f"{remaining_files} verbleibende doppelte Dateien · "
                f"{_format_size(self._freed_bytes)} freigewordener Speicherplatz"
            )
        if moved_count:
            noun = "Datei wurde" if moved_count == 1 else "Dateien wurden"
            summary += f"\n{moved_count} {noun} in den Papierkorb verschoben."
            self.safety_notice.setText(
                f"{moved_count} {noun} in den Papierkorb verschoben."
            )
        self.summary.setText(summary)
        self.clear_all_button.setEnabled(bool(self._group_controls))
        if failures:
            details = "\n".join(f"{path}: {error}" for path, error in failures)
            message = QMessageBox(self)
            message.setWindowTitle(
                "Keine Datei verschoben"
                if not moved_count
                else "Nicht alle Dateien wurden verschoben"
            )
            message.setIcon(
                QMessageBox.Icon.Critical
                if not moved_count
                else QMessageBox.Icon.Warning
            )
            message.setText(
                "Keine Datei konnte in den Papierkorb verschoben werden."
                if not moved_count
                else "Einige Dateien konnten nicht in den Papierkorb verschoben werden."
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
            self.cancel_button.setEnabled(False)
            self.summary.setText("Suche wird abgebrochen …")
        else:
            self.close()

    def _request_cancel(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
        self._pool.clear()

    def closeEvent(self, event) -> None:
        if self._searching:
            self._request_cancel()
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
