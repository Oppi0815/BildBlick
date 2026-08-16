from pathlib import Path
import sqlite3

from image_index import (
    index_folder, indexed_folders, remove_indexed_folder, search_images,
    update_indexed_image,
)
from metadata_database import initialize_metadata_database

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
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2


def test_progress_cancel_remove_and_direct_update_leave_files_untouched(tmp_path):
    database = tmp_path / "metadata.db"
    folder = tmp_path / "images"; folder.mkdir()
    files = [folder / f"{index}.jpg" for index in range(3)]
    for file_path in files: file_path.write_bytes(b"jpeg-copy")
    progress = []
    def metadata(file_path):
        return {"comment": file_path.stem, "people": "Horst", "place": "Steyerberg", "gps": "52, 9"}
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
    remove_indexed_folder(folder, database)
    assert indexed_folders(database) == [] and all(file_path.exists() for file_path in files)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM images").fetchone()[0] == 0
