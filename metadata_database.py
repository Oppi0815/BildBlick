"""Local, optional suggestion storage for manual image information."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 4


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
    if version < 3:
        for table in ("people", "places"):
            columns = {
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            }
            if "hidden" not in columns:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0"
                )
        connection.execute("PRAGMA user_version = 3")
    if version < 4:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS face_models (id INTEGER PRIMARY KEY CHECK(id=1),
              detector_model TEXT NOT NULL, recognition_model TEXT NOT NULL,
              embedding_dimension INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS face_references (id INTEGER PRIMARY KEY,
              person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
              embedding BLOB NOT NULL, source_image_path TEXT NOT NULL,
              source_face_index INTEGER NOT NULL, detection_confidence REAL NOT NULL,
              quality REAL NULL, created_at TEXT NOT NULL,
              UNIQUE(person_id, source_image_path, source_face_index));
        """)
        connection.execute("PRAGMA user_version = 4")
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


def person_id_for_name(name: str, path: Path | None = None) -> int:
    """Return the existing/local person id, creating the suggested person if needed."""
    _upsert("people", name, path=path)
    with _connection(path) as connection:
        return int(connection.execute("SELECT id FROM people WHERE normalized_name=?", (_normalized(name),)).fetchone()[0])


def find_person_id(name: str, path: Path | None = None) -> int | None:
    """Return an existing people-table id without changing the database."""
    with _connection(path) as connection:
        row = connection.execute(
            "SELECT id FROM people WHERE normalized_name=?", (_normalized(name),)
        ).fetchone()
    return int(row[0]) if row is not None else None


def face_reference_vectors(path: Path | None = None) -> dict[int, tuple[str, list[bytes]]]:
    with _connection(path) as connection:
        rows = connection.execute("SELECT p.id,p.name,r.embedding FROM people p JOIN face_references r ON r.person_id=p.id ORDER BY p.id,r.id").fetchall()
    result: dict[int, tuple[str, list[bytes]]] = {}
    for row in rows:
        result.setdefault(row["id"], (row["name"], []))[1].append(row["embedding"])
    return result


def add_face_reference(person_id: int, embedding: bytes, source_image_path: str, source_face_index: int, confidence: float, quality: float | None = None, path: Path | None = None) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with _connection(path) as connection:
        cursor = connection.execute("""INSERT OR IGNORE INTO face_references
            (person_id,embedding,source_image_path,source_face_index,detection_confidence,quality,created_at)
            VALUES (?,?,?,?,?,?,?)""", (person_id, embedding, source_image_path, source_face_index, confidence, quality, now))
    return cursor.rowcount == 1


def face_reference_entries(path: Path | None = None) -> list[dict]:
    with _connection(path) as connection:
        rows = connection.execute("""SELECT r.id,r.person_id,p.name,r.source_image_path,r.source_face_index,
          r.detection_confidence,r.quality,r.created_at FROM face_references r JOIN people p ON p.id=r.person_id
          ORDER BY p.name COLLATE NOCASE,r.created_at DESC""").fetchall()
    return [dict(row) for row in rows]


def delete_face_references(ids: list[int], path: Path | None = None) -> int:
    if not ids: return 0
    with _connection(path) as connection:
        cursor = connection.executemany("DELETE FROM face_references WHERE id=?", [(value,) for value in ids])
    return cursor.rowcount


def face_reference_owner(source_image_path: str, source_face_index: int, path: Path | None = None) -> str | None:
    with _connection(path) as connection:
        row = connection.execute("SELECT p.name FROM face_references r JOIN people p ON p.id=r.person_id WHERE r.source_image_path=? AND r.source_face_index=? LIMIT 1", (source_image_path, source_face_index)).fetchone()
    return None if row is None else str(row["name"])


def upsert_place(name: str, latitude: float | None = None, longitude: float | None = None, path: Path | None = None) -> None:
    _upsert("places", name, latitude, longitude, path)


def place_coordinates(name: str, path: Path | None = None) -> tuple[float, float] | None:
    """Return locally stored coordinates for a place, if both are present."""
    normalized = _normalized(name)
    if not normalized:
        return None
    with _connection(path) as connection:
        row = connection.execute(
            "SELECT latitude, longitude FROM places WHERE normalized_name=?",
            (normalized,),
        ).fetchone()
    if row is None or row["latitude"] is None or row["longitude"] is None:
        return None
    return float(row["latitude"]), float(row["longitude"])


def set_place_coordinates(
    name: str, latitude: float | None, longitude: float | None,
    path: Path | None = None,
) -> None:
    """Explicitly replace a place's coordinates; never touches image files."""
    name = " ".join(name.split())
    if not name:
        raise ValueError("empty name")
    if (latitude is None) != (longitude is None):
        raise ValueError("latitude and longitude must be set together")
    if latitude is not None and not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("invalid coordinates")
    with _connection(path) as connection:
        row = connection.execute(
            "SELECT id FROM places WHERE normalized_name=?", (_normalized(name),)
        ).fetchone()
        if row is None:
            _upsert("places", name, latitude, longitude, path)
            return
        connection.execute(
            "UPDATE places SET latitude=?, longitude=?, updated_at=? WHERE id=?",
            (latitude, longitude, datetime.now(timezone.utc).isoformat(), row["id"]),
        )


def _suggest(table: str, prefix: str, limit: int, path: Path | None) -> list[str]:
    prefix = _normalized(prefix)
    if not prefix:
        return []
    with _connection(path) as connection:
        rows = connection.execute(f"""SELECT name FROM {table} WHERE hidden=0 AND normalized_name LIKE ?
            ORDER BY CASE WHEN normalized_name LIKE ? THEN 0 ELSE 1 END, use_count DESC,
            last_used_at DESC, name COLLATE NOCASE LIMIT ?""", (f"%{prefix}%", f"{prefix}%", limit)).fetchall()
    return [row["name"] for row in rows]


def suggest_people(prefix: str, limit: int = 10, path: Path | None = None) -> list[str]:
    return _suggest("people", prefix, limit, path)


def suggest_places(prefix: str, limit: int = 10, path: Path | None = None) -> list[str]:
    return _suggest("places", prefix, limit, path)


def metadata_entries(kind: str, path: Path | None = None) -> list[dict[str, object]]:
    """Return manageable suggestion entries and their current index usage."""
    if kind not in {"people", "places"}:
        raise ValueError(kind)
    with _connection(path) as connection:
        if kind == "people":
            rows = connection.execute("""SELECT people.id,people.name,people.use_count,people.last_used_at,
                people.hidden,count(DISTINCT image_people.image_id) AS indexed_count,NULL AS latitude,NULL AS longitude
                FROM people LEFT JOIN image_people ON image_people.person_id=people.id
                GROUP BY people.id ORDER BY people.name COLLATE NOCASE""").fetchall()
        else:
            rows = connection.execute("""SELECT places.id,places.name,places.use_count,places.last_used_at,
                places.hidden,count(DISTINCT images.id) AS indexed_count,places.latitude,places.longitude
                FROM places LEFT JOIN images ON lower(images.place_name)=places.normalized_name
                GROUP BY places.id ORDER BY places.name COLLATE NOCASE""").fetchall()
    return [dict(row) for row in rows]


def indexed_metadata_paths(kind: str, name: str, path: Path | None = None) -> list[Path]:
    normalized = _normalized(name)
    with _connection(path) as connection:
        if kind == "people":
            rows = connection.execute("""SELECT images.file_path FROM images
                JOIN image_people ON image_people.image_id=images.id
                JOIN people ON people.id=image_people.person_id
                WHERE people.normalized_name=? ORDER BY images.file_path""", (normalized,)).fetchall()
        elif kind == "places":
            rows = connection.execute(
                "SELECT file_path FROM images WHERE lower(place_name)=? ORDER BY file_path",
                (normalized,),
            ).fetchall()
        else:
            raise ValueError(kind)
    return [Path(row[0]) for row in rows]


def rename_metadata_entry(
    kind: str, entry_id: int, new_name: str, *, merge: bool = False,
    path: Path | None = None,
) -> int:
    """Rename or merge an entry atomically and return the surviving id."""
    if kind not in {"people", "places"}:
        raise ValueError(kind)
    new_name = " ".join(new_name.split())
    if not new_name:
        raise ValueError("empty name")
    normalized = _normalized(new_name)
    now = datetime.now(timezone.utc).isoformat()
    with _connection(path) as connection:
        source = connection.execute(
            f"SELECT * FROM {kind} WHERE id=?", (entry_id,)
        ).fetchone()
        if source is None:
            raise KeyError(entry_id)
        target = connection.execute(
            f"SELECT * FROM {kind} WHERE normalized_name=? AND id<>?",
            (normalized, entry_id),
        ).fetchone()
        if target is not None and not merge:
            raise FileExistsError(new_name)
        if target is not None:
            target_id = int(target["id"])
            if kind == "people":
                connection.execute("""INSERT OR IGNORE INTO image_people(image_id,person_id)
                    SELECT image_id,? FROM image_people WHERE person_id=?""", (target_id, entry_id))
                connection.execute("DELETE FROM image_people WHERE person_id=?", (entry_id,))
            connection.execute(
                f"UPDATE {kind} SET use_count=use_count+?,hidden=0,updated_at=? WHERE id=?",
                (int(source["use_count"]), now, target_id),
            )
            connection.execute(f"DELETE FROM {kind} WHERE id=?", (entry_id,))
            if kind == "places":
                connection.execute(
                    "UPDATE images SET place_name=? WHERE lower(place_name)=?",
                    (target["name"], source["normalized_name"]),
                )
            return target_id
        connection.execute(
            f"UPDATE {kind} SET name=?,normalized_name=?,hidden=0,updated_at=? WHERE id=?",
            (new_name, normalized, now, entry_id),
        )
        if kind == "places":
            connection.execute(
                "UPDATE images SET place_name=? WHERE lower(place_name)=?",
                (new_name, source["normalized_name"]),
            )
        return entry_id


def hide_metadata_entry(kind: str, entry_id: int, path: Path | None = None) -> None:
    if kind not in {"people", "places"}:
        raise ValueError(kind)
    with _connection(path) as connection:
        connection.execute(f"UPDATE {kind} SET hidden=1 WHERE id=?", (entry_id,))
