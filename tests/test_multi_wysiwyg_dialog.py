from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from printing.layout import ImageSourceInfo
from printing.multi_wysiwyg_dialog import MultiImageWysiwygPrintDialog


def test_multi_wysiwyg_dialog_builds_live_page_plans_and_navigates(tmp_path):
    QApplication.instance() or QApplication([])
    sources = [ImageSourceInfo(Path(f"{index}.jpg"), 1600, 900, filename=f"{index}.jpg") for index in range(5)]
    dialog = MultiImageWysiwygPrintDialog({"current": sources[:1], "selected": sources[1:3], "all": sources}, QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    dialog.source.setCurrentIndex(dialog.source.findData("all"))
    dialog.count.setCurrentIndex(dialog.count.findData(4))
    assert [len(page.image_elements) for page in dialog.page_plans] == [4, 1]
    assert dialog.page_label.text() == "Seite 1 von 2"
    dialog._set_page(1)
    assert dialog.page_label.text() == "Seite 2 von 2"
    dialog.paper.setCurrentText("10 × 15 cm")
    assert (dialog.page_plans[0].page_size.width_mm, dialog.page_plans[0].page_size.height_mm) == (100, 150)


def test_multi_wysiwyg_dialog_uses_contact_sheet_pageplan_text(tmp_path):
    QApplication.instance() or QApplication([])
    source = ImageSourceInfo(Path("photo.jpg"), 1600, 900, filename="photo.jpg", capture_date="10.08.2026")
    dialog = MultiImageWysiwygPrintDialog({"current": [source], "selected": [], "all": [source]}, QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    dialog.contact.setChecked(True); dialog.filename.setChecked(True); dialog.show_header.setChecked(True); dialog.header.setText("Titel")
    roles = {text.semantic_role for text in dialog.page_plans[0].text_elements}
    assert {"filename", "header", "page_number"} <= roles


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
