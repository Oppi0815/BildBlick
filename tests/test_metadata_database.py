import sqlite3

import pytest

from image_index import search_images
from metadata_database import (
    hide_metadata_entry, metadata_entries, place_coordinates, rename_metadata_entry,
    set_place_coordinates,
    suggest_people, suggest_places, upsert_person, upsert_place,
)


def test_people_places_and_suggestions_use_a_temporary_database(tmp_path):
    database = tmp_path / "metadata.db"
    upsert_person(" Ingeborg ", database)
    upsert_person("INGEBORG", database)
    upsert_person("Ingrid", database)
    upsert_place("Steyerberg", 52.0, 9.0, database)
    upsert_place("STEYERBERG", 53.0, 10.0, database)

    assert suggest_people("ing", path=database) == ["Ingeborg", "Ingrid"]
    assert suggest_places("ste", path=database) == ["Steyerberg"]
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        assert connection.execute("SELECT use_count, latitude, longitude FROM places").fetchone() == (2, 52.0, 9.0)


def test_place_coordinates_are_explicitly_editable_and_clearable(tmp_path):
    database = tmp_path / "metadata.db"
    upsert_place("Steyerberg", path=database)
    assert place_coordinates("Steyerberg", database) is None
    set_place_coordinates("Steyerberg", 52.123456, 9.654321, database)
    assert place_coordinates(" steyerberg ", database) == (52.123456, 9.654321)
    set_place_coordinates("Steyerberg", None, None, database)
    assert place_coordinates("Steyerberg", database) is None
    with pytest.raises(ValueError):
        set_place_coordinates("Steyerberg", 91, 9, database)


def test_person_rename_merge_and_hide_preserve_relations_and_suggestions(tmp_path):
    database = tmp_path / "metadata.db"
    upsert_person("Ingebrog", database); upsert_person("Ingeborg", database)
    entries = metadata_entries("people", database)
    typo = next(entry for entry in entries if entry["name"] == "Ingebrog")
    original_id = typo["id"]
    rename_metadata_entry("people", original_id, "Inge Borg", path=database)
    renamed = next(entry for entry in metadata_entries("people", database) if entry["name"] == "Inge Borg")
    assert renamed["id"] == original_id
    assert suggest_people("inge", path=database) == ["Ingeborg", "Inge Borg"]
    image_path = tmp_path / "person.jpg"; image_path.write_bytes(b"jpeg-copy")
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        image_id = connection.execute(
            "INSERT INTO images(file_path,file_name,directory_path) VALUES(?,?,?)",
            (str(image_path), image_path.name, str(tmp_path)),
        ).lastrowid
        connection.execute(
            "INSERT INTO image_people(image_id,person_id) VALUES(?,?)", (image_id, original_id)
        )
        connection.commit()
    surviving_id = rename_metadata_entry(
        "people", original_id, "Ingeborg", merge=True, path=database
    )
    assert surviving_id != original_id
    assert [entry["name"] for entry in metadata_entries("people", database)] == ["Ingeborg"]
    assert search_images(person="Ingeborg", path=database) == [image_path]
    assert search_images(person="Inge Borg", path=database) == []
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT person_id FROM image_people").fetchone()[0] == surviving_id
    hide_metadata_entry("people", surviving_id, database)
    assert suggest_people("inge", path=database) == []
    assert metadata_entries("people", database)[0]["hidden"] == 1


def test_place_rename_updates_index_value_without_changing_coordinates(tmp_path):
    database = tmp_path / "metadata.db"
    upsert_place("Steyerbeg", 52.1, 9.2, database)
    entry = metadata_entries("places", database)[0]
    image_path = tmp_path / "place.jpg"; image_path.write_bytes(b"jpeg-copy")
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO images(file_path,file_name,directory_path,place_name) VALUES(?,?,?,'Steyerbeg')",
            (str(image_path), image_path.name, str(tmp_path)),
        )
        connection.commit()
    rename_metadata_entry("places", entry["id"], "Steyerberg", path=database)
    renamed = metadata_entries("places", database)[0]
    assert (renamed["name"], renamed["latitude"], renamed["longitude"]) == ("Steyerberg", 52.1, 9.2)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT place_name FROM images").fetchone()[0] == "Steyerberg"
    assert search_images(place="Steyerberg", path=database) == [image_path]
    assert search_images(place="Steyerbeg", path=database) == []
