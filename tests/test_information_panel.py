from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QEvent, QItemSelectionModel, QPoint, QThread, QThreadPool, QTimer, Qt
from PySide6.QtGui import QImage, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QDialog, QFormLayout, QGroupBox, QLabel, QPushButton,
    QHeaderView, QListWidgetItem, QMessageBox, QSizePolicy, QTabWidget, QTreeWidget,
)

from bildbetrachter import (
    COLOR_SCHEMES,
    ImageViewer,
    ImageIndexTask,
    ImageMetadataRefreshTask,
    BatchMetadataTask,
    MetadataBulkEditTask,
    _metadata_value_present,
    _raw_metadata_text,
    build_all_image_metadata,
    build_information_metadata,
    read_manual_image_metadata,
    write_manual_image_metadata,
)


def _add_selected_thumbnail(viewer: ImageViewer, path: Path, *, current=False) -> None:
    item = QListWidgetItem(path.name)
    item.setData(Qt.ItemDataRole.UserRole, path)
    viewer.thumbnail_list.addItem(item)
    item.setSelected(True)
    if current:
        viewer.thumbnail_list.setCurrentItem(item)


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


def test_fullscreen_information_panel_uses_white_text_and_restores_theme_style(tmp_path):
    application, viewer = _viewer(tmp_path)
    original_style = viewer.information_panel.styleSheet()
    original_file_style = viewer.file_name_label.styleSheet()
    original_tooltip = viewer.information_toggle_button.toolTip()
    original_thumbnail_value = viewer.thumbnail_size_slider.value()
    try:
        viewer.original_image = QImage(200, 100, QImage.Format.Format_RGB32)
        viewer._show_information_panel()
        for scheme in ("System", *COLOR_SCHEMES):
            viewer._color_scheme = scheme; viewer._apply_color_scheme()
            viewer._enter_fullscreen(); application.processEvents()
            style = viewer.information_panel.styleSheet()
            assert "background-color: #000000" in style
            assert "color: #ffffff" in style
            assert "QGroupBox#informationSection" in style
            assert "QLineEdit" in style and "color: #1f1f1f" in style
            assert "color: #ffffff" in viewer.file_name_label.styleSheet()
            assert viewer.information_toggle_button.toolTip() == ""
            assert viewer.thumbnail_size_controls.isHidden()
            assert viewer.thumbnail_size_slider.value() == original_thumbnail_value
            viewer._leave_fullscreen(); application.processEvents()
            assert viewer.information_panel.styleSheet() == original_style
            assert viewer.file_name_label.styleSheet() == original_file_style
            assert viewer.information_toggle_button.toolTip() == original_tooltip
            assert not viewer.thumbnail_size_controls.isHidden()
            assert viewer.thumbnail_size_slider.value() == original_thumbnail_value
    finally:
        if viewer._fullscreen_mode: viewer._leave_fullscreen()
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
        assert all(
            button.text() != "Zurücksetzen"
            for button in viewer.manual_metadata_section.findChildren(QPushButton)
        )

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


def test_saving_place_with_image_gps_enriches_place_database(tmp_path, monkeypatch):
    path = _image(tmp_path / "place-gps.jpg")
    recorded = []
    metadata = {"comment": "", "people": "", "place": "Steyerberg", "gps": "52.123456, 9.654321"}
    monkeypatch.setattr("bildbetrachter.write_manual_image_metadata", lambda *_: None)
    monkeypatch.setattr("bildbetrachter.read_manual_image_metadata", lambda _: dict(metadata))
    monkeypatch.setattr("bildbetrachter.place_coordinates", lambda _: None)
    monkeypatch.setattr("bildbetrachter.upsert_place", lambda *args: recorded.append(args))
    monkeypatch.setattr("bildbetrachter.update_indexed_image", lambda *_: True)
    application, viewer = _viewer(tmp_path)
    try:
        viewer.current_image = path
        viewer._show_information_panel()
        viewer.load_manual_metadata_into_fields(metadata)
        viewer._capture_manual_metadata()
        assert recorded == [("Steyerberg", 52.123456, 9.654321)]
    finally:
        viewer.window.close()


def test_gps_focus_shows_fresh_local_place_suggestion_without_writing(tmp_path, monkeypatch):
    path = _image(tmp_path / "focus-gps.jpg")
    coordinates = {"Steyerberg": (52.123456, 9.654321), "Nienburg": (52.765432, 9.123456)}
    monkeypatch.setattr("bildbetrachter.place_coordinates", lambda name: coordinates.get(name))
    application, viewer = _viewer(tmp_path)
    try:
        viewer.current_image = path
        viewer._show_information_panel()
        viewer.load_manual_metadata_into_fields({"place": "Steyerberg"})
        gps = viewer.manual_metadata_fields["gps"]
        viewer.eventFilter(gps, QEvent(QEvent.Type.FocusIn))
        assert viewer.place_gps_suggestion.isVisible()
        assert "52.123456, 9.654321" in viewer.place_gps_suggestion_label.text()
        assert gps.text() == ""
        viewer.eventFilter(gps, QEvent(QEvent.Type.FocusOut))
        viewer.eventFilter(gps, QEvent(QEvent.Type.FocusIn))
        assert viewer.place_gps_suggestion.isVisible()
        viewer.manual_metadata_fields["place"].setText("Nienburg")
        viewer.eventFilter(gps, QEvent(QEvent.Type.FocusIn))
        assert "52.765432, 9.123456" in viewer.place_gps_suggestion_label.text()
        viewer._batch_metadata_mode = True
        viewer.eventFilter(gps, QEvent(QEvent.Type.FocusOut))
        assert viewer.place_gps_suggestion.isVisible()
        viewer.place_gps_suggestion_apply_button.click()
        assert gps.text() == "52.765432, 9.123456"
        assert viewer.batch_touched["gps"]
        assert viewer.manual_metadata_dirty
    finally:
        viewer.window.close()


def test_mixed_batch_gps_stays_editable_and_can_accept_place_suggestion(tmp_path, monkeypatch):
    paths = [_image(tmp_path / f"mixed-gps-{index}.jpg") for index in range(3)]
    values = {
        paths[0]: {"comment": "", "people": "", "place": "Steyerberg", "gps": ""},
        paths[1]: {"comment": "", "people": "", "place": "Steyerberg", "gps": "52.1, 9.1"},
        paths[2]: {"comment": "", "people": "", "place": "Steyerberg", "gps": "52.2, 9.2"},
    }
    monkeypatch.setattr("bildbetrachter.read_manual_image_metadata", lambda path: dict(values[path]))
    monkeypatch.setattr("bildbetrachter.place_coordinates", lambda _: (52.123456, 9.654321))
    application, viewer = _viewer(tmp_path)
    try:
        for index, path in enumerate(paths):
            _add_selected_thumbnail(viewer, path, current=index == 0)
        viewer._show_information_panel()
        application.processEvents()
        gps = viewer.manual_metadata_fields["gps"]
        assert gps.text() == ""
        assert gps.placeholderText() == "Verschiedene Werte"
        assert gps.isEnabled() and not gps.isReadOnly()
        assert gps.focusPolicy() == Qt.FocusPolicy.StrongFocus
        QTimer.singleShot(
            0,
            lambda: next(
                dialog for dialog in application.topLevelWidgets()
                if isinstance(dialog, QDialog) and dialog.objectName() == "gpsCandidateDialog"
            ).accept(),
        )
        viewer.eventFilter(gps, QEvent(QEvent.Type.FocusIn))
        assert gps.text() == "52.123456, 9.654321"
        assert viewer.batch_touched["gps"] and viewer.manual_metadata_dirty
        assert viewer._batch_changes()["gps"] == "52.123456, 9.654321"
    finally:
        viewer.window.close()


def test_gps_map_uses_deduplicated_batch_coordinates(tmp_path, monkeypatch):
    paths = [_image(tmp_path / f"map-{index}.jpg") for index in range(3)]
    values = {
        paths[0]: {"comment": "", "people": "", "place": "", "gps": "52.1, 9.1"},
        paths[1]: {"comment": "", "people": "", "place": "", "gps": "52.1, 9.1"},
        paths[2]: {"comment": "", "people": "", "place": "", "gps": "52.2, 9.2"},
    }
    monkeypatch.setattr("bildbetrachter.read_manual_image_metadata", lambda path: dict(values[path]))
    application, viewer = _viewer(tmp_path)
    try:
        for index, path in enumerate(paths):
            _add_selected_thumbnail(viewer, path, current=index == 0)
        viewer._show_information_panel()
        application.processEvents()
        assert viewer.show_map_button.isEnabled()
        assert sorted(viewer._gps_map_positions()) == [(52.1, 9.1, 2), (52.2, 9.2, 1)]
    finally:
        viewer.window.close()


def test_manual_metadata_layout_matches_warm_in_every_color_scheme(tmp_path):
    """Themes may recolor the editor, but must not move or resize it."""
    path = _image(tmp_path / "theme-layout.jpg")
    application, viewer = _viewer(tmp_path)
    try:
        viewer.current_image = path
        viewer._show_information_panel()
        application.processEvents()

        def geometry() -> dict[str, object]:
            fields = viewer.manual_metadata_fields
            labels = viewer.manual_metadata_labels
            return {
                "heading_count": sum(
                    label.text() == "Bildinformationen"
                    for label in viewer.information_panel.findChildren(QLabel)
                ),
                "comment_label": labels["comment"].geometry(),
                "comment_field": fields["comment"].geometry(),
                "row_labels": tuple(labels[key].geometry() for key in ("people", "place", "gps")),
                "row_fields": tuple(fields[key].geometry() for key in ("people", "place", "gps")),
                "save_button": viewer.manual_metadata_save_button.geometry(),
                "section": viewer.manual_metadata_section.geometry(),
                "separator": viewer.manual_metadata_separator.geometry(),
            }

        viewer._color_scheme = "Warm"
        viewer._apply_color_scheme()
        application.processEvents()
        warm = geometry()
        assert warm["heading_count"] == 1
        row_fields = warm["row_fields"]
        assert len({rect.x() for rect in row_fields}) == 1
        assert len({rect.right() for rect in row_fields}) == 1
        assert len({rect.height() for rect in row_fields}) == 1
        assert warm["comment_field"].left() == 0
        assert warm["comment_field"].right() == row_fields[0].right()

        for scheme in COLOR_SCHEMES:
            viewer._color_scheme = scheme
            viewer._apply_color_scheme()
            application.processEvents()
            assert geometry() == warm, scheme
    finally:
        viewer.window.close()


def test_main_window_controls_remain_visible_in_every_color_scheme(tmp_path):
    application, viewer = _viewer(tmp_path)
    try:
        assert viewer.status_bar.isVisible()
        assert viewer.bottom_control_bar.isVisible()
        assert viewer.status_bar.parentWidget() is viewer.window
        assert viewer.bottom_control_bar.parentWidget() is viewer.status_bar
        assert viewer.window.menuBar().cornerWidget(Qt.Corner.TopRightCorner) is (
            viewer.thumbnail_quick_toggle.parentWidget()
        )

        for scheme in ("System", *COLOR_SCHEMES):
            viewer._color_scheme = scheme
            viewer._apply_color_scheme()
            application.processEvents()
            assert viewer.status_bar.isVisible()
            assert viewer.bottom_control_bar.isVisible()
            assert all(
                button.isVisible() and button.parentWidget().isVisible()
                for button in (
                    viewer.thumbnail_quick_toggle,
                    viewer.details_quick_toggle,
                    viewer.fullscreen_quick_toggle,
                )
            )

        viewer._hide_bottom_control_bar()
        application.processEvents()
        assert viewer.status_bar.isHidden()
        viewer._show_bottom_control_bar()
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


def test_image_index_manager_loads_current_folder_entries_each_time_it_opens(tmp_path, monkeypatch):
    application, viewer = _viewer(tmp_path)
    first, second = tmp_path / "with-images", tmp_path / "empty"
    entries = [(first, True, "scan-a"), (second, False, "scan-b")]
    monkeypatch.setattr("bildbetrachter.indexed_folders", lambda: entries)
    observed = []

    def inspect_dialog():
        dialog = next(widget for widget in application.topLevelWidgets() if isinstance(widget, QDialog) and widget.objectName() == "imageIndexManagerDialog" and widget.isVisible())
        try:
            tree = dialog.findChild(QTreeWidget, "indexedFoldersTree")
            observed.extend((tree.topLevelItem(index).text(0), tree.topLevelItem(index).text(1)) for index in range(tree.topLevelItemCount()))
        finally:
            dialog.accept()

    QTimer.singleShot(0, inspect_dialog)
    viewer.manage_image_index_action.trigger()
    assert observed == [(str(first), "Ja"), (str(second), "Nein")]
    viewer.window.close()


def test_image_index_manager_uses_reread_labels_tooltips_layout_and_shared_refresh(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ImageViewer, "_start_index_metadata_refresh", lambda self, folders=None: calls.append(folders))
    application, viewer = _viewer(tmp_path)
    first = tmp_path / "a very long indexed folder name" / "with another level"
    second = tmp_path / "short"
    entries = [(first, True, "2026-08-17T10:20:30+00:00"), (second, False, "")]
    monkeypatch.setattr("bildbetrachter.indexed_folders", lambda: entries)
    observed = {}

    def inspect_dialog():
        dialog = next(widget for widget in application.topLevelWidgets() if isinstance(widget, QDialog) and widget.objectName() == "imageIndexManagerDialog" and widget.isVisible())
        try:
            tree = dialog.findChild(QTreeWidget, "indexedFoldersTree")
            update = dialog.findChild(QPushButton, "updateIndexedFolderButton")
            update_all = dialog.findChild(QPushButton, "updateAllIndexedFoldersButton")
            observed["texts"] = (update.text(), update_all.text())
            observed["tooltips"] = (update.toolTip(), update_all.toolTip())
            header = tree.header()
            observed["modes"] = tuple(header.sectionResizeMode(index) for index in range(3))
            observed["widths"] = tuple(tree.columnWidth(index) for index in range(3))
            update.click(); update_all.click()
        finally:
            dialog.accept()

    viewer.refresh_index_metadata_action.trigger()
    QTimer.singleShot(0, inspect_dialog)
    viewer.manage_image_index_action.trigger()
    assert calls == [None, [(first, True)], None]
    assert observed["texts"] == ("Neu einlesen", "Alle neu einlesen")
    assert observed["tooltips"] == (
        "Liest diesen Ordner erneut ein und synchronisiert die Bildmetadaten im Index.",
        "Liest alle im Bildindex eingetragenen Ordner erneut ein.",
    )
    assert observed["modes"] == (
        QHeaderView.ResizeMode.Stretch,
        QHeaderView.ResizeMode.ResizeToContents,
        QHeaderView.ResizeMode.ResizeToContents,
    )
    assert observed["widths"][0] > observed["widths"][1] and observed["widths"][0] > observed["widths"][2]
    viewer.window.close()


def test_metadata_database_manager_is_reachable_and_lists_people_places(tmp_path, monkeypatch):
    application, viewer = _viewer(tmp_path)
    entries = {
        "people": [{"id":1,"name":"Ingeborg","use_count":3,"last_used_at":"2026-01-01","hidden":0,"indexed_count":2,"latitude":None,"longitude":None}],
        "places": [{"id":2,"name":"Steyerberg","use_count":4,"last_used_at":"2026-01-02","hidden":0,"indexed_count":2,"latitude":52.0,"longitude":9.0}],
    }
    monkeypatch.setattr("bildbetrachter.metadata_entries", lambda kind: entries[kind])
    observed = {}
    def inspect_dialog():
        dialog = next(widget for widget in application.topLevelWidgets() if isinstance(widget, QDialog) and widget.objectName() == "metadataDatabaseManagerDialog" and widget.isVisible())
        people = dialog.findChild(QTreeWidget, "peopleMetadataTree")
        places = dialog.findChild(QTreeWidget, "placesMetadataTree")
        observed["people"] = people.topLevelItem(0).text(0)
        observed["place"] = places.topLevelItem(0).text(0)
        observed["usage"] = (people.topLevelItem(0).text(1), places.topLevelItem(0).text(1))
        observed["sorting"] = people.header().isSortIndicatorShown() and places.header().isSortIndicatorShown()
        observed["people_headers"] = tuple(people.headerItem().text(index) for index in range(people.columnCount()))
        observed["places_headers"] = tuple(places.headerItem().text(index) for index in range(places.columnCount()))
        observed["resize_modes"] = tuple(people.header().sectionResizeMode(index) for index in range(people.columnCount()))
        observed["path"] = dialog.findChild(QLabel, "metadataDatabasePathLabel").text()
        dialog.accept()
    QTimer.singleShot(0, inspect_dialog)
    viewer.manage_metadata_database_action.trigger()
    assert viewer.manage_metadata_database_action in viewer.tools_menu.actions()
    assert observed["people"] == "Ingeborg" and observed["place"] == "Steyerberg"
    assert observed["usage"] == ("2", "2") and observed["sorting"] and "metadata.db" in observed["path"]
    assert observed["people_headers"] == ("Name", "Bilder", "Zuletzt verwendet")
    assert "Eingaben" not in observed["people_headers"] + observed["places_headers"]
    assert observed["resize_modes"] == (
        QHeaderView.ResizeMode.Stretch,
        QHeaderView.ResizeMode.ResizeToContents,
        QHeaderView.ResizeMode.ResizeToContents,
    )
    viewer.window.close()


@pytest.mark.parametrize("kind", ("people", "places"))
def test_metadata_database_manager_sorts_image_counts_as_integers(tmp_path, monkeypatch, kind):
    application, viewer = _viewer(tmp_path)
    counts = (1, 14, 15, 18, 2, 20, 22, 26, 29, 3, 5, 0, 100)
    entries = {
        "people": [
            {"id": index, "name": f"Person {count:03}", "use_count": 1, "last_used_at": "2026-01-01", "hidden": 0, "indexed_count": count, "latitude": None, "longitude": None}
            for index, count in enumerate(counts)
        ],
        "places": [
            {"id": index, "name": f"Ort {count:03}", "use_count": 1, "last_used_at": "2026-01-01", "hidden": 0, "indexed_count": count, "latitude": 52.0, "longitude": 9.0}
            for index, count in enumerate(counts)
        ],
    }
    monkeypatch.setattr("bildbetrachter.metadata_entries", lambda entry_kind: entries[entry_kind])
    observed = {}

    def click_header(tree, column):
        header = tree.header()
        QTest.mouseClick(
            header.viewport(), Qt.MouseButton.LeftButton,
            pos=QPoint(header.sectionPosition(column) + header.sectionSize(column) // 2, header.height() // 2),
        )
        application.processEvents()

    def inspect_dialog():
        dialog = next(widget for widget in application.topLevelWidgets() if isinstance(widget, QDialog) and widget.objectName() == "metadataDatabaseManagerDialog" and widget.isVisible())
        try:
            dialog.findChild(QTabWidget, "metadataDatabaseTabs").setCurrentIndex(0 if kind == "people" else 1)
            tree = dialog.findChild(QTreeWidget, f"{kind}MetadataTree")
            click_header(tree, 1)
            observed["ascending"] = [int(tree.topLevelItem(index).text(1)) for index in range(tree.topLevelItemCount())]
            click_header(tree, 1)
            observed["descending"] = [int(tree.topLevelItem(index).text(1)) for index in range(tree.topLevelItemCount())]
            click_header(tree, 0)
            observed["names"] = [tree.topLevelItem(index).text(0) for index in range(tree.topLevelItemCount())]
        finally:
            dialog.accept()

    QTimer.singleShot(0, inspect_dialog)
    viewer.manage_metadata_database_action.trigger()
    assert observed["ascending"] == sorted(counts)
    assert observed["descending"] == sorted(counts, reverse=True)
    assert observed["names"] == sorted(observed["names"])
    viewer.window.close()


def test_people_metadata_last_used_sorts_chronologically_and_survives_tab_switch(tmp_path, monkeypatch):
    application, viewer = _viewer(tmp_path)
    entries = {
        "people": [
            {"id": 1, "name": "Horst", "use_count": 1, "last_used_at": "2026-08-17T12:00:00+00:00", "hidden": 0, "indexed_count": 2, "latitude": None, "longitude": None},
            {"id": 2, "name": "Anette", "use_count": 1, "last_used_at": "2025-01-02T12:00:00+00:00", "hidden": 0, "indexed_count": 1, "latitude": None, "longitude": None},
            {"id": 3, "name": "Debbie", "use_count": 1, "last_used_at": "2026-01-01T12:00:00+00:00", "hidden": 0, "indexed_count": 3, "latitude": None, "longitude": None},
        ],
        "places": [],
    }
    monkeypatch.setattr("bildbetrachter.metadata_entries", lambda kind: entries[kind])
    observed = {}

    def click_header(tree, column):
        header = tree.header()
        QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(header.sectionPosition(column) + header.sectionSize(column) // 2, header.height() // 2))
        application.processEvents()

    def inspect_dialog():
        dialog = next(widget for widget in application.topLevelWidgets() if isinstance(widget, QDialog) and widget.objectName() == "metadataDatabaseManagerDialog" and widget.isVisible())
        try:
            tabs = dialog.findChild(QTabWidget, "metadataDatabaseTabs")
            people = dialog.findChild(QTreeWidget, "peopleMetadataTree")
            click_header(people, 2)
            observed["ascending"] = [people.topLevelItem(index).text(2) for index in range(people.topLevelItemCount())]
            tabs.setCurrentIndex(1); tabs.setCurrentIndex(0)
            click_header(people, 2)
            observed["descending"] = [people.topLevelItem(index).text(2) for index in range(people.topLevelItemCount())]
            observed["indicator"] = people.header().isSortIndicatorShown()
        finally:
            dialog.accept()

    QTimer.singleShot(0, inspect_dialog)
    viewer.manage_metadata_database_action.trigger()
    assert observed["ascending"] == sorted(observed["ascending"])
    assert observed["descending"] == sorted(observed["descending"], reverse=True)
    assert observed["indicator"]
    viewer.window.close()


@pytest.mark.parametrize(("kind", "button_name"), (("people", "showPeopleImagesButton"), ("places", "showPlacesImagesButton")))
def test_metadata_database_manager_shows_selected_entry_with_existing_search_mode(tmp_path, monkeypatch, kind, button_name):
    path = _image(tmp_path / f"{kind}.jpg")
    application, viewer = _viewer(tmp_path)
    entries = {
        "people": [{"id":1,"name":"Ingeborg","use_count":3,"last_used_at":"","hidden":0,"indexed_count":1,"latitude":None,"longitude":None}],
        "places": [{"id":2,"name":"Steyerberg","use_count":4,"last_used_at":"","hidden":0,"indexed_count":1,"latitude":52.0,"longitude":9.0}],
    }
    monkeypatch.setattr("bildbetrachter.metadata_entries", lambda entry_kind: entries[entry_kind])
    monkeypatch.setattr("bildbetrachter.search_images", lambda **kwargs: [path])
    shown = []
    monkeypatch.setattr(viewer, "_show_image_search_results", lambda paths: shown.extend(paths))
    def click_show():
        dialog = next(widget for widget in application.topLevelWidgets() if isinstance(widget, QDialog) and widget.objectName() == "metadataDatabaseManagerDialog" and widget.isVisible())
        button = dialog.findChild(QPushButton, button_name)
        assert button.isEnabled()
        button.click()
    QTimer.singleShot(0, click_show)
    viewer.manage_metadata_database_action.trigger()
    assert shown == [path]
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


def test_index_metadata_refresh_worker_runs_outside_gui_thread_and_reports_progress(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    worker_threads = []
    def fake_refresh(reader, path=None, progress=None, cancelled=None):
        worker_threads.append(QThread.currentThread())
        progress(0, 2); progress(1, 2); progress(2, 2)
        return 2
    monkeypatch.setattr("bildbetrachter.refresh_indexed_metadata", fake_refresh)
    task = ImageMetadataRefreshTask()
    values, finished = [], []
    task.signals.progress.connect(lambda current, total: values.append((current, total)), Qt.ConnectionType.DirectConnection)
    task.signals.finished.connect(lambda count, cancelled: finished.append((count, cancelled)), Qt.ConnectionType.DirectConnection)
    pool = QThreadPool.globalInstance(); pool.start(task)
    assert pool.waitForDone(3000)
    assert worker_threads and worker_threads[0] is not application.thread()
    assert values == [(0, 2), (1, 2), (2, 2)] and finished == [(2, False)]


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


def test_read_manual_metadata_treats_empty_gps_exif_values_as_missing(tmp_path, monkeypatch):
    path = _image(tmp_path / "empty-gps.jpg")
    monkeypatch.setattr("bildbetrachter._exiftool_json", lambda _: {
        "GPS:GPSLatitude": "", "GPS:GPSLongitude": "",
    })
    assert read_manual_image_metadata(path)["gps"] == ""


def test_person_list_is_replaced_instead_of_appended_in_real_jpeg(tmp_path):
    path = _image(tmp_path / "people-replacement.jpg")
    write_manual_image_metadata(path, {"people":"Horst, Ingeborg, Peter"})
    assert read_manual_image_metadata(path)["people"] == "Horst, Ingeborg, Peter"
    write_manual_image_metadata(path, {"people":"Ingeborg"})
    assert read_manual_image_metadata(path)["people"] == "Ingeborg"
    write_manual_image_metadata(path, {"people":"Ingeborg, Horst, Ingeborg, ,"})
    assert read_manual_image_metadata(path)["people"] == "Ingeborg, Horst"
    write_manual_image_metadata(path, {"people":""})
    assert read_manual_image_metadata(path)["people"] == ""


def test_gui_reloads_replaced_person_list_after_save_and_reopen(tmp_path, monkeypatch):
    path = _image(tmp_path / "people.jpg")
    other = _image(tmp_path / "other.jpg")
    write_manual_image_metadata(path, {"people":"Horst, Ingeborg, Peter"})
    monkeypatch.setattr("bildbetrachter.upsert_person", lambda *args: None)
    monkeypatch.setattr("bildbetrachter.update_indexed_image", lambda *args: True)
    application, viewer = _viewer(tmp_path)
    try:
        viewer.current_image = path; viewer._show_information_panel(); application.processEvents()
        people = viewer.manual_metadata_fields["people"]
        assert people.text() == "Horst, Ingeborg, Peter"
        resolved = viewer._resolved_sort_path(path)
        viewer._image_metadata_by_path[resolved] = {"people":"Horst, Ingeborg, Peter"}
        people.setText("Ingeborg")
        viewer.manual_metadata_save_button.click(); application.processEvents()
        assert not viewer.manual_metadata_dirty
        assert people.text() == "Ingeborg"
        assert read_manual_image_metadata(path)["people"] == "Ingeborg"
        assert viewer._image_metadata_by_path[resolved]["people"] == "Ingeborg"
        monkeypatch.setattr(QMessageBox, "exec", lambda self: pytest.fail("unexpected warning"))
        viewer.current_image = other; viewer._update_information_panel()
        viewer.current_image = path; viewer._update_information_panel()
        assert people.text() == "Ingeborg"
    finally:
        viewer.window.close()


def test_successful_metadata_save_updates_index_and_index_failure_does_not_undo_save(tmp_path, monkeypatch):
    path = _image(tmp_path / "indexed.jpg")
    application, viewer = _viewer(tmp_path)
    saved_calls, index_calls = [], []
    metadata = {"comment":"Neu", "people":"Ingeborg", "place":"Steyerberg", "gps":"52, 9"}
    monkeypatch.setattr("bildbetrachter.write_manual_image_metadata", lambda file_path, values: saved_calls.append((file_path, values)))
    monkeypatch.setattr("bildbetrachter.read_manual_image_metadata", lambda file_path: metadata)
    monkeypatch.setattr("bildbetrachter.upsert_person", lambda *args: None)
    monkeypatch.setattr("bildbetrachter.upsert_place", lambda *args: None)
    monkeypatch.setattr("bildbetrachter.place_coordinates", lambda *args: None)
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


def test_thumbnail_batch_selection_is_extended_but_pdf_pages_remain_single(tmp_path):
    application, viewer = _viewer(tmp_path)
    try:
        assert viewer.thumbnail_list.selectionMode() == viewer.thumbnail_list.SelectionMode.ExtendedSelection
        assert viewer.pdf_thumbnail_bar.selectionMode() == viewer.pdf_thumbnail_bar.SelectionMode.SingleSelection
    finally:
        viewer.window.close()


def test_thumbnail_ctrl_click_and_shift_click_select_individuals_and_ranges(tmp_path):
    application, viewer = _viewer(tmp_path)
    try:
        items = []
        for index in range(4):
            path = _image(tmp_path / f"select-{index}.jpg")
            item = QListWidgetItem(path.name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            viewer.thumbnail_list.addItem(item)
            items.append(item)
        application.processEvents()
        viewport = viewer.thumbnail_list.viewport()
        QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, viewer.thumbnail_list.visualItemRect(items[0]).center())
        QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, viewer.thumbnail_list.visualItemRect(items[2]).center())
        assert items[0].isSelected() and items[2].isSelected() and not items[1].isSelected()
        viewer.thumbnail_list.clearSelection()
        QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, viewer.thumbnail_list.visualItemRect(items[1]).center())
        QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, viewer.thumbnail_list.visualItemRect(items[3]).center())
        assert [item.isSelected() for item in items] == [False, True, True, True]
    finally:
        viewer.window.close()


def test_batch_editor_shows_common_and_mixed_values_and_tracks_only_touched_field(tmp_path, monkeypatch):
    first = _image(tmp_path / "one.jpg")
    second = _image(tmp_path / "two.jpg")
    metadata = {
        first: {"comment":"A", "people":"Horst", "place":"Steyerberg", "gps":"52, 9"},
        second: {"comment":"B", "people":"Ingeborg", "place":"Steyerberg", "gps":"53, 10"},
    }
    monkeypatch.setattr("bildbetrachter.read_manual_image_metadata", lambda path: metadata[path])
    application, viewer = _viewer(tmp_path)
    try:
        _add_selected_thumbnail(viewer, first, current=True)
        _add_selected_thumbnail(viewer, second)
        viewer._show_information_panel(); application.processEvents()
        assert viewer.batch_selection_label.text() == "2 Bilder ausgewählt"
        assert viewer.manual_metadata_fields["place"].text() == "Steyerberg"
        assert viewer.manual_metadata_fields["people"].text() == ""
        assert viewer.manual_metadata_fields["people"].placeholderText() == "Verschiedene Werte"
        assert not any(viewer.batch_touched.values())
        viewer.manual_metadata_fields["place"].setText("Nienburg")
        assert viewer.batch_touched == {"comment":False, "people":False, "place":True, "gps":False}
        assert viewer._batch_changes() == {"place":"Nienburg"}
        viewer.clear_manual_metadata_fields()
        assert not any(viewer.batch_touched.values())
        assert viewer.manual_metadata_fields["place"].text() == "Steyerberg"
    finally:
        viewer.window.close()


def test_batch_editor_reports_supported_jpegs_in_mixed_selection(tmp_path, monkeypatch):
    jpg = _image(tmp_path / "one.jpg")
    png = _image(tmp_path / "two.png")
    pdf = tmp_path / "three.pdf"; pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr("bildbetrachter.read_manual_image_metadata", lambda path: {"comment":"", "people":"", "place":"", "gps":""})
    application, viewer = _viewer(tmp_path)
    try:
        for index, path in enumerate((jpg, png, pdf)):
            _add_selected_thumbnail(viewer, path, current=index == 0)
        viewer._show_information_panel(); application.processEvents()
        assert viewer._batch_metadata_paths == [jpg]
        assert viewer.batch_selection_label.text() == "1 von 3 Dateien können bearbeitet werden"
    finally:
        viewer.window.close()


def test_batch_worker_continues_after_error_and_updates_each_successful_index(tmp_path, monkeypatch):
    paths = [_image(tmp_path / f"{index}.jpg") for index in range(3)]
    writes, indexes = [], []
    def write(path, changes):
        if path == paths[1]:
            raise OSError("schreibgeschützt")
        writes.append((path, changes))
    monkeypatch.setattr("bildbetrachter.write_manual_image_metadata", write)
    monkeypatch.setattr("bildbetrachter.read_manual_image_metadata", lambda path: {"comment":"", "people":"Horst", "place":"Neu", "gps":""})
    monkeypatch.setattr("bildbetrachter.update_indexed_image", lambda path, values: indexes.append(path))
    task = BatchMetadataTask(paths, {"place":"Neu"})
    result = []
    task.signals.finished.connect(lambda saved, errors, cancelled: result.append((saved, errors, cancelled)), Qt.ConnectionType.DirectConnection)
    task.run()
    assert [path for path, _ in writes] == [paths[0], paths[2]]
    assert indexes == [paths[0], paths[2]]
    assert len(result[0][0]) == 2 and result[0][1][0][0] == paths[1] and not result[0][2]


def test_batch_worker_can_cancel_after_completed_files(tmp_path, monkeypatch):
    paths = [_image(tmp_path / f"cancel-{index}.jpg") for index in range(3)]
    writes = []
    monkeypatch.setattr("bildbetrachter.write_manual_image_metadata", lambda path, changes: writes.append(path))
    monkeypatch.setattr("bildbetrachter.read_manual_image_metadata", lambda path: {"comment":"Neu", "people":"", "place":"", "gps":""})
    monkeypatch.setattr("bildbetrachter.update_indexed_image", lambda *args: False)
    task = BatchMetadataTask(paths, {"comment":"Neu"})
    result = []
    task.signals.progress.connect(lambda *_: task.cancel(), Qt.ConnectionType.DirectConnection)
    task.signals.finished.connect(lambda saved, errors, cancelled: result.append((saved, errors, cancelled)), Qt.ConnectionType.DirectConnection)
    task.run()
    assert writes == [paths[0]]
    assert len(result[0][0]) == 1 and not result[0][1] and result[0][2]


def test_batch_worker_runs_outside_gui_thread(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    path = _image(tmp_path / "thread.jpg")
    worker_threads = []
    monkeypatch.setattr("bildbetrachter.write_manual_image_metadata", lambda *_: worker_threads.append(QThread.currentThread()))
    monkeypatch.setattr("bildbetrachter.read_manual_image_metadata", lambda path: {"comment":"Neu", "people":"", "place":"", "gps":""})
    monkeypatch.setattr("bildbetrachter.update_indexed_image", lambda *args: False)
    task = BatchMetadataTask([path], {"comment":"Neu"})
    pool = QThreadPool.globalInstance(); pool.start(task)
    assert pool.waitForDone(3000)
    assert worker_threads and worker_threads[0] is not application.thread()


def test_metadata_bulk_worker_replaces_person_exactly_and_continues_after_error(tmp_path, monkeypatch):
    first = _image(tmp_path / "first.jpg")
    second = _image(tmp_path / "second.jpg")
    missing = tmp_path / "missing.jpg"
    stored = {
        first: {"comment":"", "people":"Horst, Ingebrog, Peter", "place":"", "gps":""},
        second: {"comment":"", "people":"Ingebrog, Ingeborg", "place":"", "gps":""},
    }
    writes, indexes = [], []
    monkeypatch.setattr("bildbetrachter.read_manual_image_metadata", lambda path: dict(stored[path]))
    def write(path, changes):
        writes.append((path, dict(changes))); stored[path].update(changes)
    monkeypatch.setattr("bildbetrachter.write_manual_image_metadata", write)
    monkeypatch.setattr("bildbetrachter.update_indexed_image", lambda image_path, values, **kwargs: indexes.append((image_path, values)))
    task = MetadataBulkEditTask([first, missing, second], "people", "Ingebrog", "Ingeborg")
    result = []
    task.signals.finished.connect(lambda saved, errors, cancelled: result.append((saved, errors, cancelled)), Qt.ConnectionType.DirectConnection)
    task.run()
    assert writes == [
        (first, {"people":"Horst, Ingeborg, Peter"}),
        (second, {"people":"Ingeborg"}),
    ]
    assert [path for path, _ in indexes] == [first, second]
    assert len(result[0][0]) == 2 and result[0][1][0][0] == missing


def test_metadata_bulk_place_edit_preserves_gps_and_supports_cancel(tmp_path, monkeypatch):
    paths = [_image(tmp_path / f"place-{index}.jpg") for index in range(2)]
    stored = {path:{"comment":"", "people":"", "place":"Steyerbeg", "gps":"52.0, 9.0"} for path in paths}
    writes = []
    monkeypatch.setattr("bildbetrachter.read_manual_image_metadata", lambda path: dict(stored[path]))
    def write(path, changes): writes.append(dict(changes)); stored[path].update(changes)
    monkeypatch.setattr("bildbetrachter.write_manual_image_metadata", write)
    monkeypatch.setattr("bildbetrachter.update_indexed_image", lambda *args, **kwargs: True)
    task = MetadataBulkEditTask(paths, "places", "Steyerbeg", "Steyerberg")
    task.signals.progress.connect(lambda *_: task.cancel(), Qt.ConnectionType.DirectConnection)
    result = []
    task.signals.finished.connect(lambda saved, errors, cancelled: result.append((saved, errors, cancelled)), Qt.ConnectionType.DirectConnection)
    task.run()
    assert writes == [{"place":"Steyerberg"}]
    assert stored[paths[0]]["gps"] == "52.0, 9.0"
    assert len(result[0][0]) == 1 and result[0][2]


@pytest.mark.parametrize(
    ("key", "value", "initial_people", "expected_people"),
    (
        ("people", "Ingeborg", "Horst", "Ingeborg"),
        ("people", "Ingeborg, Horst, Ingeborg, ,", "Horst", "Ingeborg, Horst"),
        ("people", "Ingeborg", "Horst, Ingeborg", "Ingeborg"),
        ("people", "", "Horst, Ingeborg", ""),
        ("place", "Nienburg", "Horst", "Horst"),
        ("comment", "Gemeinsam", "Horst", "Horst"),
        ("gps", "52.500000, 9.500000", "Horst", "Horst"),
    ),
)
def test_successful_batch_finish_clears_dirty_state_before_next_selection(
    tmp_path, monkeypatch, key, value, initial_people, expected_people
):
    paths = [_image(tmp_path / f"batch-{index}.jpg") for index in range(4)]
    stored = {
        path: {"comment":"Alt", "people":initial_people, "place":"Steyerberg", "gps":"52.000000, 9.000000"}
        for path in paths
    }
    monkeypatch.setattr("bildbetrachter.read_manual_image_metadata", lambda path: dict(stored[path]))
    monkeypatch.setattr("bildbetrachter.upsert_person", lambda *args: None)
    monkeypatch.setattr("bildbetrachter.upsert_place", lambda *args: None)
    application, viewer = _viewer(tmp_path)
    try:
        items = []
        for index, path in enumerate(paths):
            item = QListWidgetItem(path.name); item.setData(Qt.ItemDataRole.UserRole, path)
            viewer.thumbnail_list.addItem(item); items.append(item)
            if index < 3: item.setSelected(True)
        viewer.thumbnail_list.setCurrentItem(items[0], QItemSelectionModel.SelectionFlag.NoUpdate)
        viewer._show_information_panel(); application.processEvents()
        field = viewer.manual_metadata_fields[key]
        field.setPlainText(value) if hasattr(field, "setPlainText") else field.setText(value)
        assert viewer.manual_metadata_dirty and viewer.batch_touched[key]
        for path in paths[:3]:
            if key == "people":
                stored[path][key] = expected_people
            else:
                stored[path][key] = value
        class Progress:
            def close(self): pass
        viewer._batch_metadata_task = type("Task", (), {"paths": paths[:3]})()
        viewer._batch_metadata_progress = Progress()
        viewer._batch_metadata_finished(
            [(path, dict(stored[path])) for path in paths[:3]], [], False
        )
        assert not viewer.manual_metadata_dirty
        assert not any(viewer.batch_touched.values())
        monkeypatch.setattr(QMessageBox, "exec", lambda self: pytest.fail("unexpected unsaved-change dialog"))
        monkeypatch.setattr(
            "bildbetrachter.write_manual_image_metadata",
            lambda *args: pytest.fail("previous batch action was applied again"),
        )
        viewer.thumbnail_list.setCurrentItem(items[3], QItemSelectionModel.SelectionFlag.ClearAndSelect)
        application.processEvents()
        assert viewer.current_image == paths[3]
    finally:
        viewer.window.close()


def test_incomplete_batch_finish_keeps_pending_edit_dirty(tmp_path, monkeypatch):
    paths = [_image(tmp_path / f"partial-{index}.jpg") for index in range(3)]
    metadata = {"comment":"", "people":"Horst", "place":"Steyerberg", "gps":""}
    monkeypatch.setattr("bildbetrachter.read_manual_image_metadata", lambda path: dict(metadata))
    monkeypatch.setattr("bildbetrachter.upsert_place", lambda *args: None)
    application, viewer = _viewer(tmp_path)
    try:
        for index, path in enumerate(paths):
            _add_selected_thumbnail(viewer, path, current=index == 0)
        viewer._show_information_panel(); application.processEvents()
        viewer.manual_metadata_fields["place"].setText("Nienburg")
        class Progress:
            def close(self): pass
        viewer._batch_metadata_task = type("Task", (), {"paths": paths})()
        viewer._batch_metadata_progress = Progress()
        viewer._batch_metadata_finished([(paths[0], metadata)], [], True)
        assert viewer.manual_metadata_dirty
        assert viewer.batch_touched["place"]
        assert viewer.manual_metadata_fields["place"].text() == "Nienburg"
    finally:
        viewer.window.close()


def test_unsaved_batch_edit_still_warns_before_selection_change(tmp_path, monkeypatch):
    paths = [_image(tmp_path / f"warning-{index}.jpg") for index in range(3)]
    metadata = {"comment":"", "people":"Horst", "place":"Steyerberg", "gps":""}
    monkeypatch.setattr("bildbetrachter.read_manual_image_metadata", lambda path: dict(metadata))
    application, viewer = _viewer(tmp_path)
    try:
        items = []
        for index, path in enumerate(paths):
            item = QListWidgetItem(path.name); item.setData(Qt.ItemDataRole.UserRole, path)
            viewer.thumbnail_list.addItem(item); items.append(item)
            if index < 2: item.setSelected(True)
        viewer.thumbnail_list.setCurrentItem(items[0], QItemSelectionModel.SelectionFlag.NoUpdate)
        viewer._show_information_panel(); application.processEvents()
        viewer.manual_metadata_fields["place"].setText("Nienburg")
        shown = []
        monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.text()))
        viewer.thumbnail_list.setCurrentItem(items[2], QItemSelectionModel.SelectionFlag.ClearAndSelect)
        application.processEvents()
        assert shown and "geändert" in shown[0]
        assert viewer.manual_metadata_dirty and viewer.batch_touched["place"]
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
