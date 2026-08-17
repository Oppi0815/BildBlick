from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox

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
    manager.set_language("de", persist=False)


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
    manager.set_language("de", persist=False)


def test_image_index_reread_labels_and_tooltips_have_all_translations():
    keys = (
        "Neu einlesen", "Alle neu einlesen",
        "Liest diesen Ordner erneut ein und synchronisiert die Bildmetadaten im Index.",
        "Liest alle im Bildindex eingetragenen Ordner erneut ein.",
    )
    manager = LanguageManager(QSettings())
    for code in LANGUAGES:
        manager.set_language(code, persist=False)
        for key in keys:
            assert t(key)
            if code != "de":
                assert t(key) != key
    manager.set_language("de", persist=False)


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
    viewer._set_language("de")
    viewer.window.close(); app.processEvents()


def test_main_window_menus_and_comparison_dialog_translate_live(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("bildbetrachter.QSettings", lambda *_args: QSettings(str(tmp_path / "viewer.ini"), QSettings.Format.IniFormat))
    viewer = ImageViewer(tmp_path)
    try:
        for code, expected in (("en", "View"), ("fr", "Affichage"), ("es", "Ver"), ("uk", "Вигляд")):
            viewer._set_language(code)
            assert viewer.view_menu.title() == expected
            assert viewer.rotate_left_action.text() != "Nach links drehen"
            assert viewer.compare_images_action.text() != "Bilder vergleichen …"
    finally:
        viewer._set_language("de")
        viewer.window.close(); app.processEvents()


def test_slideshow_and_about_texts_translate_live(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("bildbetrachter.QSettings", lambda *_args: QSettings(str(tmp_path / "viewer.ini"), QSettings.Format.IniFormat))
    viewer = ImageViewer(tmp_path)
    try:
        for code in ("en", "fr", "es", "uk"):
            viewer._set_language(code)
            assert viewer.slideshow_menu.title() != "Diashow"
            assert viewer.slideshow_action.text() != "Diashow starten"
            assert viewer.about_action.text() != "Über BildBlick …"
    finally:
        viewer._set_language("de")
        viewer.window.close(); app.processEvents()


def test_help_text_and_about_description_translate_with_shortcuts(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("bildbetrachter.QSettings", lambda *_args: QSettings(str(tmp_path / "viewer.ini"), QSettings.Format.IniFormat))
    viewer = ImageViewer(tmp_path)
    shown_help, shown_about = [], []
    monkeypatch.setattr(QMessageBox, "exec", lambda dialog: shown_help.append(dialog.text()) or 0)
    monkeypatch.setattr(QDialog, "exec", lambda dialog: shown_about.append(dialog) or 0)
    try:
        for code in ("en", "fr", "es", "uk"):
            viewer._set_language(code)
            viewer._show_controls_help()
            assert "<b>" in shown_help[-1]
            assert "F11" in shown_help[-1] and "F5" in shown_help[-1] and "Escape" in shown_help[-1]
        viewer._set_language("en"); viewer._show_about()
        assert shown_about[-1].findChild(QLabel, "aboutDescriptionLabel").text() == "A fast and convenient image viewer"
        viewer._set_language("uk"); viewer._show_about()
        assert shown_about[-1].findChild(QLabel, "aboutDescriptionLabel").text() == "Швидкий і зручний переглядач зображень"
    finally:
        viewer._set_language("de")
        viewer.window.close(); app.processEvents()
