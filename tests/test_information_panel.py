from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QThread, QThreadPool, QTimer, Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QDialog, QFormLayout, QGroupBox, QLabel, QPushButton,
    QSizePolicy, QTreeWidget,
)

from bildbetrachter import (
    ImageViewer,
    ImageIndexTask,
    _metadata_value_present,
    _raw_metadata_text,
    build_all_image_metadata,
    build_information_metadata,
    read_manual_image_metadata,
    write_manual_image_metadata,
)


def _viewer(tmp_path: Path) -> tuple[QApplication, ImageViewer]:
    application = QApplication.instance() or QApplication([])
    viewer = ImageViewer(tmp_path)
    viewer.window.resize(900, 700)
    viewer.window.show()
    application.processEvents()
    return application, viewer


def _image(path: Path, *, exif: Image.Exif | None = None) -> Path:
    image = Image.new("RGB", (200, 100), "white")
    if exif is None:
        image.save(path)
    else:
        image.save(path, exif=exif)
    return path


def _panel_text(viewer: ImageViewer) -> str:
    return "\n".join(
        label.text() for label in viewer.information_panel.findChildren(QLabel)
    )


def test_information_panel_is_closed_by_default_and_button_toggles_it(tmp_path):
    application, viewer = _viewer(tmp_path)

    assert viewer.information_panel.isHidden()
    QTest.mouseClick(viewer.information_toggle_button, Qt.MouseButton.LeftButton)
    application.processEvents()
    assert viewer.information_panel.isVisible()
    QTest.mouseClick(viewer.information_toggle_button, Qt.MouseButton.LeftButton)
    application.processEvents()
    assert viewer.information_panel.isHidden()
    viewer.window.close()


def test_i_shortcut_and_escape_toggle_the_information_panel(tmp_path):
    application, viewer = _viewer(tmp_path)

    QTest.keyClick(viewer.window, Qt.Key.Key_I)
    application.processEvents()
    assert viewer.information_panel.isVisible()
    QTest.keyClick(viewer.window, Qt.Key.Key_Escape)
    application.processEvents()
    assert viewer.information_panel.isHidden()
    viewer.window.close()


def test_information_panel_uses_wrapping_values_and_keeps_close_button_working(tmp_path):
    nested = tmp_path / "a" / "very-long-folder-name-for-information-panel"
    nested.mkdir(parents=True)
    path = _image(nested / "long-file-name-for-the-information-panel.jpg")
    application, viewer = _viewer(tmp_path)
    try:
        viewer.current_image = path
        viewer._show_information_panel()
        application.processEvents()

        groups = viewer.information_content.findChildren(QGroupBox, "informationSection")
        assert groups
        assert all(not group.styleSheet() for group in groups)
        path_value = next(
            value
            for value in viewer.information_content.findChildren(QLabel, "informationValueLabel")
            if value.text() == str(path)
        )
        assert path_value.wordWrap()
        assert path_value.toolTip() == str(path)
        forms = [group.layout() for group in groups]
        assert all(isinstance(form, QFormLayout) for form in forms)
        assert all(
            form.rowWrapPolicy() == QFormLayout.RowWrapPolicy.WrapLongRows
            for form in forms
        )
        assert path_value.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
        labels = viewer.information_content.findChildren(
            QLabel, "informationFieldLabel"
        )
        assert labels and all(label.wordWrap() for label in labels)
        values = viewer.information_content.findChildren(
            QLabel, "informationValueLabel"
        )
        assert values
        assert all(
            label.isVisible() and label.width() > 0 and label.height() > 0
            and bool(label.text())
            for label in [*labels, *values]
        )
        assert viewer.information_scroll_area.horizontalScrollBarPolicy() == (
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        QTest.mouseClick(viewer.information_close_button, Qt.MouseButton.LeftButton)
        application.processEvents()
        assert viewer.information_panel.isHidden()
    finally:
        viewer.window.close()


def test_information_panel_shows_exif_and_updates_for_image_change(tmp_path):
    exif = Image.Exif()
    exif[271] = "BildBlick Camera"
    exif[272] = "Modell A"
    exif[36867] = "2026:08:12 10:11:12"
    exif[34855] = 200
    first = _image(tmp_path / "mit-exif.jpg", exif=exif)
    second = _image(tmp_path / "zweites-bild.jpg")
    application, viewer = _viewer(tmp_path)

    viewer.current_image = first
    viewer._show_information_panel()
    application.processEvents()
    assert "BildBlick Camera" in _panel_text(viewer)
    assert "ISO" in _panel_text(viewer)

    viewer.current_image = second
    viewer._update_information_panel()
    assert "zweites-bild.jpg" in _panel_text(viewer)
    assert "BildBlick Camera" not in _panel_text(viewer)
    viewer.window.close()


def test_image_without_exif_keeps_file_information_and_explains_absence(tmp_path):
    path = _image(tmp_path / "ohne-exif.jpg")

    metadata = build_information_metadata(path)

    assert metadata["BILD"]["Dateiname"] == "ohne-exif.jpg"
    assert metadata["WEITERE EXIF-DATEN"]["Hinweis"] == "Keine EXIF-Daten vorhanden"


def test_missing_exif_fields_are_omitted_without_error(tmp_path):
    exif = Image.Exif()
    exif[271] = "Nur Hersteller"
    path = _image(tmp_path / "teilweise-exif.jpg", exif=exif)

    metadata = build_information_metadata(path)

    assert metadata["KAMERA"] == {"Hersteller": "Nur Hersteller"}
    assert "AUFNAHME" not in metadata


def test_gps_section_is_only_added_when_coordinates_are_available(tmp_path):
    without_gps = _image(tmp_path / "ohne-gps.jpg")
    exif = Image.Exif()
    exif[34853] = {1: "N", 2: (48, 8, 0), 3: "E", 4: (11, 34, 0), 6: 512}
    with_gps = _image(tmp_path / "mit-gps.jpg", exif=exif)

    assert "GPS" not in build_information_metadata(without_gps)
    gps = build_information_metadata(with_gps)["GPS"]
    assert gps["Breitengrad"] == "48,133333"
    assert gps["Längengrad"] == "11,566667"
    assert gps["Höhe"] == "512 m"


def test_the_information_panel_handles_all_color_schemes(tmp_path):
    application, viewer = _viewer(tmp_path)

    for scheme in ("System", "Hell", "Dunkel"):
        viewer._color_scheme = scheme
        viewer._apply_color_scheme()
        viewer._show_information_panel()
        application.processEvents()
        assert viewer.information_panel.isVisible()
        viewer._hide_information_panel()
    viewer.window.close()


def test_pinned_manual_metadata_editor_is_editable_for_jpeg_and_not_scrolled(tmp_path):
    path = _image(tmp_path / "editor.jpg")
    application, viewer = _viewer(tmp_path)
    try:
        viewer.current_image = path
        viewer._show_information_panel()
        application.processEvents()

        assert list(viewer.manual_metadata_fields) == ["comment", "people", "place", "gps"]
        assert all(field.isEnabled() for field in viewer.manual_metadata_fields.values())
        assert not viewer.information_scroll_area.isAncestorOf(viewer.manual_metadata_section)
        assert viewer.information_panel.isAncestorOf(viewer.manual_metadata_section)

        viewer.manual_metadata_fields["comment"].setPlainText("Restaurierung")
        viewer.manual_metadata_fields["people"].setText("Ingeborg, Horst")
        assert viewer.collect_manual_metadata_from_fields() == {
            "comment": "Restaurierung", "people": "Ingeborg, Horst", "place": "", "gps": ""
        }
        viewer.manual_metadata_save_button.click()
        assert viewer.manual_metadata == viewer.collect_manual_metadata_from_fields()
    finally:
        viewer.window.close()


def test_manual_metadata_has_one_heading_and_uniform_theme_fields(tmp_path):
    path = _image(tmp_path / "theme.jpg")
    application, viewer = _viewer(tmp_path)
    try:
        viewer.current_image = path; viewer._show_information_panel(); application.processEvents()
        headings = [label for label in viewer.information_panel.findChildren(QLabel) if label.text() == "Bildinformationen"]
        assert len(headings) == 1
        for scheme, expected in (("System", "#ffffff"), ("Hell", "#ffffff"), ("Dunkel", "#343a42")):
            viewer._color_scheme = scheme; viewer._apply_color_scheme(); application.processEvents()
            colors = {field.palette().color(QPalette.ColorRole.Base).name() for field in viewer.manual_metadata_fields.values()}
            assert colors == {expected}
            assert all(field.isEnabled() and not field.isReadOnly() for field in viewer.manual_metadata_fields.values())
    finally:
        viewer.window.close()


def test_image_index_manager_is_reachable_and_empty_state_disables_folder_actions(tmp_path, monkeypatch):
    application, viewer = _viewer(tmp_path)
    monkeypatch.setattr("bildbetrachter.indexed_folders", lambda: [])
    observed = {}
    def inspect_dialog():
        dialog = next(widget for widget in application.topLevelWidgets() if isinstance(widget, QDialog) and widget.objectName() == "imageIndexManagerDialog")
        tree = dialog.findChild(QTreeWidget, "indexedFoldersTree")
        observed["empty"] = tree.topLevelItem(0).text(0)
        observed["update"] = dialog.findChild(QPushButton, "updateIndexedFolderButton").isEnabled()
        observed["update_all"] = dialog.findChild(QPushButton, "updateAllIndexedFoldersButton").isEnabled()
        observed["remove"] = dialog.findChild(QPushButton, "removeIndexedFolderButton").isEnabled()
        dialog.accept()
    QTimer.singleShot(0, inspect_dialog)
    viewer.manage_image_index_action.trigger()
    assert viewer.manage_image_index_action in viewer.tools_menu.actions()
    assert observed == {"empty":"Noch keine Ordner im Bildindex.", "update":False, "update_all":False, "remove":False}
    viewer.window.close()


def test_pinned_manual_metadata_fields_accept_real_mouse_and_keyboard_input(tmp_path):
    path = _image(tmp_path / "interactive.JPG")
    application, viewer = _viewer(tmp_path)
    try:
        viewer.current_image = path
        viewer._show_information_panel()
        application.processEvents()
        values = {
            "comment": "BildBlick Test", "people": "Horst, Ingeborg",
            "place": "Steyerberg", "gps": "52.000000, 9.000000",
        }
        for key, expected in values.items():
            field = viewer.manual_metadata_fields[key]
            target = field.viewport() if hasattr(field, "viewport") else field
            assert field.isEnabled() and not field.isReadOnly()
            assert not field.visibleRegion().isEmpty()
            QTest.mouseClick(target, Qt.MouseButton.LeftButton)
            assert field.hasFocus() or target.hasFocus()
            QTest.keyClicks(target, expected)
        application.processEvents()
        assert viewer.collect_manual_metadata_from_fields() == values
    finally:
        viewer.window.close()


def test_pinned_manual_metadata_editor_resets_on_file_change_and_disables_for_pdf(tmp_path):
    first = _image(tmp_path / "first.jpg")
    second = _image(tmp_path / "second.jpg")
    pdf_path = tmp_path / "document.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    application, viewer = _viewer(tmp_path)
    try:
        viewer.current_image = first
        viewer._show_information_panel()
        viewer.manual_metadata_fields["place"].setText("Steyerberg")
        viewer.current_image = second
        viewer._update_information_panel()
        assert viewer.manual_metadata_fields["place"].text() == ""

        viewer.current_image = pdf_path
        viewer._update_information_panel()
        assert all(not field.isEnabled() for field in viewer.manual_metadata_fields.values())
    finally:
        viewer.window.close()


def test_pinned_manual_metadata_editor_retranslates_live(tmp_path):
    path = _image(tmp_path / "editor.jpg")
    application, viewer = _viewer(tmp_path)
    try:
        viewer.current_image = path
        viewer._show_information_panel()
        for language, expected in (("en", "Notes"), ("fr", "Remarques"), ("es", "Notas"), ("uk", "Примітки"), ("de", "Bemerkungen")):
            viewer._set_language(language)
            application.processEvents()
            assert viewer.manual_metadata_labels["comment"].text() == expected
    finally:
        viewer.window.close()


def test_image_index_worker_runs_outside_gui_thread_and_reports_progress(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    worker_threads = []
    def fake_index(folder, recursive, reader, path=None, progress=None, cancelled=None):
        worker_threads.append(QThread.currentThread())
        progress(1, 2); progress(2, 2)
        return 2
    monkeypatch.setattr("bildbetrachter.index_folder", fake_index)
    task = ImageIndexTask([(tmp_path, False)])
    progress_values, finished_values = [], []
    task.signals.progress.connect(lambda current, total: progress_values.append((current, total)), Qt.ConnectionType.DirectConnection)
    task.signals.finished.connect(lambda count, cancelled: finished_values.append((count, cancelled)), Qt.ConnectionType.DirectConnection)
    pool = QThreadPool.globalInstance(); pool.start(task)
    assert pool.waitForDone(3000)
    assert worker_threads and worker_threads[0] is not application.thread()
    assert progress_values == [(1, 2), (2, 2)]
    assert finished_values == [(2, False)]


def test_manual_jpeg_metadata_round_trip_preserves_image_and_existing_exif(tmp_path):
    exif = Image.Exif()
    exif[271] = "Existing camera"
    path = _image(tmp_path / "metadata with spaces.jpg", exif=exif)
    size_before = Image.open(path).size

    write_manual_image_metadata(path, {
        "comment": "Restaurierung", "people": "Ingeborg, Horst, Ingeborg",
        "place": "Steyerberg", "gps": "52.123456, 9.123456",
    })

    assert read_manual_image_metadata(path) == {
        "comment": "Restaurierung", "people": "Ingeborg, Horst",
        "place": "Steyerberg", "gps": "52.123456, 9.123456",
    }
    assert Image.open(path).getexif()[271] == "Existing camera"
    assert Image.open(path).size == size_before


def test_manual_jpeg_metadata_removes_empty_values_and_rejects_invalid_gps(tmp_path):
    path = _image(tmp_path / "metadata.jpg")
    write_manual_image_metadata(path, {
        "comment": "Text", "people": "Horst", "place": "Ort", "gps": "52, 9",
    })
    write_manual_image_metadata(path, {"comment": "", "people": "", "place": "", "gps": ""})
    assert read_manual_image_metadata(path) == {"comment": "", "people": "", "place": "", "gps": ""}
    with pytest.raises(ValueError):
        write_manual_image_metadata(path, {"comment": "", "people": "", "place": "", "gps": "91, 9"})


def test_successful_metadata_save_updates_index_and_index_failure_does_not_undo_save(tmp_path, monkeypatch):
    path = _image(tmp_path / "indexed.jpg")
    application, viewer = _viewer(tmp_path)
    saved_calls, index_calls = [], []
    metadata = {"comment":"Neu", "people":"Ingeborg", "place":"Steyerberg", "gps":"52, 9"}
    monkeypatch.setattr("bildbetrachter.write_manual_image_metadata", lambda file_path, values: saved_calls.append((file_path, values)))
    monkeypatch.setattr("bildbetrachter.read_manual_image_metadata", lambda file_path: metadata)
    monkeypatch.setattr("bildbetrachter.upsert_person", lambda *args: None)
    monkeypatch.setattr("bildbetrachter.upsert_place", lambda *args: None)
    monkeypatch.setattr("bildbetrachter.update_indexed_image", lambda file_path, values: index_calls.append((file_path, values)) or True)
    try:
        viewer.current_image = path; viewer._show_information_panel()
        viewer.load_manual_metadata_into_fields(metadata); viewer.manual_metadata_dirty = True
        viewer._capture_manual_metadata()
        assert saved_calls and index_calls == [(path, metadata)]
        assert not viewer.manual_metadata_dirty
        monkeypatch.setattr("bildbetrachter.update_indexed_image", lambda *args: (_ for _ in ()).throw(OSError("DB defekt")))
        viewer.manual_metadata_dirty = True; viewer._capture_manual_metadata()
        assert len(saved_calls) == 2 and not viewer.manual_metadata_dirty
    finally:
        viewer.window.close()


def test_pdf_information_is_file_only_and_does_not_read_exif(tmp_path):
    pdf_path = tmp_path / "dokument.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    metadata = build_information_metadata(pdf_path)

    assert metadata == {
        "BILD": {
            "Dateiname": "dokument.pdf",
            "Dateipfad": str(pdf_path),
            "Dateigröße": "9 B",
            "Dateiformat": "PDF",
        }
    }


def test_image_navigation_controls_remain_available(tmp_path):
    application, viewer = _viewer(tmp_path)

    assert viewer.bottom_control_bar.isAncestorOf(viewer.previous_button)
    assert viewer.bottom_control_bar.isAncestorOf(viewer.next_button)
    assert viewer.previous_image_action is not None
    assert viewer.next_image_action is not None
    viewer.window.close()


def test_all_metadata_is_closed_by_default_and_lazy_loaded(tmp_path, monkeypatch):
    path = _image(tmp_path / "raw.jpg")
    application, viewer = _viewer(tmp_path)
    viewer.current_image = path
    viewer._show_information_panel()
    assert not viewer.all_metadata_toggle.isChecked()
    called = []
    original = build_all_image_metadata
    monkeypatch.setattr("bildbetrachter.build_all_image_metadata", lambda current: called.append(current) or original(current))
    viewer.all_metadata_toggle.click()
    application.processEvents()
    assert called == [path]
    assert viewer.all_metadata_content.isVisible()
    viewer.all_metadata_toggle.click()
    assert viewer.all_metadata_content.isHidden()
    viewer.window.close()


def test_all_metadata_has_exif_gps_and_safe_makernote(tmp_path):
    exif = Image.Exif()
    exif[33434] = (1, 125)
    exif[37500] = b"x" * 20_000
    exif[34853] = {1: "N", 2: (48, 8, 0), 3: "E", 4: (11, 34, 0)}
    path = _image(tmp_path / "raw-gps.jpg", exif=exif)

    metadata = build_all_image_metadata(path)

    assert "EXIF" in metadata and "ExposureTime" in metadata["EXIF"]
    assert "GPS" in metadata and "GPSLatitude" in metadata["GPS"]
    assert metadata["EXIF"]["MakerNote"] == "vorhanden (nicht dekodiert)"


def test_all_metadata_handles_pdf_and_long_values(tmp_path):
    pdf_path = tmp_path / "metadata.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    exif = Image.Exif()
    exif[315] = "A" * 2_000
    image_path = _image(tmp_path / "long.jpg", exif=exif)

    assert build_all_image_metadata(pdf_path) == {}
    assert len(build_all_image_metadata(image_path)["EXIF"]["Artist"]) <= 500


def test_raw_metadata_omits_only_empty_values_and_preserves_zero_and_false():
    for value in (None, "", " \t ", [], (), {}, b""):
        assert not _metadata_value_present(value)
        assert _raw_metadata_text(value) is None
    for value in (0, False):
        assert _metadata_value_present(value)
        assert _raw_metadata_text(value) == str(value)


def test_all_metadata_keeps_unknown_present_exif_tags(tmp_path):
    exif = Image.Exif()
    exif[65000] = 0
    path = _image(tmp_path / "unknown-tag.jpg", exif=exif)

    metadata = build_all_image_metadata(path)

    assert metadata["EXIF"]["Unbekanntes Tag 0xFDE8"] == "0"


def test_raw_metadata_filters_nested_and_placeholder_values_but_keeps_zero_false():
    empty_values = (
        None, "", "  ", [], (), set(), {}, b"", bytearray(),
        [None, " ", []], {"empty": ["", None]}, "None", "null",
        "N/A", "not available", "(,; /)",
    )
    for value in empty_values:
        assert _raw_metadata_text(value) is None
    assert _raw_metadata_text(0) == "0"
    assert _raw_metadata_text(0.0) == "0.0"
    assert _raw_metadata_text(False) == "False"


def test_xmp_is_never_shown_in_any_metadata_group(tmp_path, monkeypatch):
    xmp = '''<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="rdf" xmlns:t="test">
      <rdf:RDF><rdf:Description t:none="None" t:blank=" " t:zero="0" t:false="False">
        <t:empty><rdf:Bag>  </rdf:Bag></t:empty><t:title>Ein echter Wert</t:title>
      </rdf:Description></rdf:RDF></x:xmpmeta>'''

    class FakeImage:
        info = {"xmp": xmp, "XML:com.adobe.xmp": xmp, "comment": "sichtbar"}
        def getexif(self):
            return Image.Exif()
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("bildbetrachter.PillowImage.open", lambda _path: FakeImage())
    metadata = build_all_image_metadata(tmp_path / "fake.jpg")

    assert "XMP" not in metadata
    assert metadata["Datei / Sonstige"] == {"comment": "sichtbar"}
