from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from bildbetrachter import (
    ImageViewer,
    _metadata_value_present,
    _raw_metadata_text,
    build_all_image_metadata,
    build_information_metadata,
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

    assert viewer.thumbnail_panel.isAncestorOf(viewer.previous_button)
    assert viewer.thumbnail_panel.isAncestorOf(viewer.next_button)
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
