from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QRectF
from PySide6.QtGui import QColor, QImage, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from printing.layout import ImageSourceInfo
from printing.multi_wysiwyg_dialog import MultiImageWysiwygPrintDialog
from printing.renderer import MmTransform


def test_multi_wysiwyg_dialog_builds_live_page_plans_and_navigates(tmp_path):
    QApplication.instance() or QApplication([])
    sources = [ImageSourceInfo(Path(f"{index}.jpg"), 1600, 900, filename=f"{index}.jpg") for index in range(5)]
    dialog = MultiImageWysiwygPrintDialog({"current": sources[:1], "selected": sources[1:3], "all": sources}, QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    assert dialog.windowTitle() == "Mehrere Bilder drucken — BildBlick"
    dialog.source.setCurrentIndex(dialog.source.findData("all"))
    dialog.count.setCurrentIndex(dialog.count.findData(4))
    assert [len(page.image_elements) for page in dialog.page_plans] == [4, 1]
    assert dialog.page_label.text() == "Seite 1 von 2"
    dialog._set_page(1)
    assert dialog.page_label.text() == "Seite 2 von 2"
    dialog.paper.setCurrentText("10 × 15 cm")
    assert (dialog.page_plans[0].page_size.width_mm, dialog.page_plans[0].page_size.height_mm) == (100, 150)


def test_dialog_prefers_selected_then_all_then_current_as_its_initial_source(tmp_path):
    QApplication.instance() or QApplication([])
    images = [ImageSourceInfo(Path(f"{index}.jpg"), 1600, 900, filename=f"{index}.jpg") for index in range(3)]
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    selected = MultiImageWysiwygPrintDialog({"current": images[:1], "selected": images[1:], "all": images}, settings)
    all_images = MultiImageWysiwygPrintDialog({"current": images[:1], "selected": images[:1], "all": images}, settings)
    current = MultiImageWysiwygPrintDialog({"current": images[:1], "selected": [], "all": images[:1]}, settings)
    assert selected.source.currentData() == "selected"
    assert all_images.source.currentData() == "all"
    assert current.source.currentData() == "current"


def test_multi_wysiwyg_dialog_uses_contact_sheet_pageplan_text(tmp_path):
    QApplication.instance() or QApplication([])
    source = ImageSourceInfo(Path("photo.jpg"), 1600, 900, filename="photo.jpg", capture_date="10.08.2026")
    dialog = MultiImageWysiwygPrintDialog({"current": [source], "selected": [], "all": [source]}, QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    dialog.contact.setChecked(True); dialog.filename.setChecked(True); dialog.capture.setChecked(True); dialog.show_header.setChecked(True); dialog.header.setText("Titel")
    roles = {text.semantic_role for text in dialog.page_plans[0].text_elements}
    capture_date = next(text for text in dialog.page_plans[0].text_elements if text.semantic_role == "capture_date")
    assert {"filename", "capture_date", "header", "page_number"} <= roles
    assert capture_date.text == "10.08.2026"


def test_multi_wysiwyg_dialog_omits_capture_date_when_disabled(tmp_path):
    QApplication.instance() or QApplication([])
    source = ImageSourceInfo(Path("photo.jpg"), 1600, 900, filename="photo.jpg", capture_date="10.08.2026")
    dialog = MultiImageWysiwygPrintDialog({"current": [source], "selected": [], "all": [source]}, QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    dialog.contact.setChecked(True)
    dialog.capture.setChecked(False)
    assert "capture_date" not in {text.semantic_role for text in dialog.page_plans[0].text_elements}


def test_dialog_keeps_drag_order_and_removals_in_the_print_model(tmp_path):
    QApplication.instance() or QApplication([])
    sources = [ImageSourceInfo(Path(f"{index}.jpg"), 1600, 900, filename=f"{index}.jpg") for index in range(3)]
    dialog = MultiImageWysiwygPrintDialog({"current": sources[:1], "selected": [], "all": sources}, QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    dialog.source.setCurrentIndex(dialog.source.findData("all"))
    item = dialog.image_list.takeItem(2); dialog.image_list.insertItem(0, item); dialog._sync_list_order()
    assert [source.filename for source in dialog.selected_sources()] == ["2.jpg", "0.jpg", "1.jpg"]
    dialog.image_list.item(1).setSelected(True); dialog._remove_selected()
    assert [source.filename for source in dialog.selected_sources()] == ["2.jpg", "1.jpg"]
    assert [image.source.filename for page in dialog.page_plans for image in page.image_elements] == ["2.jpg", "1.jpg"]
    dialog._reset_order()
    assert [source.filename for source in dialog.selected_sources()] == ["0.jpg", "1.jpg", "2.jpg"]


def test_multi_dialog_uses_palette_friendly_list_and_resizable_settings_panel(tmp_path):
    QApplication.instance() or QApplication([])
    source = ImageSourceInfo(Path("very-long-file-name.jpg"), 1600, 900, filename="very-long-file-name.jpg")
    dialog = MultiImageWysiwygPrintDialog({"current": [source]}, QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    assert dialog.settings_scroll.widgetResizable()
    assert dialog.settings_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert dialog.settings_scroll.minimumWidth() >= 420
    assert dialog.image_list.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert dialog.image_list.textElideMode() == Qt.TextElideMode.ElideMiddle
    assert dialog.image_list.maximumHeight() == 180
    assert dialog.image_list.item(0).toolTip() == "very-long-file-name.jpg"
    assert dialog.image_list.palette().color(dialog.image_list.backgroundRole()).isValid()
    assert "palette(base)" in dialog.styleSheet()
    assert "#000000" not in dialog.styleSheet().lower()
    assert dialog.profile.view().itemDelegate() is dialog.profile_popup_delegate


def test_action_buttons_keep_their_complete_natural_width(tmp_path):
    QApplication.instance() or QApplication([])
    dialog = MultiImageWysiwygPrintDialog({"current": []}, QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    for button, text in (
        (dialog.reset_order_button, "Reihenfolge zurücksetzen"),
        (dialog.remove_button, "Auswahl entfernen"),
        (dialog.reload_button, "Quelle neu laden"),
    ):
        assert button.text() == text
        assert button.minimumWidth() >= button.sizeHint().width()


def test_dialog_uses_theme_palette_roles_without_fixed_light_or_dark_backgrounds(tmp_path):
    QApplication.instance() or QApplication([])
    colors = {
        "window": "#20242a", "panel": "#292e35", "preview": "#252a30",
        "text": "#edf0f3", "button": "#343a42", "selection": "#3b8edb",
        "selection_text": "#ffffff",
    }
    dialog = MultiImageWysiwygPrintDialog({"current": []}, QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat), theme_colors=colors)
    palette = dialog.palette()
    assert palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Window).name() == colors["window"]
    assert palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Base).name() != "#ffffff"
    assert palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.WindowText).name() == colors["text"]
    assert dialog.settings_scroll.viewport().palette().color(QPalette.ColorRole.Window).name() == colors["window"]
    assert dialog.image_list.palette().color(QPalette.ColorRole.Base).name() == colors["panel"]
    assert colors["window"] in dialog.styleSheet()
    assert colors["panel"] in dialog.styleSheet()
    assert "background-color: #ffffff" not in dialog.styleSheet().lower()
    assert "#000000" not in dialog.styleSheet().lower()
    assert "QDialog#wysiwygMultiPrintDialog" in dialog.styleSheet()
    assert "QCheckBox:disabled" in dialog.styleSheet()
    assert f"background-color: {colors['preview']};" in dialog.styleSheet()
    assert "QComboBox::drop-down" in dialog.styleSheet()
    assert "QSpinBox::up-button" in dialog.styleSheet()
    assert "QComboBox:focus" in dialog.styleSheet()
    assert f"border: 2px solid {colors['selection']}" in dialog.styleSheet()
    assert dialog.profile.property("wysiwygDarkArrowStyle")
    assert dialog.rows.property("wysiwygDarkArrowStyle")
    assert dialog.profile.findChild(QWidget, "wysiwygComboDownArrow") is not None
    assert dialog.rows.findChild(QWidget, "wysiwygSpinUpArrow") is not None
    assert dialog.rows.findChild(QWidget, "wysiwygSpinDownArrow") is not None


def test_multi_dialog_clamps_a_tiny_saved_size(tmp_path):
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("printing/multiImageWysiwygDialogSize", QSize(100, 100))
    dialog = MultiImageWysiwygPrintDialog({"current": []}, settings)
    assert dialog.size().width() >= dialog.minimumWidth()
    assert dialog.size().height() >= dialog.minimumHeight()


def test_footer_options_flow_into_the_wysiwyg_page_plan(tmp_path):
    QApplication.instance() or QApplication([])
    source = ImageSourceInfo(Path("/tmp/Urlaub/1.jpg"), 1600, 900, filename="1.jpg")
    dialog = MultiImageWysiwygPrintDialog({"current": [source], "all": [source]}, QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    dialog.footer_folder.setChecked(True)
    roles = {text.semantic_role for text in dialog.page_plans[0].text_elements}
    assert "folder" in roles
    assert next(text.text for text in dialog.page_plans[0].text_elements if text.semantic_role == "folder") == "Urlaub"
    assert "print_date" not in roles
    assert "page_number" in roles
    dialog.print_date.setChecked(True)
    roles = {text.semantic_role for text in dialog.page_plans[0].text_elements}
    assert {"folder", "page_number", "print_date"} <= roles
    assert next(text.text for text in dialog.page_plans[0].text_elements if text.semantic_role == "print_date") == dialog.print_date_text()
    dialog.footer_folder.setChecked(False)
    dialog.print_date.setChecked(False)
    roles = {text.semantic_role for text in dialog.page_plans[0].text_elements}
    assert "folder" not in roles
    assert "print_date" not in roles
    assert "page_number" in roles


def test_footer_folder_comes_from_the_current_image_folder(tmp_path):
    QApplication.instance() or QApplication([])
    current = ImageSourceInfo(Path("/tmp/Aktueller Ordner/current.jpg"), 1600, 900, filename="current.jpg")
    other = ImageSourceInfo(Path("/tmp/Andere Bilder/other.jpg"), 1600, 900, filename="other.jpg")
    dialog = MultiImageWysiwygPrintDialog({"current": [current], "all": [other]}, QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    dialog.source.setCurrentIndex(dialog.source.findData("all"))
    dialog.footer_folder.setChecked(True)
    folder = next(text.text for text in dialog.page_plans[0].text_elements if text.semantic_role == "folder")
    assert folder == "Aktueller Ordner"


def test_multi_wysiwyg_preview_shows_header_and_footer_from_the_real_dialog_pageplan(tmp_path):
    QApplication.instance() or QApplication([])
    source = ImageSourceInfo(Path("/tmp/TESTORDNER/real-preview.jpg"), 1600, 900, filename="real-preview.jpg", capture_date="10.08.2026")
    dialog = MultiImageWysiwygPrintDialog({"current": [source], "selected": [], "all": [source]}, QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    dialog.resize(1280, 900)
    dialog.show_header.setChecked(True)
    dialog.header.setText("ECHTER TITEL")
    dialog.contact.setChecked(True)
    dialog.filename.setChecked(True)
    dialog.capture.setChecked(True)
    dialog.footer_folder.setChecked(True)
    dialog.page_number.setChecked(True)
    dialog.print_date.setChecked(True)
    dialog._print_date_text = "11.08.2026"
    dialog.paper.setCurrentText("A4")
    dialog.count.setCurrentIndex(dialog.count.findData(1))
    QApplication.processEvents()
    assert dialog.page_plans
    header = next(text for text in dialog.page_plans[0].text_elements if text.semantic_role == "header")
    capture_date = next(text for text in dialog.page_plans[0].text_elements if text.semantic_role == "capture_date")
    folder = next(text for text in dialog.page_plans[0].text_elements if text.semantic_role == "folder")
    page_number = next(text for text in dialog.page_plans[0].text_elements if text.semantic_role == "page_number")
    print_date = next(text for text in dialog.page_plans[0].text_elements if text.semantic_role == "print_date")
    assert header.text == "ECHTER TITEL"
    assert capture_date.text == "10.08.2026"
    assert folder.text == "TESTORDNER"
    assert page_number.text == "Seite 1 von 1"
    assert print_date.text == "11.08.2026"

    dialog.show()
    QApplication.processEvents()
    pixmap = dialog.preview.grab()
    image = pixmap.toImage()
    image_dpr = image.devicePixelRatio() or 1.0
    available = QRectF(dialog.preview.rect()).adjusted(16, 16, -16, -16)
    scale = min(available.width() / dialog.page_plans[0].page_size.width_mm, available.height() / dialog.page_plans[0].page_size.height_mm)
    paper = QRectF(
        available.center().x() - dialog.page_plans[0].page_size.width_mm * scale / 2,
        available.center().y() - dialog.page_plans[0].page_size.height_mm * scale / 2,
        dialog.page_plans[0].page_size.width_mm * scale,
        dialog.page_plans[0].page_size.height_mm * scale,
    )
    header_rect = MmTransform(dialog.page_plans[0], paper).rect_to_target(header.rect)
    transform = MmTransform(dialog.page_plans[0], paper)

    def has_dark_text_pixels(rect: QRectF) -> bool:
        pixel_rect = QRectF(
            rect.x() * image_dpr,
            rect.y() * image_dpr,
            rect.width() * image_dpr,
            rect.height() * image_dpr,
        )
        tolerance = 2
        for y in range(max(0, int(pixel_rect.top()) - tolerance), min(image.height(), int(pixel_rect.bottom()) + tolerance + 1)):
            for x in range(max(0, int(pixel_rect.left()) - tolerance), min(image.width(), int(pixel_rect.right()) + tolerance + 1)):
                color = image.pixelColor(x, y)
                if color.alpha() > 0 and color.red() < 200 and color.green() < 200 and color.blue() < 200:
                    return True
        return False

    assert has_dark_text_pixels(header_rect)
    assert has_dark_text_pixels(transform.rect_to_target(capture_date.rect))
    assert has_dark_text_pixels(transform.rect_to_target(folder.rect))
    assert has_dark_text_pixels(transform.rect_to_target(page_number.rect))
    assert has_dark_text_pixels(transform.rect_to_target(print_date.rect))
