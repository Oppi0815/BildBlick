from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt
from PySide6.QtGui import QImage, QPalette
from PySide6.QtWidgets import QApplication

from printing.layout import ImageSourceInfo, RectMm
from printing.wysiwyg_dialog import SingleImageWysiwygPrintDialog


def _dialog(tmp_path):
    QApplication.instance() or QApplication([])
    image = QImage(1200, 800, QImage.Format.Format_RGB32)
    source = ImageSourceInfo(Path("example.jpg"), 1200, 800, 300, 300, "example.jpg", "10.08.2026")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    return SingleImageWysiwygPrintDialog(image, source, settings)


def test_dialog_replans_for_paper_margins_rotation_and_caption(tmp_path):
    dialog = _dialog(tmp_path)
    initial = dialog.build_page_plan()
    dialog.paper.setCurrentText("10 × 15 cm")
    dialog.orientation.setCurrentIndex(dialog.orientation.findData("portrait"))
    dialog.margins[0].setValue(8)
    dialog.rotation.setCurrentIndex(dialog.rotation.findData(90))
    dialog.filename_caption.setChecked(True)
    changed = dialog.build_page_plan()
    assert changed.page_size.width_mm == 100
    assert changed.printable_rect.x_mm == 8
    assert changed.image_elements[0].rotation_degrees == 90
    assert changed.text_elements
    assert changed != initial


def test_dialog_has_local_indicator_spacing_and_shared_popup_delegates(tmp_path):
    dialog = _dialog(tmp_path)
    assert dialog.objectName() == "singleImageWysiwygPrintDialog"
    assert "QCheckBox { spacing: 8px; }" in dialog.styleSheet()
    assert "#ffffff" not in dialog.styleSheet().lower()
    assert "palette(window-text)" in dialog.styleSheet()
    combos = (
        (dialog.profile, dialog.profile_popup_delegate, "profileCombo"),
        (dialog.paper, dialog.paper_popup_delegate, "paperSizeCombo"),
        (dialog.orientation, dialog.orientation_popup_delegate, "orientationCombo"),
        (dialog.scale, dialog.image_size_popup_delegate, "imageSizeCombo"),
        (dialog.position, dialog.position_popup_delegate, "positionCombo"),
        (dialog.caption_align, dialog.text_alignment_popup_delegate, "textAlignmentCombo"),
        (dialog.zoom, dialog.preview_zoom_popup_delegate, "previewZoomCombo"),
    )
    for combo, delegate, object_name in combos:
        assert combo.objectName() == object_name
        assert combo.view().objectName() == f"{object_name}PopupView"
        assert combo.view().itemDelegate() is delegate
        assert delegate.INDICATOR_GUTTER_PX == 28
    assert [dialog.orientation.itemText(index) for index in range(dialog.orientation.count())] == [
        "Automatisch", "Hochformat", "Querformat",
    ]


def test_fixed_size_and_profile_round_trip(tmp_path, monkeypatch):
    dialog = _dialog(tmp_path)
    dialog._set_fixed_size(90, 60)
    assert dialog.build_page_plan().image_elements[0].target_rect.width_mm == 90
    monkeypatch.setattr("printing.wysiwyg_dialog.QInputDialog.getText", lambda *_args: ("Mein Profil", True))
    dialog._save_profile()
    assert "Mein Profil" in dialog._profiles()
    dialog._apply_state({"paper": "A4", "scale": "fill"})
    dialog.profile.setCurrentIndex(dialog.profile.findText("Mein Profil"))
    dialog._load_selected_profile()
    assert dialog.scale.currentData() == "fixed_size"


def test_borderless_fill_profile_resets_geometry_and_shows_hint(tmp_path):
    dialog = _dialog(tmp_path)
    dialog._set_custom_geometry(RectMm(12, 15, 80, 50))
    dialog.profile.setCurrentIndex(dialog.profile.findText("Randlos – Seite füllen"))
    dialog._load_selected_profile()
    assert dialog._custom_rect_mm is None
    assert [margin.value() for margin in dialog.margins] == [0, 0, 0, 0]
    assert dialog.scale.currentData() == "fill"
    assert dialog.position.currentData() == "center"
    assert not dialog.filename_caption.isChecked() and not dialog.date_caption.isChecked()
    assert dialog.lock_aspect.isChecked() and not dialog.borderless_hint.isHidden()
    dialog.profile.setCurrentIndex(dialog.profile.findText("A4 – Einpassen"))
    dialog._load_selected_profile()
    assert dialog.borderless_hint.isHidden()


def test_dialog_uses_screen_bounded_geometry_and_a_non_scrolling_settings_panel(tmp_path):
    dialog = _dialog(tmp_path)
    assert dialog.minimumWidth() >= 720
    assert dialog.settings_scroll.widgetResizable()
    assert dialog.settings_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert dialog.settings_scroll.minimumWidth() >= 420
    assert dialog.content_splitter.sizes()[1] >= dialog.content_splitter.sizes()[0]


def test_tiny_saved_dialog_size_is_not_restored(tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("printing/singleImageWysiwygDialogSize", QSize(100, 100))
    image = QImage(1200, 800, QImage.Format.Format_RGB32)
    source = ImageSourceInfo(Path("example.jpg"), 1200, 800, 300, 300, "example.jpg", "10.08.2026")
    dialog = SingleImageWysiwygPrintDialog(image, source, settings)
    assert dialog.size().width() >= dialog.minimumWidth()
    assert dialog.size().height() >= dialog.minimumHeight()


def test_single_dialog_uses_the_same_supplied_theme_palette(tmp_path):
    image = QImage(1200, 800, QImage.Format.Format_RGB32)
    source = ImageSourceInfo(Path("example.jpg"), 1200, 800, 300, 300, "example.jpg", "10.08.2026")
    colors = {
        "window": "#20242a", "panel": "#292e35", "preview": "#252a30",
        "text": "#edf0f3", "button": "#343a42", "selection": "#3b8edb",
        "selection_text": "#ffffff",
    }
    dialog = SingleImageWysiwygPrintDialog(image, source, QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat), theme_colors=colors)
    assert dialog.palette().color(QPalette.ColorGroup.Active, QPalette.ColorRole.Window).name() == colors["window"]
    assert dialog.palette().color(QPalette.ColorGroup.Active, QPalette.ColorRole.Base).name() == colors["panel"]
