"""Visible WYSIWYG single-image print dialog for BildBlick."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QSettings, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton, QScrollArea,
    QSplitter, QStyle, QStyleOptionButton, QStyleOptionViewItem, QStyledItemDelegate,
    QVBoxLayout, QWidget,
)

from printing.layout import CaptionOptions, ImageSourceInfo, MarginsMm, PageSizeMm, RectMm, SingleImageLayout, SizeMm
from printing.planner import plan_single_image
from printing.legacy_single_image import rotated_source_info
from printing.pdf_export import export_page_plan_pdf
from printing.wysiwyg_preview import WysiwygPagePreview
from printing.wysiwyg_ui import (
    SETTINGS_PANEL_WIDTH, configure_wysiwyg_form, configure_wysiwyg_scroll_area,
    apply_wysiwyg_theme, restore_wysiwyg_dialog_geometry, save_wysiwyg_dialog_geometry,
)
from i18n import LanguageManager


PROFILE_KEY = "printing/singleImageProfiles"
GEOMETRY_KEY = "printing/singleImageWysiwygDialogSize"
PAPER_SIZES = {"A4": (210.0, 297.0), "10 × 15 cm": (100.0, 150.0), "13 × 18 cm": (130.0, 180.0), "Letter": (215.9, 279.4)}
BUILTIN_PROFILES = {
    "A4 – Einpassen": {"paper": "A4", "scale": "fit"},
    "A4 – Seite füllen": {"paper": "A4", "scale": "fill"},
    "10 × 15 cm": {"paper": "10 × 15 cm", "scale": "fit"},
    "13 × 18 cm": {"paper": "13 × 18 cm", "scale": "fit"},
    "Originalgröße zentriert": {"paper": "A4", "scale": "original", "position": "center"},
    "Randlos – Seite füllen": {
        "paper": "A4", "width": 210, "height": 297,
        "orientation": "automatic", "margins": [0, 0, 0, 0], "linked": True,
        "scale": "fill", "image_width": 100, "image_height": 150,
        "lock": True, "position": "center", "rotation": 0,
        "filename": False, "date": False, "caption_size": 10,
        "caption_align": "center",
    },
}


class _WysiwygComboPopupDelegate(QStyledItemDelegate):
    """Paint a WYSIWYG combo popup with a dedicated indicator gutter.

    The macOS combo popup's default delegate takes the menu-item route, where
    the app's selection-accent checkmark is painted at x=7 independently from
    item stylesheet padding.  Painting one item view here gives its text a
    stable, explicit 28 px gutter and draws the checkmark exactly once.
    """

    INDICATOR_GUTTER_PX = 28

    def __init__(self, combo: QComboBox) -> None:
        super().__init__(combo.view())
        self._combo = combo

    def paint(self, painter, option, index) -> None:
        style = option.widget.style() if option.widget else self._combo.style()
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        background.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        background.features &= ~QStyleOptionViewItem.ViewItemFeature.HasDisplay
        background.text = ""
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, background, painter, option.widget)

        text_option = QStyleOptionViewItem(option)
        self.initStyleOption(text_option, index)
        text_option.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        text_option.rect = option.rect.adjusted(self.INDICATOR_GUTTER_PX, 0, 0, 0)
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, text_option, painter, option.widget)

        if index.row() == self._combo.currentIndex():
            indicator_size = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, None, option.widget)
            indicator_size = max(1, min(indicator_size, self.INDICATOR_GUTTER_PX - 8, option.rect.height() - 4))
            indicator = QStyleOptionButton()
            indicator.rect = QRect(
                option.rect.x() + 5,
                option.rect.y() + (option.rect.height() - indicator_size) // 2,
                indicator_size,
                indicator_size,
            )
            indicator.palette = option.palette
            indicator.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_On
            style.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorCheckBox, indicator, painter, option.widget)


def configure_wysiwyg_combo_popup(combo: QComboBox, object_name: str) -> _WysiwygComboPopupDelegate:
    """Apply the shared popup fix to one combo in this dialog only."""
    combo.setObjectName(object_name)
    combo.view().setObjectName(f"{object_name}PopupView")
    delegate = _WysiwygComboPopupDelegate(combo)
    combo.view().setItemDelegate(delegate)
    return delegate


# Compatibility for callers from earlier revisions.
_configure_wysiwyg_combo_popup = configure_wysiwyg_combo_popup


class SingleImageWysiwygPrintDialog(QDialog):
    """Edits one layout. The default preview intentionally has no hardware margin.

    It models PDF/virtual paper until the native printer dialog supplies the
    final hardware paint rectangle at print time.
    """
    def __init__(self, image: QImage, source: ImageSourceInfo, settings: QSettings, parent=None, theme_colors: dict[str, str] | None = None) -> None:
        super().__init__(parent)
        self.image, self.source, self.settings = image, source, settings
        self.page_plan = None
        self._custom_rect_mm: RectMm | None = None
        self._applying_state = False
        self.setObjectName("wysiwygSinglePrintDialog")
        # Keep checkbox spacing local while palette roles follow Light/Dark mode.
        apply_wysiwyg_theme(self, theme_colors)
        self.setWindowTitle("Drucken — BildBlick")
        outer = QVBoxLayout(self)
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        outer.addWidget(self.content_splitter, 1)
        controls = QWidget(self)
        controls.setObjectName("wysiwygPrintSettingsPanel")
        form = QFormLayout(controls)
        configure_wysiwyg_form(form)
        self.profile = QComboBox(controls); form.addRow("Profil:", self.profile)
        self.profile_popup_delegate = _configure_wysiwyg_combo_popup(self.profile, "profileCombo")
        self.borderless_hint = QLabel(
            "Randlosdruck muss vom Drucker und Papierformat unterstützt und gegebenenfalls im Druckdialog aktiviert werden.",
            controls,
        )
        self.borderless_hint.setObjectName("borderlessPrintHint")
        self.borderless_hint.setWordWrap(True)
        self.borderless_hint.setToolTip(
            "Nutzt die gesamte von Drucker und Treiber freigegebene Druckfläche. "
            "Echter Randlosdruck muss vom Drucker und Papierformat unterstützt werden."
        )
        self.borderless_hint.hide()
        form.addRow("", self.borderless_hint)
        self.paper = QComboBox(controls); self.paper.addItems([*PAPER_SIZES, "Benutzerdefiniert"]); form.addRow("Papierformat:", self.paper)
        self.paper_popup_delegate = _configure_wysiwyg_combo_popup(self.paper, "paperSizeCombo")
        self.width = self._spin(210); self.height = self._spin(297)
        form.addRow("Breite (mm):", self.width); form.addRow("Höhe (mm):", self.height)
        self.orientation = QComboBox(controls); self.orientation.addItem("Automatisch", "automatic"); self.orientation.addItem("Hochformat", "portrait"); self.orientation.addItem("Querformat", "landscape"); form.addRow("Ausrichtung:", self.orientation)
        self.orientation_popup_delegate = _configure_wysiwyg_combo_popup(self.orientation, "orientationCombo")
        self.margin_link = QCheckBox("Ränder koppeln", controls); self.margin_link.setChecked(True); form.addRow("", self.margin_link)
        self.margins = [self._spin(5) for _ in range(4)]
        for label, spin in zip(("Rand links:", "Rand oben:", "Rand rechts:", "Rand unten:"), self.margins): form.addRow(label, spin)
        self.scale = QComboBox(controls)
        for label, value in (("An Seite anpassen", "fit"), ("Seite füllen", "fill"), ("Originalgröße", "original"), ("Feste Größe", "fixed_size")): self.scale.addItem(label, value)
        form.addRow("Bildgröße:", self.scale)
        self.image_size_popup_delegate = _configure_wysiwyg_combo_popup(self.scale, "imageSizeCombo")
        self.image_width = self._spin(100); self.image_height = self._spin(150)
        form.addRow("Bildbreite (mm):", self.image_width); form.addRow("Bildhöhe (mm):", self.image_height)
        self.lock_aspect = QCheckBox("Seitenverhältnis sperren", controls); self.lock_aspect.setChecked(True); form.addRow("", self.lock_aspect)
        quick = QWidget(controls); quick_layout = QHBoxLayout(quick); quick_layout.setContentsMargins(0, 0, 0, 0)
        for text, size in (("10 × 15", (100, 150)), ("13 × 18", (130, 180))):
            button = QPushButton(text, quick); button.clicked.connect(lambda _checked=False, s=size: self._set_fixed_size(*s)); quick_layout.addWidget(button)
        form.addRow("Schnellwahl:", quick)
        self.position = QComboBox(controls)
        for label, value in (("Mitte", "center"), ("oben links", "top_left"), ("oben", "top"), ("oben rechts", "top_right"), ("links", "left"), ("rechts", "right"), ("unten links", "bottom_left"), ("unten", "bottom"), ("unten rechts", "bottom_right"), ("Benutzerdefiniert", "custom")): self.position.addItem(label, value)
        form.addRow("Position:", self.position)
        self.position_popup_delegate = _configure_wysiwyg_combo_popup(self.position, "positionCombo")
        self.rotation = QComboBox(controls)
        for value in (0, 90, 180, 270): self.rotation.addItem(f"{value}°", value)
        form.addRow("Zusatzrotation:", self.rotation)
        self.rotation_popup_delegate = _configure_wysiwyg_combo_popup(self.rotation, "rotationCombo")
        self.filename_caption = QCheckBox("Dateiname anzeigen", controls); self.date_caption = QCheckBox("Aufnahmedatum anzeigen", controls)
        form.addRow("Beschriftung:", self.filename_caption); form.addRow("", self.date_caption)
        self.caption_size = self._spin(10, 4, 36); form.addRow("Schriftgröße (pt):", self.caption_size)
        self.caption_align = QComboBox(controls); self.caption_align.addItem("Links", "left"); self.caption_align.addItem("Mitte", "center"); self.caption_align.addItem("Rechts", "right"); form.addRow("Textausrichtung:", self.caption_align)
        self.text_alignment_popup_delegate = _configure_wysiwyg_combo_popup(self.caption_align, "textAlignmentCombo")
        self.settings_scroll = QScrollArea(self)
        configure_wysiwyg_scroll_area(self.settings_scroll, controls)
        self.content_splitter.addWidget(self.settings_scroll)
        right_panel = QWidget(self)
        right_panel.setObjectName("wysiwygPreviewPanel")
        right = QVBoxLayout(right_panel)
        self.content_splitter.addWidget(right_panel)
        zoom_row = QHBoxLayout(); zoom_row.addWidget(QLabel("Vorschau-Zoom:"))
        self.zoom = QComboBox(self); self.zoom.addItem("An Fenster anpassen", 0)
        for value in (25, 50, 75, 100, 150, 200): self.zoom.addItem(f"{value} %", value)
        self.preview_zoom_popup_delegate = _configure_wysiwyg_combo_popup(self.zoom, "previewZoomCombo")
        zoom_row.addWidget(self.zoom); zoom_row.addStretch(); right.addLayout(zoom_row)
        self.preview = WysiwygPagePreview(self); preview_scroll = QScrollArea(self); preview_scroll.setWidgetResizable(True); preview_scroll.setWidget(self.preview); right.addWidget(preview_scroll, 1)
        buttons = QHBoxLayout(); self.save_profile_button = QPushButton("Profil speichern", self); self.delete_profile_button = QPushButton("Profil löschen", self); self.reset_geometry_button = QPushButton("Position und Größe zurücksetzen", self); self.pdf_button = QPushButton("Als PDF speichern …", self); self.print_button = QPushButton("Drucken", self); cancel = QPushButton("Abbrechen", self)
        for button in (self.save_profile_button, self.delete_profile_button, self.reset_geometry_button, self.pdf_button, self.print_button): buttons.addWidget(button)
        buttons.addStretch(); buttons.addWidget(cancel); outer.addLayout(buttons)
        self._populate_profiles()
        watched = [self.paper, self.width, self.height, self.orientation, self.margin_link, *self.margins, self.scale, self.image_width, self.image_height, self.lock_aspect, self.position, self.rotation, self.filename_caption, self.date_caption, self.caption_size, self.caption_align]
        for widget in watched:
            signal = getattr(widget, "currentIndexChanged", None) or getattr(widget, "valueChanged", None) or getattr(widget, "toggled", None)
            signal.connect(self._on_layout_setting_changed)
        self.zoom.currentIndexChanged.connect(lambda: self.preview.set_zoom_percent(int(self.zoom.currentData())))
        for spin in self.margins: spin.valueChanged.connect(lambda value, changed=spin: self._link_margins(changed, value))
        self.profile.currentIndexChanged.connect(self._load_selected_profile)
        self.save_profile_button.clicked.connect(self._save_profile); self.delete_profile_button.clicked.connect(self._delete_profile)
        self.reset_geometry_button.clicked.connect(self._reset_custom_geometry)
        self.preview.geometryEdited.connect(self._set_custom_geometry)
        self.preview.centerRequested.connect(self._center_image)
        self.pdf_button.clicked.connect(self._export_pdf); self.print_button.clicked.connect(self.accept); cancel.clicked.connect(self.reject)
        self.content_splitter.setSizes([SETTINGS_PANEL_WIDTH, 850])
        self.content_splitter.setStretchFactor(1, 1)
        apply_wysiwyg_theme(self, theme_colors)
        restore_wysiwyg_dialog_geometry(self, self.settings, GEOMETRY_KEY)
        self._update_preview()
        LanguageManager(self.settings).translate_widget_tree(self)

    def closeEvent(self, event) -> None:
        save_wysiwyg_dialog_geometry(self, self.settings, GEOMETRY_KEY)
        super().closeEvent(event)

    @staticmethod
    def _spin(value: float, minimum: float = 0.0, maximum: float = 1000.0) -> QDoubleSpinBox:
        spin = QDoubleSpinBox(); spin.setRange(minimum, maximum); spin.setDecimals(1); spin.setSuffix(" mm" if maximum > 36 else ""); spin.setValue(value); return spin

    def _set_fixed_size(self, width: float, height: float) -> None:
        self.scale.setCurrentIndex(self.scale.findData("fixed_size")); self.image_width.setValue(width); self.image_height.setValue(height)

    def _link_margins(self, changed, value) -> None:
        if self.margin_link.isChecked():
            for spin in self.margins:
                if spin is not changed: spin.blockSignals(True); spin.setValue(value); spin.blockSignals(False)
        self._update_preview()

    def _page_size(self) -> PageSizeMm:
        selected = self.paper.currentText()
        width, height = PAPER_SIZES.get(selected, (self.width.value(), self.height.value()))
        return PageSizeMm(width, height)

    def _orientation(self) -> str:
        selected = self.orientation.currentData()
        if selected != "automatic": return selected
        rotated_width = self.source.pixel_height if int(self.rotation.currentData()) % 180 else self.source.pixel_width
        rotated_height = self.source.pixel_width if int(self.rotation.currentData()) % 180 else self.source.pixel_height
        return "landscape" if rotated_width > rotated_height else "portrait"

    def build_layout(self, available_rect: RectMm | None = None, page_size: PageSizeMm | None = None, orientation: str | None = None) -> SingleImageLayout:
        mode = str(self.scale.currentData())
        requested = SizeMm(self.image_width.value(), self.image_height.value()) if mode == "fixed_size" else None
        position = "custom" if self._custom_rect_mm is not None else str(self.position.currentData())
        if position == "custom" and self._custom_rect_mm is None:
            position = "center"
        return SingleImageLayout(page_size or self._page_size(), orientation or self._orientation(), MarginsMm(*(spin.value() for spin in self.margins)), mode, requested, position, self.lock_aspect.isChecked(), CaptionOptions(self.filename_caption.isChecked(), self.date_caption.isChecked(), self.caption_size.value(), str(self.caption_align.currentData())), available_rect, self._custom_rect_mm)

    def build_page_plan(self, available_rect: RectMm | None = None, page_size: PageSizeMm | None = None):
        # Planner is the sole layout authority; rotation is renderer metadata.
        rotation = int(self.rotation.currentData())
        # A physical printer may change orientation in its native dialog. Its
        # reported page dimensions are authoritative for the final plan.
        final_orientation = ("landscape" if page_size.width_mm > page_size.height_mm else "portrait") if page_size else None
        return plan_single_image(rotated_source_info(self.source, rotation), self.build_layout(available_rect, page_size, final_orientation), rotation_degrees=rotation)

    def _update_preview(self, *_args) -> None:
        try:
            self.width.setEnabled(self.paper.currentText() == "Benutzerdefiniert"); self.height.setEnabled(self.paper.currentText() == "Benutzerdefiniert")
            enabled = self.scale.currentData() == "fixed_size"; self.image_width.setEnabled(enabled); self.image_height.setEnabled(enabled); self.lock_aspect.setEnabled(enabled)
            self.page_plan = self.build_page_plan()
            self.preview.set_lock_aspect_ratio(self.lock_aspect.isChecked())
            self.preview.set_page_plan(self.page_plan, lambda _source: self.image)
        except (TypeError, ValueError) as error:
            self.page_plan = None; self.preview.set_page_plan(None, lambda _source: self.image)
            self.setToolTip(str(error))

    def _on_layout_setting_changed(self, *_args) -> None:
        # Paper, margins, scaling, orientation and rotation reset a free
        # geometry. Choosing a named position does so too; caption-only
        # changes retain the image rectangle.
        if not self._applying_state and self.sender() is not self.lock_aspect:
            self._custom_rect_mm = None
        self._update_preview()

    def _set_custom_geometry(self, rect: RectMm) -> None:
        self._custom_rect_mm = rect
        self._applying_state = True
        self.position.setCurrentIndex(self.position.findData("custom"))
        self._applying_state = False
        self._update_preview()

    def _center_image(self) -> None:
        self._custom_rect_mm = None
        self._applying_state = True
        self.position.setCurrentIndex(self.position.findData("center"))
        self._applying_state = False
        self._update_preview()

    def _reset_custom_geometry(self) -> None:
        self._custom_rect_mm = None
        if self.position.currentData() == "custom":
            self._applying_state = True
            self.position.setCurrentIndex(self.position.findData("center"))
            self._applying_state = False
        self._update_preview()

    def _state(self) -> dict:
        return {"paper": self.paper.currentText(), "width": self.width.value(), "height": self.height.value(), "orientation": self.orientation.currentData(), "margins": [spin.value() for spin in self.margins], "linked": self.margin_link.isChecked(), "scale": self.scale.currentData(), "image_width": self.image_width.value(), "image_height": self.image_height.value(), "lock": self.lock_aspect.isChecked(), "position": self.position.currentData(), "rotation": self.rotation.currentData(), "filename": self.filename_caption.isChecked(), "date": self.date_caption.isChecked(), "caption_size": self.caption_size.value(), "caption_align": self.caption_align.currentData()}

    def _apply_state(self, state: dict) -> None:
        self._custom_rect_mm = None
        def choose(combo, value):
            index = combo.findData(value); combo.setCurrentIndex(index if index >= 0 else combo.findText(str(value)))
        self.paper.setCurrentText(state.get("paper", "A4")); self.width.setValue(state.get("width", 210)); self.height.setValue(state.get("height", 297)); choose(self.orientation, state.get("orientation", "automatic"))
        for spin, value in zip(self.margins, state.get("margins", [5] * 4)): spin.setValue(float(value))
        self.margin_link.setChecked(state.get("linked", True)); choose(self.scale, state.get("scale", "fit")); self.image_width.setValue(state.get("image_width", 100)); self.image_height.setValue(state.get("image_height", 150)); self.lock_aspect.setChecked(state.get("lock", True)); choose(self.position, state.get("position", "center")); choose(self.rotation, state.get("rotation", 0)); self.filename_caption.setChecked(state.get("filename", False)); self.date_caption.setChecked(state.get("date", False)); self.caption_size.setValue(state.get("caption_size", 10)); choose(self.caption_align, state.get("caption_align", "center")); self._update_preview()

    def _profiles(self) -> dict:
        value = self.settings.value(PROFILE_KEY, {})
        return value if isinstance(value, dict) else {}

    def _populate_profiles(self) -> None:
        self.profile.blockSignals(True); self.profile.clear()
        for name in BUILTIN_PROFILES: self.profile.addItem(name, ("builtin", name))
        for name in sorted(self._profiles()): self.profile.addItem(name, ("user", name))
        self.profile.blockSignals(False); self.delete_profile_button.setEnabled(False)

    def _load_selected_profile(self) -> None:
        kind, name = self.profile.currentData(); state = BUILTIN_PROFILES[name] if kind == "builtin" else self._profiles().get(name, {})
        self.delete_profile_button.setEnabled(kind == "user")
        self.borderless_hint.setVisible(kind == "builtin" and name == "Randlos – Seite füllen")
        self._apply_state(state)

    def _save_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "Profil speichern", "Profilname:")
        if not ok or not name.strip(): return
        if name.strip() in BUILTIN_PROFILES: QMessageBox.warning(self, "Profil", "Eingebaute Profile können nicht überschrieben werden."); return
        profiles = self._profiles(); profiles[name.strip()] = self._state(); self.settings.setValue(PROFILE_KEY, profiles); self.settings.sync(); self._populate_profiles(); self.profile.setCurrentIndex(self.profile.findText(name.strip()))

    def _delete_profile(self) -> None:
        data = self.profile.currentData()
        if not data or data[0] != "user": return
        profiles = self._profiles(); profiles.pop(data[1], None); self.settings.setValue(PROFILE_KEY, profiles); self.settings.sync(); self._populate_profiles()

    def _export_pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Als PDF speichern", self.source.path.with_suffix(".pdf").as_posix(), "PDF-Dateien (*.pdf)")
        if not path: return
        try:
            target = export_page_plan_pdf(path, self.build_page_plan(), lambda _source: self.image)
            QMessageBox.information(self, "PDF gespeichert", f"PDF wurde gespeichert:\n{target}")
        except Exception as error:
            QMessageBox.critical(self, "PDF konnte nicht gespeichert werden", str(error))
