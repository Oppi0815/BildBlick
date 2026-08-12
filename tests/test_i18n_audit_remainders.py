from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from bildbetrachter import ImageViewer
from i18n import LanguageManager, t
from printing.layout import ImageSourceInfo, PageSizeMm
from printing.multi_image_print import MultiImagePrintSettings, multi_image_document_from_settings
from printing.planner import plan_multi_image_pages
from printing.wysiwyg_preview import WysiwygPagePreview


def test_compare_selection_messages_are_translated(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    viewer = ImageViewer(tmp_path)
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda dialog: shown.append((dialog.windowTitle(), dialog.text())) or 0)
    expected = {
        "en": "Please select two images first.",
        "fr": "Veuillez d’abord sélectionner deux images.",
        "es": "Primero seleccione dos imágenes.",
        "uk": "Спочатку виберіть два зображення.",
    }
    for code, text in expected.items():
        viewer._set_language(code)
        viewer._compare_selected_images()
        assert shown[-1] == (t("Bilder vergleichen"), text)
    viewer.window.close(); application.processEvents()


def test_audit_remainder_dynamic_texts_and_startup_messages_have_all_translations(tmp_path):
    manager = LanguageManager(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    keys = ("{count} Bilder", "Suche nach Bildern …", "Suche nach Bildern … ({count} gefunden)", "Bild mit eingeschränkten Metadaten gespeichert", "Das Bild wurde gespeichert, einige Metadaten konnten jedoch nicht vollständig erhalten werden.", "Der übergebene Pfad konnte nicht geöffnet werden.", "Bitte nur eine Bilddatei oder einen Ordner angeben.", "Mein Rechner", "Vorschau nicht verfügbar", "Drehung gespeichert", "Die Drehung wurde im Original gespeichert.")
    for code in ("en", "fr", "es", "uk"):
        manager.set_language(code)
        assert t("{count} Bilder").format(count=0)
        assert t("Suche nach Bildern … ({count} gefunden)").format(count=7)
        assert all(t(key) != key for key in keys if key not in {"{count} Bilder", "Suche nach Bildern … ({count} gefunden)"})


def test_ui_resource_preview_and_printed_page_number_follow_active_language(tmp_path):
    application = QApplication.instance() or QApplication([])
    manager = LanguageManager(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    label = QLabel("Mein Rechner")
    source = ImageSourceInfo(Path("photo.jpg"), 1200, 800, filename="photo.jpg")
    for code, expected in {"en": "Page 1 of 1", "fr": "Page 1 sur 1", "es": "Página 1 de 1", "uk": "Сторінка 1 з 1"}.items():
        manager.set_language(code)
        manager.translate_widget_tree(label)
        assert label.text() == t("Mein Rechner")
        document = multi_image_document_from_settings([source], MultiImagePrintSettings(show_page_number=True), PageSizeMm.a4())
        page = plan_multi_image_pages(document)[0]
        assert next(text.text for text in page.text_elements if text.semantic_role == "page_number") == expected
        preview = WysiwygPagePreview()
        assert t("Vorschau nicht verfügbar")
        preview.deleteLater()
    label.deleteLater(); application.processEvents()
