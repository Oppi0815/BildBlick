import threading
from pathlib import Path

from PIL import Image
from PySide6.QtWidgets import QApplication

import i18n
from duplicate_finder import (
    RESULT_CONTROL_COLUMN_PADDING,
    DuplicateFinderDialog,
    VISUAL_THRESHOLDS,
    dhash,
    find_duplicates,
    hamming_distance,
)
from i18n import t


def image(path: Path, color: str = "white") -> Path:
    Image.new("RGB", (20, 20), color).save(path)
    return path


def search(roots, recursive=False):
    return find_duplicates(roots, recursive, {".jpg"}, threading.Event())


def test_exact_duplicates_across_multiple_folders_and_deduplicated_paths(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"; first.mkdir(); second.mkdir()
    source = image(first / "a.jpg"); (second / "b.jpg").write_bytes(source.read_bytes())
    result = search([first, second, first])
    assert result["examined"] == 2 and len(result["groups"]) == 1


def test_overlapping_roots_and_recursion_do_not_process_a_file_twice(tmp_path):
    child = tmp_path / "child"; child.mkdir(); image(child / "a.jpg")
    assert search([tmp_path, child], recursive=True)["examined"] == 1


def test_subdirectories_and_missing_roots(tmp_path):
    child = tmp_path / "child"; child.mkdir(); image(child / "a.jpg")
    assert search([tmp_path], recursive=False)["examined"] == 0
    result = search([tmp_path, tmp_path / "missing"], recursive=True)
    assert result["examined"] == 1 and result["missing_roots"]


def test_same_name_is_case_insensitive_unicode_and_independent_of_content(tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"; one.mkdir(); two.mkdir()
    image(one / "FÖTO.JPG", "white"); image(two / "föto.jpg", "black")
    result = find_duplicates([one, two], False, {".jpg"}, threading.Event(), search_exact=False, search_name=True)
    assert len(result["groups"]) == 1
    assert result["group_reasons"][result["groups"][0]] == {"name"}


def test_name_and_exact_result_share_one_group(tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"; one.mkdir(); two.mkdir()
    source = image(one / "same.jpg"); (two / "SAME.JPG").write_bytes(source.read_bytes())
    result = find_duplicates([one, two], False, {".jpg"}, threading.Event(), search_name=True)
    assert len(result["groups"]) == 1
    assert result["group_reasons"][result["groups"][0]] == {"exact", "name"}


def test_dhash_is_stable_and_visual_search_finds_same_image(tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"; one.mkdir(); two.mkdir()
    source = image(one / "a.jpg", "white"); (two / "other.jpg").write_bytes(source.read_bytes())
    assert hamming_distance(dhash(source), dhash(two / "other.jpg")) == 0
    result = find_duplicates([one, two], False, {".jpg"}, threading.Event(), search_exact=False, search_visual=True)
    assert result["group_reasons"][result["groups"][0]] == {"visual_equal"}


def test_visual_similar_images_have_a_nonzero_hamming_distance(tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"; one.mkdir(); two.mkdir()
    first = Image.new("L", (9, 8), 0)
    for y in range(8):
        for x in range(9):
            first.putpixel((x, y), x * 25)
    second = first.copy(); second.putpixel((4, 3), 255)
    first.save(one / "a.png"); second.save(two / "b.png")
    assert 0 < hamming_distance(dhash(one / "a.png"), dhash(two / "b.png")) <= VISUAL_THRESHOLDS["normal"]
    result = find_duplicates([one, two], False, {".png"}, threading.Event(), search_exact=False, search_visual=True)
    assert result["group_reasons"][result["groups"][0]] == {"visual_similar"}


def test_all_duplicate_reasons_are_preserved_for_visually_equal_files(tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"; one.mkdir(); two.mkdir()
    source = image(one / "same.jpg"); (two / "SAME.JPG").write_bytes(source.read_bytes())
    result = find_duplicates([one, two], False, {".jpg"}, threading.Event(), search_name=True, search_visual=True)
    assert result["group_reasons"][result["groups"][0]] == {"exact", "name", "visual_equal"}


def test_name_and_visual_similar_reasons_are_preserved(tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"; one.mkdir(); two.mkdir()
    first = Image.new("L", (9, 8), 0)
    for y in range(8):
        for x in range(9): first.putpixel((x, y), x * 25)
    second = first.copy(); second.putpixel((4, 3), 255)
    first.save(one / "same.png"); second.save(two / "SAME.PNG")
    result = find_duplicates([one, two], False, {".png"}, threading.Event(), search_exact=False, search_name=True, search_visual=True)
    assert result["group_reasons"][result["groups"][0]] == {"name", "visual_similar"}


def test_duplicate_finder_dynamic_texts_are_translated_in_all_languages():
    source = "Möchtest du die ausgewählten {count} Dateien in den Papierkorb verschieben?\n\nMindestens eine Datei jeder Duplikatgruppe bleibt erhalten."
    no_results = "Keine doppelten Dateien mehr vorhanden."
    summary = "{examined} Bilddateien untersucht · {groups} Duplikatgruppen · {files} mehrfach vorhandene Dateien · {size} theoretisch freigebbar · {skipped} übersprungen oder fehlerhaft"
    original = i18n._language
    try:
        for code in ("de", "en", "fr", "es", "uk"):
            i18n._language = code
            assert t(source).format(count=3)
            assert t(summary).format(examined=4, groups=1, files=2, size="1,0 MB", skipped=0)
            if code != "de":
                assert t(source) != source
                assert t(no_results) != no_results
    finally:
        i18n._language = original


def test_visual_results_do_not_automatically_mark_files_for_trash(tmp_path):
    app = QApplication.instance() or QApplication([])
    one, two = tmp_path / "one", tmp_path / "two"; one.mkdir(); two.mkdir()
    source = image(one / "a.jpg"); (two / "b.jpg").write_bytes(source.read_bytes())
    result = find_duplicates([one, two], False, {".jpg"}, threading.Event(), search_exact=False, search_visual=True)
    dialog = DuplicateFinderDialog(None, one, {".jpg"})
    try:
        dialog._show_results(result)
        assert all(not entry["trash"].isChecked() for controls in dialog._group_controls for entry in controls["entries"])
    finally:
        dialog.close()


def test_duplicate_finder_result_controls_and_columns_are_wide_enough(tmp_path):
    app = QApplication.instance() or QApplication([])
    one, two = tmp_path / "one", tmp_path / "two"; one.mkdir(); two.mkdir()
    source = image(one / "a.jpg"); (two / "b.jpg").write_bytes(source.read_bytes())
    result = find_duplicates([one, two], False, {".jpg"}, threading.Event())
    dialog = DuplicateFinderDialog(None, one, {".jpg"})
    try:
        dialog._show_results(result)
        controls = dialog._group_controls[0]
        assert dialog.results.columnWidth(6) >= controls["mark_button"].sizeHint().width() + RESULT_CONTROL_COLUMN_PADDING
        assert dialog.results.columnWidth(7) >= controls["clear_button"].sizeHint().width() + RESULT_CONTROL_COLUMN_PADDING
        assert dialog.results.columnWidth(6) >= dialog.results.headerItem().text(6).__len__()
    finally:
        dialog.close()


def test_search_status_animation_and_progress_lifecycle(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    dialog = DuplicateFinderDialog(None, tmp_path, {".jpg"})
    monkeypatch.setattr(dialog._pool, "start", lambda task: None)
    try:
        dialog.show(); app.processEvents()
        dialog.visual_checkbox.setChecked(True)
        dialog._start_search()
        assert dialog.status_panel.isVisible()
        assert dialog._activity_timer.isActive()
        dialog._set_total(12); dialog._set_progress(7)
        assert dialog._search_checked == 7
        assert "7" in dialog.status_numbers.text()
        dialog._search_finished({"cancelled": True})
        assert not dialog._activity_timer.isActive()
        assert not dialog.status_panel.isVisible()
    finally:
        dialog.close()


def test_visual_thresholds_are_ordered_and_different_images_do_not_match(tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"; one.mkdir(); two.mkdir()
    image(one / "a.jpg", "white")
    patterned = Image.new("RGB", (20, 20), "black")
    for x in range(20):
        for y in range(20):
            if (x + y) % 2:
                patterned.putpixel((x, y), (255, 255, 255))
    patterned.save(two / "b.jpg")
    assert VISUAL_THRESHOLDS["strict"] < VISUAL_THRESHOLDS["normal"] < VISUAL_THRESHOLDS["generous"]
    result = find_duplicates([one, two], False, {".jpg"}, threading.Event(), search_exact=False, search_visual=True)
    assert result["groups"] == []
