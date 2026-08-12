from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLabel

from bildbetrachter import ImageViewer, build_information_metadata
from i18n import LANGUAGE_KEY, LANGUAGES, LanguageManager, language_code
from i18n import t


def test_package_one_file_operation_texts_have_all_translations():
    keys = (
        "Bild umbenennen", "Datei bereits vorhanden", "Möchtest du die ausgewählten {count} Bilder in den Papierkorb verschieben?",
        "Technische Details: {detail}", "Ablage nicht möglich", "Drehung konnte nicht gespeichert werden",
    )
    expected = {"de": "Deutsch", "en": "English", "fr": "Français", "es": "Español", "uk": "Українська"}
    settings = QSettings()
    manager = LanguageManager(settings)
    for code in LANGUAGES:
        manager.set_language(code, persist=False)
        for key in keys:
            assert t(key)
            if code != "de":
                assert t(key) != key, (code, key)
        assert t("Möchtest du die ausgewählten {count} Bilder in den Papierkorb verschieben?").format(count=3)
        assert t("Technische Details: {detail}").format(detail="OS error")


def test_package_one_remaining_rotation_and_drop_texts_have_all_translations():
    keys = (
        "Für das Überschreiben der Originaldatei verwenden Sie bitte „Drehung im Original speichern …“.",
        "Die Originaldatei ist schreibgeschützt oder es fehlen Schreibrechte.",
        "Es wurden keine Dateien oder Ordner abgelegt.",
        "Bitte legen Sie entweder einen einzelnen Ordner oder Bilddateien ab.",
    )
    manager = LanguageManager(QSettings())
    for code in LANGUAGES:
        manager.set_language(code, persist=False)
        for key in keys:
            assert t(key)
            if code != "de":
                assert t(key) != key


def test_language_codes_fall_back_to_german():
    assert language_code("de") == "de"
    assert language_code("ua") == "de"
    assert language_code("invalid") == "de"


def test_language_manager_persists_each_supported_language(tmp_path):
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    manager = LanguageManager(settings)
    for code in LANGUAGES:
        manager.set_language(code)
        assert manager.code == code
        assert settings.value(LANGUAGE_KEY) == code
    restored = LanguageManager(settings)
    assert restored.code == "uk"


def test_widget_text_and_metadata_change_with_language(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    manager = LanguageManager(settings)
    label = QLabel("Bildinformationen")
    manager.set_language("uk")
    manager.translate_widget_tree(label)
    assert label.text() == "Інформація про зображення"
    manager.set_language("en")
    metadata = build_information_metadata(tmp_path / "missing.jpg")
    assert "IMAGE" in metadata
    assert metadata["IMAGE"]["File name"] == "missing.jpg"
    manager.set_language("de")
    label.deleteLater(); app.processEvents()


def test_viewer_has_exclusive_language_actions_and_live_switch(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("bildbetrachter.QSettings", lambda *_args: QSettings(str(tmp_path / "viewer.ini"), QSettings.Format.IniFormat))
    viewer = ImageViewer(tmp_path)
    assert set(viewer.language_actions) == set(LANGUAGES)
    viewer._set_language("fr")
    assert viewer.language_manager.code == "fr"
    assert viewer.language_menu.title() == "Langue"
    assert sum(action.isChecked() for action in viewer.language_actions.values()) == 1
    viewer.window.close(); app.processEvents()
