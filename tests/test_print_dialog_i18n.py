from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from i18n import LanguageManager, t
from printing.layout import ImageSourceInfo
from printing.multi_wysiwyg_dialog import MultiImageWysiwygPrintDialog
from printing.wysiwyg_dialog import SingleImageWysiwygPrintDialog


def _settings(tmp_path):
    QApplication.instance() or QApplication([])
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


def _source(name="photo.jpg"):
    return ImageSourceInfo(Path(name), 1200, 800, 300, 300, name, "10.08.2026")


def _single(tmp_path):
    return SingleImageWysiwygPrintDialog(
        QImage(1200, 800, QImage.Format.Format_RGB32), _source(), _settings(tmp_path)
    )


def _multi(tmp_path):
    sources = [_source(f"{index}.jpg") for index in range(3)]
    return MultiImageWysiwygPrintDialog(
        {"current": sources[:1], "selected": sources[1:], "all": sources}, _settings(tmp_path)
    )


def test_single_print_dialog_translates_visible_controls_in_all_languages(tmp_path):
    expected = {
        "en": ("Print — BildBlick", "Paper size:", "Save as PDF …"),
        "fr": ("Imprimer — BildBlick", "Format de papier :", "Enregistrer au format PDF …"),
        "es": ("Imprimir — BildBlick", "Tamaño de papel:", "Guardar como PDF …"),
        "uk": ("Друк — BildBlick", "Формат паперу:", "Зберегти як PDF …"),
    }
    for code, (title, label, button) in expected.items():
        dialog = _single(tmp_path / code)
        LanguageManager(dialog.settings).set_language(code)
        assert dialog.windowTitle() == title
        assert label in [item.text() for item in dialog.findChildren(type(dialog.borderless_hint))]
        assert dialog.pdf_button.text() == button
        assert dialog.paper.itemText(dialog.paper.findText(t("Benutzerdefiniert"))) == t("Benutzerdefiniert")
        dialog.close()


def test_multi_print_dialog_translates_controls_and_dynamic_status_in_all_languages(tmp_path):
    expected = {
        "en": ("Print multiple images — BildBlick", "Grid:", "Page 1 of 2", "2 images · 2 pages · 1 per page"),
        "fr": ("Imprimer plusieurs images — BildBlick", "Grille :", "Page 1 sur 2", "2 images · 2 pages · 1 par page"),
        "es": ("Imprimir varias imágenes — BildBlick", "Cuadrícula:", "Página 1 de 2", "2 imágenes · 2 páginas · 1 por página"),
        "uk": ("Друк кількох зображень — BildBlick", "Сітка:", "Сторінка 1 з 2", "2 зображень · 2 сторінок · 1 на сторінці"),
    }
    for code, (title, grid, page, status) in expected.items():
        dialog = _multi(tmp_path / code)
        LanguageManager(dialog.settings).set_language(code)
        dialog._set_page(0)
        assert dialog.windowTitle() == title
        assert grid in [label.text() for label in dialog.findChildren(type(dialog.page_label))]
        assert dialog.page_label.text() == page
        assert dialog.status_label.text() == status
        assert dialog.profile.itemText(0) == t("Standard")
        dialog.close()


def test_print_error_keeps_technical_detail_inside_translated_frame(tmp_path):
    settings = _settings(tmp_path)
    manager = LanguageManager(settings)
    for code, expected in {
        "en": "Print error: driver offline",
        "fr": "Erreur d’impression : driver offline",
        "es": "Error de impresión: driver offline",
        "uk": "Помилка друку: driver offline",
    }.items():
        manager.set_language(code)
        assert t("Druckfehler: {detail}").format(detail="driver offline") == expected


def test_print_dialogs_refresh_when_the_language_changes(tmp_path):
    dialog = _single(tmp_path)
    manager = LanguageManager(dialog.settings)
    manager.set_language("fr")
    assert dialog.print_button.text() == "Imprimer"
    manager.set_language("uk")
    assert dialog.print_button.text() == "Друкувати"
    dialog.close()

    multi = _multi(tmp_path / "multi")
    manager = LanguageManager(multi.settings)
    manager.set_language("en")
    assert multi.page_label.text() == "Page 1 of 2"
    manager.set_language("fr")
    assert multi.page_label.text() == "Page 1 sur 2"
    assert multi.status_label.text() == "2 images · 2 pages · 1 par page"
    multi.close()
