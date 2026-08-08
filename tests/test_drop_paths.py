from pathlib import Path

from PySide6.QtCore import QUrl

from bildbetrachter import (
    drag_paths_for_selection,
    exportable_image_paths,
    resolve_dropped_paths,
)


def test_drop_single_image_opens_its_parent_and_selects_it(tmp_path: Path):
    image = tmp_path / "urlaub.JPG"
    image.touch()

    resolution = resolve_dropped_paths([image])

    assert resolution.error_message is None
    assert resolution.directory == tmp_path.resolve()
    assert resolution.selected_paths == [image.resolve()]
    assert resolution.primary_path == image.resolve()
    assert resolution.ignored_paths == []


def test_drop_multiple_images_keeps_order_and_selects_all(tmp_path: Path):
    first = tmp_path / "zuerst.png"
    second = tmp_path / "danach.webp"
    first.touch()
    second.touch()

    resolution = resolve_dropped_paths([first, second])

    assert resolution.error_message is None
    assert resolution.directory == tmp_path.resolve()
    assert resolution.selected_paths == [first.resolve(), second.resolve()]
    assert resolution.primary_path == first.resolve()
    assert resolution.ignored_paths == []


def test_drop_removes_duplicate_images_without_changing_order(tmp_path: Path):
    first = tmp_path / "eins.jpg"
    second = tmp_path / "zwei.jpg"
    first.touch()
    second.touch()

    resolution = resolve_dropped_paths([first, second, first])

    assert resolution.selected_paths == [first.resolve(), second.resolve()]
    assert resolution.primary_path == first.resolve()
    assert resolution.ignored_paths == [first]


def test_drop_uses_only_images_from_first_valid_directory(tmp_path: Path):
    first_directory = tmp_path / "eins"
    second_directory = tmp_path / "zwei"
    first_directory.mkdir()
    second_directory.mkdir()
    first = first_directory / "a.jpg"
    second = second_directory / "b.jpg"
    first.touch()
    second.touch()

    resolution = resolve_dropped_paths([first, second])

    assert resolution.error_message is None
    assert resolution.directory == first_directory.resolve()
    assert resolution.selected_paths == [first.resolve()]
    assert resolution.primary_path == first.resolve()
    assert resolution.ignored_paths == [second]


def test_drop_single_directory_opens_directory_without_selection(tmp_path: Path):
    resolution = resolve_dropped_paths([tmp_path])

    assert resolution.error_message is None
    assert resolution.directory == tmp_path.resolve()
    assert resolution.selected_paths == []
    assert resolution.primary_path is None


def test_drop_rejects_mixed_directory_and_image(tmp_path: Path):
    image = tmp_path / "bild.jpg"
    image.touch()

    resolution = resolve_dropped_paths([tmp_path, image])

    assert resolution.directory is None
    assert resolution.error_message is not None
    assert "Ordner oder Bilddateien" in resolution.error_message


def test_drop_rejects_unsupported_file(tmp_path: Path):
    document = tmp_path / "notizen.txt"
    document.touch()

    resolution = resolve_dropped_paths([document])

    assert resolution.directory is None
    assert resolution.error_message is not None
    assert "kein unterstütztes Bild- oder PDF-Format" in resolution.error_message


def test_drop_ignores_unsupported_file_when_a_valid_image_is_present(tmp_path: Path):
    image = tmp_path / "bild.jpg"
    document = tmp_path / "notizen.txt"
    image.touch()
    document.touch()

    resolution = resolve_dropped_paths([image, document])

    assert resolution.error_message is None
    assert resolution.selected_paths == [image.resolve()]
    assert resolution.primary_path == image.resolve()
    assert resolution.ignored_paths == [document]


def test_drop_rejects_missing_path(tmp_path: Path):
    resolution = resolve_dropped_paths([tmp_path / "fehlt.jpg"])

    assert resolution.directory is None
    assert resolution.error_message is not None
    assert "existiert nicht" in resolution.error_message


def test_drop_rejects_empty_path_list():
    resolution = resolve_dropped_paths([])

    assert resolution.directory is None
    assert resolution.error_message == "Es wurden keine Dateien oder Ordner abgelegt."


def test_exportable_paths_include_a_single_supported_image(tmp_path: Path):
    image = tmp_path / "bild.jpg"
    image.touch()

    assert exportable_image_paths([image]) == [image.resolve()]


def test_exportable_paths_include_all_selected_images_in_stable_order(tmp_path: Path):
    first = tmp_path / "eins.png"
    second = tmp_path / "zwei.tiff"
    first.touch()
    second.touch()

    assert exportable_image_paths([first, second, first]) == [
        first.resolve(),
        second.resolve(),
    ]


def test_exportable_paths_skip_missing_and_unsupported_files(tmp_path: Path):
    image = tmp_path / "bild.jpg"
    document = tmp_path / "notizen.txt"
    image.touch()
    document.touch()

    assert exportable_image_paths([tmp_path / "fehlt.jpg", document, image]) == [
        image.resolve()
    ]


def test_exportable_paths_are_valid_local_file_urls(tmp_path: Path):
    image = tmp_path / "mit leerzeichen.jpg"
    image.touch()

    urls = [QUrl.fromLocalFile(str(path)) for path in exportable_image_paths([image])]

    assert len(urls) == 1
    assert urls[0].isLocalFile()
    assert Path(urls[0].toLocalFile()) == image.resolve()


def test_drag_paths_for_single_selected_image(tmp_path: Path):
    image = tmp_path / "bild.jpg"
    image.touch()

    assert drag_paths_for_selection([image], image, []) == [image.resolve()]


def test_drag_paths_keep_multi_selection_snapshot_in_thumbnail_order(tmp_path: Path):
    first = tmp_path / "eins.jpg"
    second = tmp_path / "zwei.jpg"
    third = tmp_path / "drei.jpg"
    for path in (first, second, third):
        path.touch()

    assert drag_paths_for_selection(
        [third], third, [first, second, third]
    ) == [first.resolve(), second.resolve(), third.resolve()]


def test_drag_paths_keep_snapshot_when_last_selected_item_is_pressed(tmp_path: Path):
    first = tmp_path / "eins.jpg"
    second = tmp_path / "zwei.jpg"
    third = tmp_path / "drei.jpg"
    for path in (first, second, third):
        path.touch()

    assert drag_paths_for_selection(
        [third], third, [first, second, third]
    ) == [first.resolve(), second.resolve(), third.resolve()]


def test_drag_paths_use_only_unselected_pressed_item(tmp_path: Path):
    first = tmp_path / "eins.jpg"
    second = tmp_path / "zwei.jpg"
    third = tmp_path / "drei.jpg"
    for path in (first, second, third):
        path.touch()

    assert drag_paths_for_selection(
        [third], third, [first, second]
    ) == [third.resolve()]


def test_drag_paths_filter_duplicates_and_missing_files_from_snapshot(tmp_path: Path):
    first = tmp_path / "eins.jpg"
    second = tmp_path / "zwei.jpg"
    missing = tmp_path / "fehlt.jpg"
    first.touch()
    second.touch()

    assert drag_paths_for_selection(
        [second], second, [first, missing, second, first]
    ) == [first.resolve(), second.resolve()]
