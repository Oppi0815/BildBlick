"""Local, optional suggestion storage for manual image information."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 2


def metadata_database_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys_platform() == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".local" / "share"
    return base / "BildBlick" / "metadata.db"


def sys_platform() -> str:
    import sys
    return sys.platform


def _normalized(value: str) -> str:
    return " ".join(value.split()).casefold()


def _connection(path: Path | None = None) -> sqlite3.Connection:
    database = path or metadata_database_path()
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    initialize_metadata_database(connection)
    return connection


def initialize_metadata_database(connection_or_path: sqlite3.Connection | Path | None = None) -> None:
    owns_connection = not isinstance(connection_or_path, sqlite3.Connection)
    connection = _connection(connection_or_path) if owns_connection else connection_or_path
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS people (id INTEGER PRIMARY KEY, name TEXT NOT NULL,
          normalized_name TEXT NOT NULL UNIQUE, use_count INTEGER NOT NULL DEFAULT 0,
          created_at TEXT, updated_at TEXT, last_used_at TEXT);
        CREATE TABLE IF NOT EXISTS places (id INTEGER PRIMARY KEY, name TEXT NOT NULL,
          normalized_name TEXT NOT NULL UNIQUE, latitude REAL NULL, longitude REAL NULL,
          use_count INTEGER NOT NULL DEFAULT 0, created_at TEXT, updated_at TEXT, last_used_at TEXT);
    """)
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version < 2:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS images (id INTEGER PRIMARY KEY, file_path TEXT NOT NULL UNIQUE,
              file_name TEXT NOT NULL, directory_path TEXT NOT NULL, modified_time REAL, file_size INTEGER,
              comment TEXT, place_name TEXT, latitude REAL, longitude REAL, indexed_at TEXT);
            CREATE TABLE IF NOT EXISTS image_people (image_id INTEGER NOT NULL, person_id INTEGER NOT NULL,
              UNIQUE(image_id, person_id), FOREIGN KEY(image_id) REFERENCES images(id) ON DELETE CASCADE,
              FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS indexed_folders (id INTEGER PRIMARY KEY, folder_path TEXT NOT NULL UNIQUE,
              recursive INTEGER NOT NULL DEFAULT 0, added_at TEXT, last_scan_at TEXT);
            CREATE INDEX IF NOT EXISTS images_directory_path_index ON images(directory_path);
            CREATE INDEX IF NOT EXISTS images_place_name_index ON images(place_name);
            CREATE INDEX IF NOT EXISTS image_people_person_id_index ON image_people(person_id);
        """)
        connection.execute("PRAGMA user_version = 2")
    connection.commit()
    if owns_connection:
        connection.close()


def _upsert(table: str, name: str, latitude: float | None = None, longitude: float | None = None, path: Path | None = None) -> None:
    name = " ".join(name.split())
    if not name:
        return
    now = datetime.now(timezone.utc).isoformat()
    normalized = _normalized(name)
    if table == "people":
        with _connection(path) as connection:
            connection.execute("""INSERT INTO people (name, normalized_name, use_count, created_at, updated_at, last_used_at)
                VALUES (?, ?, 1, ?, ?, ?) ON CONFLICT(normalized_name) DO UPDATE SET
                use_count=people.use_count + 1, updated_at=excluded.updated_at, last_used_at=excluded.last_used_at""", (name, normalized, now, now, now))
        return
    with _connection(path) as connection:
        connection.execute(f"""INSERT INTO {table} (name, normalized_name, latitude, longitude, use_count, created_at, updated_at, last_used_at)
            VALUES (?, ?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(normalized_name) DO UPDATE SET use_count={table}.use_count + 1,
              updated_at=excluded.updated_at, last_used_at=excluded.last_used_at,
              latitude=CASE WHEN {table}.latitude IS NULL THEN excluded.latitude ELSE {table}.latitude END,
              longitude=CASE WHEN {table}.longitude IS NULL THEN excluded.longitude ELSE {table}.longitude END""",
            (name, normalized, latitude, longitude, now, now, now))


def upsert_person(name: str, path: Path | None = None) -> None:
    _upsert("people", name, path=path)


def upsert_place(name: str, latitude: float | None = None, longitude: float | None = None, path: Path | None = None) -> None:
    _upsert("places", name, latitude, longitude, path)


def _suggest(table: str, prefix: str, limit: int, path: Path | None) -> list[str]:
    prefix = _normalized(prefix)
    if not prefix:
        return []
    with _connection(path) as connection:
        rows = connection.execute(f"""SELECT name FROM {table} WHERE normalized_name LIKE ?
            ORDER BY CASE WHEN normalized_name LIKE ? THEN 0 ELSE 1 END, use_count DESC,
            last_used_at DESC, name COLLATE NOCASE LIMIT ?""", (f"%{prefix}%", f"{prefix}%", limit)).fetchall()
    return [row["name"] for row in rows]


def suggest_people(prefix: str, limit: int = 10, path: Path | None = None) -> list[str]:
    return _suggest("people", prefix, limit, path)


def suggest_places(prefix: str, limit: int = 10, path: Path | None = None) -> list[str]:
    return _suggest("places", prefix, limit, path)
