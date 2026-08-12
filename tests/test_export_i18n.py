from pathlib import Path

import i18n
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QGroupBox, QMessageBox

from bildbetrachter import ImageExportDialog
from i18n import t


def _dialog(tmp_path):
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    return ImageExportDialog([tmp_path / "photo.jpg"], {}, settings, tmp_path, None, lambda _path: None)


def test_export_dialog_visible_widgets_translate_in_all_languages(tmp_path):
    original = i18n._language
    try:
        for code in ("en", "fr", "es", "uk"):
            i18n._language = code
            dialog = _dialog(tmp_path)
            try:
                titles = {group.title() for group in dialog.findChildren(QGroupBox)}
                assert dialog.windowTitle() != "Bilder verkleinert exportieren"
                assert t("Zielgröße") in titles
                assert dialog.quality_label.text() != "JPEG-Qualität: 90 %"
                assert dialog.metadata_checkbox.text() != "Aufnahmedaten übernehmen"
                assert dialog.export_button.text() != "Exportieren"
                assert dialog.cancel_button.text() != "Abbrechen"
                assert "JPEG" in dialog.quality_label.text()
                if code == "uk":
                    assert any("Ц" in title or "р" in title for title in titles)
            finally:
                dialog.close()
    finally:
        i18n._language = original


def test_export_dynamic_progress_result_and_error_detail_are_translated(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    original = i18n._language
    captured = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: captured.append(box) or 0)
    try:
        i18n._language = "en"
        dialog = _dialog(tmp_path)
        dialog._export_progress(2, 3, "holiday.jpg")
        assert dialog.progress_label.text() == "Image 2 of 3: holiday.jpg"
        dialog._export_finished({"successful": ["holiday.jpg"], "skipped": [], "failures": ["holiday.jpg: OS detail"], "total_size": 12, "cancelled": False, "destination": str(tmp_path)})
        assert captured[-1].text() == "1 images were exported successfully."
        assert captured[-1].detailedText() == "Export error: holiday.jpg: OS detail"
    finally:
        i18n._language = original
        app.processEvents()
