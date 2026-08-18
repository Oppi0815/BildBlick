from pathlib import Path
import sqlite3

import metadata_database

from image_index import (
    index_folder, indexed_folders, remove_indexed_folder, search_images,
    refresh_indexed_metadata, update_indexed_image,
)
from metadata_database import initialize_metadata_database, suggest_people, suggest_places, upsert_person

def test_index_migrates_and_searches_metadata(tmp_path):
    database = tmp_path / "metadata.db"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version=1")
        connection.execute("CREATE TABLE people(id INTEGER PRIMARY KEY, name TEXT NOT NULL, normalized_name TEXT NOT NULL UNIQUE, use_count INTEGER NOT NULL DEFAULT 0, created_at TEXT, updated_at TEXT, last_used_at TEXT)")
    initialize_metadata_database(database)
    images = tmp_path / "images"; images.mkdir()
    first, second = images / "honda.jpg", images / "garden.JPG"
    first.write_bytes(b"a"); second.write_bytes(b"b")
    metadata = {first: {"comment":"Honda", "people":"Horst, Ingeborg", "place":"Steyerberg"}, second:{"comment":"Garten", "people":"Ingeborg", "place":"Nienburg"}}
    assert index_folder(images, False, metadata.get, database) == 2
    assert search_images(person="Ingeborg", path=database) == [second, first]
    assert search_images(person="Ingeborg", place="Steyerberg", path=database) == [first]
    assert search_images(comment="HONDA", path=database) == [first]
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4


def test_progress_cancel_remove_and_direct_update_leave_files_untouched(tmp_path):
    database = tmp_path / "metadata.db"
    folder = tmp_path / "images"; folder.mkdir()
    files = [folder / f"{index}.jpg" for index in range(3)]
    for file_path in files: file_path.write_bytes(b"jpeg-copy")
    progress = []
    def metadata(file_path):
        people = "Horst, Ingeborg, Peter" if file_path == files[0] else "Horst"
        return {"comment": file_path.stem, "people": people, "place": "Steyerberg", "gps": "52, 9"}
    index_folder(folder, False, metadata, database, lambda current, total: progress.append((current, total)), lambda: bool(progress and progress[-1][0] >= 1))
    assert progress[0] == (0, 3) and progress[-1] == (1, 3)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT count(*) FROM images").fetchone()[0] == 1

    index_folder(folder, False, metadata, database)
    assert indexed_folders(database)[0][:2] == (folder, False)
    assert update_indexed_image(files[0], {"comment":"Neu", "people":"Ingeborg", "place":"Nienburg", "gps":"53, 10"}, database)
    outside = tmp_path / "outside.jpg"; outside.write_bytes(b"jpeg-copy")
    assert not update_indexed_image(outside, metadata(outside), database)
    assert search_images(comment="neu", path=database) == [files[0]]
    with sqlite3.connect(database) as connection:
        indexed_people = connection.execute(
            "SELECT people.name FROM images JOIN image_people ON image_people.image_id=images.id "
            "JOIN people ON people.id=image_people.person_id WHERE images.file_path=?",
            (str(files[0]),),
        ).fetchall()
        assert indexed_people == [("Ingeborg",)]
        assert connection.execute(
            "SELECT name FROM people WHERE normalized_name IN ('horst','peter') ORDER BY normalized_name"
        ).fetchall() == [("Horst",), ("Peter",)]
    remove_indexed_folder(folder, database)
    assert indexed_folders(database) == [] and all(file_path.exists() for file_path in files)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM images").fetchone()[0] == 0


def test_deliberately_added_empty_folders_are_registered_once_with_their_scan_mode(tmp_path):
    database = tmp_path / "metadata.db"
    with_images = tmp_path / "with-images"; with_images.mkdir()
    empty = tmp_path / "empty"; empty.mkdir()
    (with_images / "photo.jpg").write_bytes(b"jpeg-copy")

    assert index_folder(with_images, True, lambda _: {"comment": "", "people": "", "place": "", "gps": ""}, database) == 1
    assert index_folder(empty, False, lambda _: {"comment": "", "people": "", "place": "", "gps": ""}, database) == 0
    # Re-adding must update the choice without creating a duplicate record.
    assert index_folder(empty, True, lambda _: {"comment": "", "people": "", "place": "", "gps": ""}, database) == 0

    assert [(folder, recursive) for folder, recursive, _ in indexed_folders(database)] == [
        (empty, True), (with_images, True),
    ]
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT folder_path, recursive, added_at, last_scan_at FROM indexed_folders ORDER BY folder_path"
        ).fetchall()
    assert len(rows) == 2
    assert all(added_at and last_scan_at for _, _, added_at, last_scan_at in rows)


def test_recursive_parent_removes_existing_child_registration_without_removing_images(tmp_path):
    database = tmp_path / "metadata.db"
    parent = tmp_path / "2026"; child = parent / "2026-01"
    child.mkdir(parents=True)
    photo = child / "photo.jpg"; photo.write_bytes(b"jpeg-copy")
    metadata = lambda _: {"comment": "", "people": "", "place": "", "gps": ""}

    assert index_folder(child, False, metadata, database) == 1
    assert index_folder(parent, True, metadata, database) == 1
    assert [(folder, recursive) for folder, recursive, _ in indexed_folders(database)] == [(parent, True)]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT file_path FROM images").fetchall() == [(str(photo),)]


def test_child_is_not_registered_when_recursive_parent_already_covers_it(tmp_path):
    database = tmp_path / "metadata.db"
    parent = tmp_path / "2026"; child = parent / "2026-01"; child.mkdir(parents=True)
    assert index_folder(parent, True, lambda _: {}, database) == 0
    assert index_folder(child, False, lambda _: {}, database) == 0
    assert [(folder, recursive) for folder, recursive, _ in indexed_folders(database)] == [(parent, True)]


def test_non_recursive_parent_allows_child_and_path_prefixes_are_not_parents(tmp_path):
    database = tmp_path / "metadata.db"
    parent = tmp_path / "2026"; child = parent / "2026-01"; lookalike = tmp_path / "20260"
    child.mkdir(parents=True); lookalike.mkdir()
    assert index_folder(parent, False, lambda _: {}, database) == 0
    assert index_folder(child, False, lambda _: {}, database) == 0
    assert index_folder(lookalike, False, lambda _: {}, database) == 0
    assert [(folder, recursive) for folder, recursive, _ in indexed_folders(database)] == [
        (parent, False), (child, False), (lookalike, False),
    ]


def test_successful_scans_set_last_scan_for_all_scan_modes_and_empty_folders(tmp_path):
    database = tmp_path / "metadata.db"
    direct = tmp_path / "direct"; recursive = tmp_path / "recursive"; empty = tmp_path / "empty"
    (recursive / "child").mkdir(parents=True); direct.mkdir(); empty.mkdir()
    (direct / "photo.jpg").write_bytes(b"jpeg-copy")
    (recursive / "child" / "photo.jpg").write_bytes(b"jpeg-copy")
    for folder, is_recursive in ((direct, False), (recursive, True), (empty, False)):
        index_folder(folder, is_recursive, lambda _: {}, database)
    scans = {folder: last_scan for folder, _recursive, last_scan in indexed_folders(database)}
    assert all(scans[folder] for folder in (direct, recursive, empty))


def test_cancelled_scan_does_not_set_last_scan_at(tmp_path):
    database = tmp_path / "metadata.db"
    folder = tmp_path / "cancelled"; folder.mkdir()
    (folder / "photo.jpg").write_bytes(b"jpeg-copy")
    assert index_folder(folder, True, lambda _: {}, database, cancelled=lambda: True) == 1
    assert indexed_folders(database) == [(folder, True, "")]


def test_default_add_and_manage_api_share_the_configured_metadata_database(tmp_path, monkeypatch):
    database = tmp_path / "application-data" / "metadata.db"
    folder = tmp_path / "empty"; folder.mkdir()
    monkeypatch.setattr(metadata_database, "metadata_database_path", lambda: database)

    assert index_folder(folder, False, lambda _: {}, None) == 0
    managed_entries = indexed_folders()
    assert len(managed_entries) == 1
    assert managed_entries[0][:2] == (folder, False)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT folder_path, recursive FROM indexed_folders").fetchall() == [
            (str(folder), 0)
        ]


def test_refresh_indexed_metadata_reloads_all_fields_without_increasing_input_counts(tmp_path):
    database = tmp_path / "metadata.db"
    folder = tmp_path / "indexed"; folder.mkdir()
    first, stale = folder / "first.jpg", folder / "stale.jpeg"
    first.write_bytes(b"jpeg-copy"); stale.write_bytes(b"jpeg-copy")
    old = {
        first: {"comment":"Alt", "people":"Horst", "place":"Altort", "gps":"1, 2"},
        stale: {"comment":"Stale", "people":"Peter", "place":"Altort", "gps":""},
    }
    assert index_folder(folder, False, old.get, database) == 2
    upsert_person("Horst", database)
    with sqlite3.connect(database) as connection:
        count_before = connection.execute("SELECT use_count FROM people WHERE normalized_name='horst'").fetchone()[0]
    stale.unlink()
    current = {
        first: {"comment":"Neu", "people":"Ingeborg", "place":"Steyerberg", "gps":"52.1, 9.2"},
    }
    progress = []
    assert refresh_indexed_metadata(current.get, database, lambda current_count, total: progress.append((current_count, total))) == 1
    assert progress == [(0, 1), (1, 1)]
    assert search_images(person="Ingeborg", path=database) == [first]
    assert search_images(person="Horst", path=database) == []
    assert search_images(place="Steyerberg", path=database) == [first]
    assert search_images(comment="neu", path=database) == [first]
    assert suggest_people("ing", path=database) == ["Ingeborg"]
    assert suggest_places("ste", path=database) == ["Steyerberg"]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT comment,place_name,latitude,longitude FROM images").fetchone() == ("Neu", "Steyerberg", 52.1, 9.2)
        assert connection.execute("SELECT count(*) FROM images").fetchone()[0] == 1
        assert connection.execute("SELECT use_count FROM people WHERE normalized_name='horst'").fetchone()[0] == count_before


def test_refresh_indexed_metadata_cancellation_keeps_database_consistent(tmp_path):
    database = tmp_path / "metadata.db"
    folder = tmp_path / "indexed"; folder.mkdir()
    files = [folder / f"{index}.jpg" for index in range(3)]
    for file_path in files: file_path.write_bytes(b"jpeg-copy")
    metadata = {file_path:{"comment":"old", "people":"Horst", "place":"Ort", "gps":""} for file_path in files}
    index_folder(folder, False, metadata.get, database)
    progress = []
    refresh_indexed_metadata(
        lambda path: {"comment":"new", "people":"Ingeborg", "place":"Neu", "gps":""},
        database, lambda current, total: progress.append((current, total)),
        lambda: bool(progress and progress[-1][0] >= 1),
    )
    assert progress == [(0, 3), (1, 3)]
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT count(*) FROM images").fetchone()[0] == 3
