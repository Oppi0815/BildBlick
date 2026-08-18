import sqlite3

import metadata_database


def test_face_schema_migration_preserves_existing_rows(tmp_path):
    path = tmp_path / "metadata.db"
    connection = sqlite3.connect(path)
    connection.executescript("""
      CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT NOT NULL, normalized_name TEXT NOT NULL UNIQUE, use_count INTEGER NOT NULL DEFAULT 0, created_at TEXT, updated_at TEXT, last_used_at TEXT, hidden INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE places (id INTEGER PRIMARY KEY, name TEXT NOT NULL, normalized_name TEXT NOT NULL UNIQUE, latitude REAL, longitude REAL, use_count INTEGER NOT NULL DEFAULT 0, created_at TEXT, updated_at TEXT, last_used_at TEXT, hidden INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE images (id INTEGER PRIMARY KEY, file_path TEXT NOT NULL UNIQUE, file_name TEXT NOT NULL, directory_path TEXT NOT NULL, modified_time REAL, file_size INTEGER, comment TEXT, place_name TEXT, latitude REAL, longitude REAL, indexed_at TEXT);
      INSERT INTO people(name,normalized_name) VALUES ('Ada','ada');
      PRAGMA user_version = 3;
    """); connection.commit(); connection.close()
    metadata_database.initialize_metadata_database(path)
    connection = sqlite3.connect(path)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
    assert connection.execute("SELECT name FROM people").fetchone()[0] == "Ada"
    assert connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='face_references'").fetchone()
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
