"""Visible WYSIWYG dialog for the shared multi-image PagePlan path."""

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget, QInputDialog

from printing.layout import ImageSourceInfo, PageSizeMm
from printing.multi_image_print import MultiImagePrintSettings, multi_image_document_from_settings
from printing.multi_pdf_export import export_multi_page_plan_pdf
from printing.planner import plan_multi_image_pages
from printing.print_profiles import MultiImagePrintProfile, create_user_profile, delete_user_profile, load_user_profiles, save_user_profile
from printing.multi_wysiwyg_preview import MultiWysiwygPreview


PAPERS = {"A4": (210.0, 297.0), "Letter": (215.9, 279.4), "10 × 15 cm": (100.0, 150.0), "13 × 18 cm": (130.0, 180.0)}


class MultiImageWysiwygPrintDialog(QDialog):
    def __init__(self, sources_by_kind: dict[str, list[ImageSourceInfo]], settings: QSettings, parent=None) -> None:
        super().__init__(parent); self.sources_by_kind, self.settings = sources_by_kind, settings; self.page_plans = []; self.page_index = 0; self._cache: dict[Path, QImage] = {}
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
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(panel); scroll.setMaximumWidth(360); split.addWidget(scroll, 0)
        right = QVBoxLayout(); self.preview = MultiWysiwygPreview(); right.addWidget(self.preview, 1); nav = QHBoxLayout(); self.previous, self.next, self.page_label = QPushButton("◀"), QPushButton("▶"), QLabel(); nav.addStretch(); nav.addWidget(self.previous); nav.addWidget(self.page_label); nav.addWidget(self.next); nav.addStretch(); right.addLayout(nav); split.addLayout(right, 1)
        buttons = QHBoxLayout(); self.save_profile_button, self.delete_profile_button = QPushButton("Profil speichern"), QPushButton("Profil löschen"); self.pdf_button, self.print_button, cancel = QPushButton("Als PDF speichern …"), QPushButton("Drucken"), QPushButton("Abbrechen"); buttons.addWidget(self.save_profile_button); buttons.addWidget(self.delete_profile_button); buttons.addStretch(); buttons.addWidget(self.pdf_button); buttons.addWidget(self.print_button); buttons.addWidget(cancel); outer.addLayout(buttons)
        self._populate_profiles(); watched = [self.source, self.paper, self.width, self.height, self.orientation, self.count, self.rows, self.columns, self.margin, self.spacing, self.contact, self.filename, self.capture, self.show_header, self.header, self.footer_folder, self.page_number, self.print_date]
        for widget in watched:
            signal = getattr(widget, "currentIndexChanged", None) or getattr(widget, "valueChanged", None) or getattr(widget, "toggled", None) or getattr(widget, "textChanged", None); signal.connect(self._update)
        self.profile.currentIndexChanged.connect(self._apply_profile); self.previous.clicked.connect(lambda: self._set_page(self.page_index - 1)); self.next.clicked.connect(lambda: self._set_page(self.page_index + 1)); self.pdf_button.clicked.connect(self._export_pdf); self.save_profile_button.clicked.connect(self._save_profile); self.delete_profile_button.clicked.connect(self._delete_profile); self.print_button.clicked.connect(self.accept); cancel.clicked.connect(self.reject); self._update()

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

    def print_settings(self) -> MultiImagePrintSettings:
        return MultiImagePrintSettings(source=str(self.source.currentData()), orientation=str(self.orientation.currentData()), images_per_page=int(self.count.currentData()), custom_rows=self.rows.value(), custom_columns=self.columns.value(), page_margin_mm=self.margin.value(), cell_spacing_mm=self.spacing.value(), contact_sheet=self.contact.isChecked(), show_filename=self.filename.isChecked(), show_capture_date=self.capture.isChecked(), show_page_number=self.page_number.isChecked(), show_header=self.show_header.isChecked(), header_text=self.header.text(), show_print_date=self.print_date.isChecked(), show_folder_in_footer=self.footer_folder.isChecked())

    def _page_size(self) -> PageSizeMm:
        return PageSizeMm(*(PAPERS.get(self.paper.currentText(), (self.width.value(), self.height.value()))))
    def _image(self, source: ImageSourceInfo) -> QImage:
        if source.path not in self._cache:
            reader = QImageReader(str(source.path)); reader.setAutoTransform(True); self._cache[source.path] = reader.read()
        return self._cache[source.path]
    def _update(self, *_args):
        self.width.setEnabled(self.paper.currentText() == "Benutzerdefiniert"); self.height.setEnabled(self.paper.currentText() == "Benutzerdefiniert"); custom = self.count.currentData() == 0; self.rows.setEnabled(custom); self.columns.setEnabled(custom)
        try:
            settings = self.print_settings(); sources = self.sources_by_kind.get(settings.source, [])
            document = multi_image_document_from_settings(sources, settings, self._page_size(), source_kind=settings.source)
            self.page_plans = plan_multi_image_pages(document)
        except ValueError:
            self.page_plans = []
        self._set_page(self.page_index)
    def _set_page(self, index):
        self.page_index = min(max(0, index), max(0, len(self.page_plans) - 1)); self.preview.set_pages(self.page_plans, self.page_index, self._image)
        self.page_label.setText(f"Seite {self.page_index + 1} von {len(self.page_plans)}" if self.page_plans else "Seite 0 von 0"); self.previous.setEnabled(self.page_index > 0); self.next.setEnabled(self.page_index + 1 < len(self.page_plans)); self.pdf_button.setEnabled(bool(self.page_plans)); self.print_button.setEnabled(bool(self.page_plans))
    def _export_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, "Mehrbild-PDF speichern", "", "PDF-Datei (*.pdf)")
        if not path: return
        try: export_multi_page_plan_pdf(path, self.page_plans, self._image)
        except Exception as error: QMessageBox.critical(self, "PDF-Export fehlgeschlagen", str(error))
