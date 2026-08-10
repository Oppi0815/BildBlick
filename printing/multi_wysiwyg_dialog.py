"""Visible WYSIWYG dialog for the shared multi-image PagePlan path."""

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtWidgets import QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget, QInputDialog, QListWidget, QListWidgetItem

from printing.layout import ImageSourceInfo, PageSizeMm
from printing.multi_image_print import MultiImagePrintSettings, multi_image_document_from_settings
from printing.multi_pdf_export import export_multi_page_plan_pdf
from printing.planner import plan_multi_image_pages
from printing.print_profiles import MultiImagePrintProfile, create_user_profile, delete_user_profile, load_user_profiles, save_user_profile
from printing.multi_wysiwyg_preview import MultiWysiwygPreview


PAPERS = {"A4": (210.0, 297.0), "Letter": (215.9, 279.4), "10 × 15 cm": (100.0, 150.0), "13 × 18 cm": (130.0, 180.0)}


class MultiImageWysiwygPrintDialog(QDialog):
    def __init__(self, sources_by_kind: dict[str, list[ImageSourceInfo]], settings: QSettings, parent=None) -> None:
        super().__init__(parent); self.sources_by_kind, self.settings = {key: list(value) for key, value in sources_by_kind.items()}, settings; self.active_sources = list(self.sources_by_kind.get("current", [])); self.page_plans = []; self.page_index = 0; self._cache: dict[Path, QImage] = {}
        self.setObjectName("multiImageWysiwygPrintDialog"); self.setWindowTitle("Mehrere Bilder WYSIWYG drucken — BildBlick"); self.resize(1120, 740); self.setMinimumSize(760, 560)
        outer = QVBoxLayout(self); split = QHBoxLayout(); outer.addLayout(split, 1)
        panel = QWidget(self); form = QFormLayout(panel)
        self.source = QComboBox(); [self.source.addItem(label, key) for label, key in (("Aktuelles Bild", "current"), ("Markierte Bilder", "selected"), ("Alle Bilder", "all"))]; form.addRow("Quelle:", self.source)
        self.profile = QComboBox(); form.addRow("Profil:", self.profile)
        self.paper = QComboBox(); self.paper.addItems([*PAPERS, "Benutzerdefiniert"]); form.addRow("Papierformat:", self.paper)
        self.width, self.height = self._double(210), self._double(297); form.addRow("Breite (mm):", self.width); form.addRow("Höhe (mm):", self.height)
        self.orientation = QComboBox(); [self.orientation.addItem(label, value) for label, value in (("Automatisch", "automatic"), ("Hochformat", "portrait"), ("Querformat", "landscape"))]; form.addRow("Ausrichtung:", self.orientation)
        self.count = QComboBox(); [self.count.addItem(f"{value} Bild" if value == 1 else f"{value} Bilder", value) for value in (1, 2, 4, 6, 9, 16, 32)]; self.count.addItem("Benutzerdefiniert", 0); form.addRow("Raster:", self.count)
        self.rows, self.columns = self._spin(4), self._spin(3); form.addRow("Zeilen:", self.rows); form.addRow("Spalten:", self.columns)
        self.margin, self.spacing = self._double(5), self._double(4); form.addRow("Seitenrand:", self.margin); form.addRow("Bildabstand:", self.spacing)
        self.contact, self.filename, self.capture = QCheckBox("Kontaktabzug"), QCheckBox("Dateiname"), QCheckBox("Aufnahmedatum"); form.addRow(self.contact); form.addRow("", self.filename); form.addRow("", self.capture)
        self.show_header, self.header = QCheckBox("Kopfzeile anzeigen"), QLineEdit(); form.addRow(self.show_header); form.addRow("Titel:", self.header)
        self.footer_folder, self.page_number, self.print_date = QCheckBox("Ordnername"), QCheckBox("Seitenzahl"), QCheckBox("Druckdatum"); self.page_number.setChecked(True); form.addRow("Fußzeile:", self.footer_folder); form.addRow("", self.page_number); form.addRow("", self.print_date)
        self.image_list = QListWidget(); self.image_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove); self.image_list.setDefaultDropAction(Qt.DropAction.MoveAction); form.addRow("Druckauswahl:", self.image_list)
        image_actions = QWidget(); image_actions_layout = QHBoxLayout(image_actions); image_actions_layout.setContentsMargins(0, 0, 0, 0); self.reset_order_button, self.remove_button, self.reload_button = QPushButton("Reihenfolge zurücksetzen"), QPushButton("Auswahl entfernen"), QPushButton("Quelle neu laden")
        for button in (self.reset_order_button, self.remove_button, self.reload_button): image_actions_layout.addWidget(button)
        form.addRow("", image_actions)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(panel); scroll.setMaximumWidth(360); split.addWidget(scroll, 0)
        right = QVBoxLayout(); self.preview = MultiWysiwygPreview(); right.addWidget(self.preview, 1); nav = QHBoxLayout(); self.first, self.previous, self.next, self.last, self.page_label = QPushButton("|◀"), QPushButton("◀"), QPushButton("▶"), QPushButton("▶|"), QLabel(); nav.addStretch(); [nav.addWidget(button) for button in (self.first, self.previous, self.page_label, self.next, self.last)]; nav.addStretch(); right.addLayout(nav); self.status_label = QLabel(); right.addWidget(self.status_label); split.addLayout(right, 1)
        buttons = QHBoxLayout(); self.save_profile_button, self.delete_profile_button = QPushButton("Profil speichern"), QPushButton("Profil löschen"); self.pdf_button, self.print_button, cancel = QPushButton("Als PDF speichern …"), QPushButton("Drucken"), QPushButton("Abbrechen"); buttons.addWidget(self.save_profile_button); buttons.addWidget(self.delete_profile_button); buttons.addStretch(); buttons.addWidget(self.pdf_button); buttons.addWidget(self.print_button); buttons.addWidget(cancel); outer.addLayout(buttons)
        self._populate_profiles(); watched = [self.source, self.paper, self.width, self.height, self.orientation, self.count, self.rows, self.columns, self.margin, self.spacing, self.contact, self.filename, self.capture, self.show_header, self.header, self.footer_folder, self.page_number, self.print_date]
        for widget in watched:
            signal = getattr(widget, "currentIndexChanged", None) or getattr(widget, "valueChanged", None) or getattr(widget, "toggled", None) or getattr(widget, "textChanged", None); signal.connect(self._update)
        self.source.currentIndexChanged.connect(self._reload_source); self.image_list.model().rowsMoved.connect(lambda *_: self._sync_list_order()); self.image_list.itemDoubleClicked.connect(lambda item: self._set_page(self.image_list.row(item) // max(1, self.print_settings().effective_images_per_page))); self.reset_order_button.clicked.connect(self._reset_order); self.remove_button.clicked.connect(self._remove_selected); self.reload_button.clicked.connect(self._reload_source); self.profile.currentIndexChanged.connect(self._apply_profile); self.first.clicked.connect(lambda: self._set_page(0)); self.previous.clicked.connect(lambda: self._set_page(self.page_index - 1)); self.next.clicked.connect(lambda: self._set_page(self.page_index + 1)); self.last.clicked.connect(lambda: self._set_page(len(self.page_plans) - 1)); self.pdf_button.clicked.connect(self._export_pdf); self.save_profile_button.clicked.connect(self._save_profile); self.delete_profile_button.clicked.connect(self._delete_profile); self.print_button.clicked.connect(self.accept); cancel.clicked.connect(self.reject); self._rebuild_list(); self._update()

    @staticmethod
    def _double(value):
        spin = QDoubleSpinBox(); spin.setRange(0, 1000); spin.setDecimals(1); spin.setSuffix(" mm"); spin.setValue(value); return spin
    @staticmethod
    def _spin(value):
        spin = QSpinBox(); spin.setRange(1, 12); spin.setValue(value); return spin

    def _populate_profiles(self):
        self.profile.clear(); self.profile.addItem("Standard", MultiImagePrintProfile("standard", "Standard", MultiImagePrintSettings(), True))
        for label, count, contact in (("4 Bilder", 4, False), ("9 Bilder", 9, False), ("16 Bilder", 16, False), ("32 Bilder", 32, False), ("Kontaktabzug 9", 9, True)):
            self.profile.addItem(label, MultiImagePrintProfile(label, label, MultiImagePrintSettings(images_per_page=count, contact_sheet=contact), True))
        for profile in load_user_profiles(self.settings): self.profile.addItem(profile.display_name, profile)

    def _apply_profile(self, _index):
        profile = self.profile.currentData()
        if not isinstance(profile, MultiImagePrintProfile): return
        value = profile.settings; pairs = ((self.source, value.source), (self.orientation, value.orientation), (self.count, value.images_per_page))
        for combo, data in pairs:
            index = combo.findData(data)
            if index >= 0: combo.setCurrentIndex(index)
        self.rows.setValue(value.custom_rows); self.columns.setValue(value.custom_columns); self.margin.setValue(value.page_margin_mm); self.spacing.setValue(value.cell_spacing_mm); self.contact.setChecked(value.contact_sheet); self.filename.setChecked(value.show_filename); self.capture.setChecked(value.show_capture_date); self.page_number.setChecked(value.show_page_number); self.show_header.setChecked(value.show_header); self.header.setText(value.header_text); self.footer_folder.setChecked(value.show_folder_in_footer); self.print_date.setChecked(value.show_print_date)

    def _save_profile(self):
        name, accepted = QInputDialog.getText(self, "Profil speichern", "Name:")
        if not accepted or not name.strip(): return
        profile = create_user_profile(name, self.print_settings()); save_user_profile(self.settings, profile); self._populate_profiles(); self.profile.setCurrentIndex(self.profile.findData(profile))

    def _delete_profile(self):
        profile = self.profile.currentData()
        if isinstance(profile, MultiImagePrintProfile) and not profile.built_in:
            delete_user_profile(self.settings, profile.profile_id); self._populate_profiles()

    def _reload_source(self, *_args):
        self.active_sources = list(self.sources_by_kind.get(str(self.source.currentData()), [])); self._rebuild_list(); self._update()
    def _reset_order(self): self._reload_source()
    def _rebuild_list(self):
        self.image_list.blockSignals(True); self.image_list.clear()
        for index, source in enumerate(self.active_sources, 1):
            item = QListWidgetItem(f"{index}.  {source.filename or source.path.name}"); item.setData(Qt.ItemDataRole.UserRole, source); self.image_list.addItem(item)
        self.image_list.blockSignals(False); self.reset_order_button.setEnabled(str(self.source.currentData()) != "current")
    def _sync_list_order(self):
        self.active_sources = [self.image_list.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.image_list.count())]; self._rebuild_list(); self._update()
    def _remove_selected(self):
        selected = {self.image_list.row(item) for item in self.image_list.selectedItems()}; self.active_sources = [source for index, source in enumerate(self.active_sources) if index not in selected]; self._rebuild_list(); self._update()

    def print_settings(self) -> MultiImagePrintSettings:
        return MultiImagePrintSettings(source=str(self.source.currentData()), orientation=str(self.orientation.currentData()), images_per_page=int(self.count.currentData()), custom_rows=self.rows.value(), custom_columns=self.columns.value(), page_margin_mm=self.margin.value(), cell_spacing_mm=self.spacing.value(), contact_sheet=self.contact.isChecked(), show_filename=self.filename.isChecked(), show_capture_date=self.capture.isChecked(), show_page_number=self.page_number.isChecked(), show_header=self.show_header.isChecked(), header_text=self.header.text(), show_print_date=self.print_date.isChecked(), show_folder_in_footer=self.footer_folder.isChecked())

    def selected_sources(self) -> list[ImageSourceInfo]: return list(self.active_sources)

    def _page_size(self) -> PageSizeMm:
        return PageSizeMm(*(PAPERS.get(self.paper.currentText(), (self.width.value(), self.height.value()))))
    def _image(self, source: ImageSourceInfo) -> QImage:
        if source.path not in self._cache:
            reader = QImageReader(str(source.path)); reader.setAutoTransform(True); self._cache[source.path] = reader.read()
        return self._cache[source.path]
    def _update(self, *_args):
        self.width.setEnabled(self.paper.currentText() == "Benutzerdefiniert"); self.height.setEnabled(self.paper.currentText() == "Benutzerdefiniert"); custom = self.count.currentData() == 0; self.rows.setEnabled(custom); self.columns.setEnabled(custom)
        try:
            settings = self.print_settings(); document = multi_image_document_from_settings(self.active_sources, settings, self._page_size(), source_kind=settings.source)
            self.page_plans = plan_multi_image_pages(document)
        except ValueError:
            self.page_plans = []
        self._set_page(self.page_index)
    def _set_page(self, index):
        self.page_index = min(max(0, index), max(0, len(self.page_plans) - 1)); self.preview.set_pages(self.page_plans, self.page_index, self._image)
        self.page_label.setText(f"Seite {self.page_index + 1} von {len(self.page_plans)}" if self.page_plans else "Seite 0 von 0"); self.first.setEnabled(self.page_index > 0); self.previous.setEnabled(self.page_index > 0); self.next.setEnabled(self.page_index + 1 < len(self.page_plans)); self.last.setEnabled(self.page_index + 1 < len(self.page_plans)); self.pdf_button.setEnabled(bool(self.page_plans)); self.print_button.setEnabled(bool(self.page_plans)); self.status_label.setText(f"{len(self.active_sources)} Bilder · {len(self.page_plans)} Seiten · {self.print_settings().effective_images_per_page} pro Seite")
    def keyPressEvent(self, event):
        keys = {Qt.Key.Key_PageUp: self.page_index - 1, Qt.Key.Key_PageDown: self.page_index + 1, Qt.Key.Key_Home: 0, Qt.Key.Key_End: len(self.page_plans) - 1}
        if event.key() in keys: self._set_page(keys[event.key()]); event.accept(); return
        super().keyPressEvent(event)
    def _export_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, "Mehrbild-PDF speichern", "", "PDF-Datei (*.pdf)")
        if not path: return
        try: export_multi_page_plan_pdf(path, self.page_plans, self._image)
        except Exception as error: QMessageBox.critical(self, "PDF-Export fehlgeschlagen", str(error))
