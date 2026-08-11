from datetime import datetime

from PIL import Image

from bildbetrachter import capture_date_text, multi_image_sources


def test_multi_image_sources_reuses_capture_date_format_from_exif(tmp_path):
    image_path = tmp_path / "EXIF-Aufnahmedatum.jpg"
    image = Image.new("RGB", (20, 10), "white")
    exif = Image.Exif()
    exif[36867] = "2026:08:11 14:30:00"
    image.save(image_path, exif=exif)

    display_date = capture_date_text(image_path)
    source = multi_image_sources([image_path], include_capture_date=True)[0]

    assert display_date == "11.08.2026 14:30"
    assert source.capture_date == display_date


def test_multi_image_sources_handles_missing_exif_without_crashing(tmp_path):
    image_path = tmp_path / "ohne-exif.jpg"
    Image.new("RGB", (20, 10), "white").save(image_path)
    expected = datetime.fromtimestamp(image_path.stat().st_mtime).strftime("%d.%m.%Y %H:%M")

    source = multi_image_sources([image_path], include_capture_date=True)[0]

    assert source.capture_date == expected
