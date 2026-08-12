from pathlib import Path

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtWidgets import QApplication

from bildbetrachter import ImageViewer
from i18n import LanguageManager, t
from pdf_support import load_pdf


class _Link:
    def __init__(self, url: str = "", page: int = -1):
        self._url = QUrl(url)
        self._page = page

    def url(self):
        return self._url

    def page(self):
        return self._page


def test_pdf_load_errors_are_translated_in_all_foreign_languages(tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    manager = LanguageManager(settings)
    expected = {
        "en": "The PDF file was not found.",
        "fr": "Le fichier PDF est introuvable.",
        "es": "No se encontró el archivo PDF.",
        "uk": "Файл PDF не знайдено.",
    }
    for code, message in expected.items():
        manager.set_language(code)
        assert load_pdf(tmp_path / "missing.pdf").error == message


def test_pdf_navigation_and_internal_link_tooltip_use_placeholders_in_all_languages(tmp_path):
    manager = LanguageManager(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    expected = {
        "en": ("Page 2 of 7", "Page 4"),
        "fr": ("Page 2 sur 7", "Page 4"),
        "es": ("Página 2 de 7", "Página 4"),
        "uk": ("Сторінка 2 з 7", "Сторінка 4"),
    }
    for code, texts in expected.items():
        manager.set_language(code)
        assert t("Seite {page} von {pages}").format(page=2, pages=7) == texts[0]
        assert ImageViewer._pdf_link_tooltip(_Link(page=3)) == texts[1]


def test_pdf_external_link_tooltips_preserve_urls_and_mail_addresses():
    assert ImageViewer._pdf_link_tooltip(_Link("https://example.org/docs")) == "https://example.org/docs"
    assert ImageViewer._pdf_link_tooltip(_Link("mailto:person@example.org?subject=Hi")) == "person@example.org"


def test_pdf_unknown_scheme_stays_blocked_and_live_switch_updates_navigation(tmp_path):
    application = QApplication.instance() or QApplication([])
    viewer = ImageViewer(tmp_path)
    assert not viewer._open_pdf_link(_Link("javascript:alert(1)"))
    viewer._pdf_document = type("Document", (), {"pageCount": lambda self: 3})()
    viewer._pdf_page = 1
    viewer._set_language("en")
    assert viewer.pdf_page_label.text() == "Page 2 of 3"
    assert viewer.previous_pdf_page_button.toolTip() == "Previous PDF page"
    viewer._set_language("uk")
    assert viewer.pdf_page_label.text() == "Сторінка 2 з 3"
    assert viewer.previous_pdf_page_button.accessibleName() == "Попередня сторінка PDF"
    viewer.window.close()
    application.processEvents()


def test_pdf_render_error_frame_and_ukrainian_text_are_translated(tmp_path):
    manager = LanguageManager(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    manager.set_language("en")
    assert t("Die PDF-Seite konnte nicht gerendert werden") == "The PDF page could not be rendered"
    manager.set_language("uk")
    assert t("Die PDF-Seite konnte nicht gerendert werden") == "Не вдалося відтворити сторінку PDF"
    assert t("Die angegebene Datei hat kein unterstütztes Bild- oder PDF-Format:\n{path}").format(path="/tmp/test.xyz") == (
        "Указаний файл не має підтримуваного формату зображення або PDF:\n/tmp/test.xyz"
    )
