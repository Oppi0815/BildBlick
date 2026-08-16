import sqlite3

from metadata_database import suggest_people, suggest_places, upsert_person, upsert_place


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
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("SELECT use_count, latitude, longitude FROM places").fetchone() == (2, 52.0, 9.0)
