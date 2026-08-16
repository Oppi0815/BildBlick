"""Local JPG metadata index and search helpers."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from metadata_database import _connection, _normalized

JPEG_EXTENSIONS = {".jpg", ".jpeg"}

def _now() -> str: return datetime.now(timezone.utc).isoformat()

def _gps_values(text: str) -> tuple[float | None, float | None]:
    try:
        latitude, longitude = (float(value.strip()) for value in text.split(","))
        return latitude, longitude
    except (TypeError, ValueError):
        return None, None


def _write_image(connection, file_path: Path, metadata: dict[str, str]) -> None:
    stat = file_path.stat(); value = str(file_path)
    latitude, longitude = _gps_values(metadata.get("gps", ""))
    connection.execute("INSERT INTO images(file_path,file_name,directory_path,modified_time,file_size,comment,place_name,latitude,longitude,indexed_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(file_path) DO UPDATE SET file_name=excluded.file_name,directory_path=excluded.directory_path,modified_time=excluded.modified_time,file_size=excluded.file_size,comment=excluded.comment,place_name=excluded.place_name,latitude=excluded.latitude,longitude=excluded.longitude,indexed_at=excluded.indexed_at", (value,file_path.name,str(file_path.parent),stat.st_mtime,stat.st_size,metadata.get('comment',''),metadata.get('place',''),latitude,longitude,_now()))
    image_id = connection.execute("SELECT id FROM images WHERE file_path=?", (value,)).fetchone()[0]
    connection.execute("DELETE FROM image_people WHERE image_id=?", (image_id,))
    for person in {item.strip() for item in metadata.get('people','').split(',') if item.strip()}:
        connection.execute("INSERT INTO people(name,normalized_name,use_count,created_at,updated_at,last_used_at) VALUES(?,?,0,?,?,?) ON CONFLICT(normalized_name) DO NOTHING", (person, _normalized(person), _now(), _now(), _now()))
        person_id = connection.execute("SELECT id FROM people WHERE normalized_name=?", (_normalized(person),)).fetchone()[0]
        connection.execute("INSERT OR IGNORE INTO image_people VALUES(?,?)", (image_id, person_id))


def index_folder(folder: Path, recursive: bool, read_metadata, path: Path | None = None,
                 progress: Callable[[int, int], None] | None = None,
                 cancelled: Callable[[], bool] | None = None) -> int:
    folder = folder.resolve()
    pattern = "**/*" if recursive else "*"
    files = [item for item in folder.glob(pattern) if item.is_file() and item.suffix.lower() in JPEG_EXTENSIONS]
    with _connection(path) as connection:
        connection.execute("INSERT INTO indexed_folders(folder_path, recursive, added_at, last_scan_at) VALUES(?, ?, ?, NULL) ON CONFLICT(folder_path) DO UPDATE SET recursive=excluded.recursive", (str(folder), recursive, _now()))
        known = {row[0] for row in connection.execute("SELECT file_path FROM images WHERE directory_path=? OR directory_path LIKE ?", (str(folder), str(folder) + "/%"))}
        total = len(files)
        if progress: progress(0, total)
        for current, file_path in enumerate(files, 1):
            if cancelled and cancelled():
                break
            stat = file_path.stat(); value = str(file_path)
            row = connection.execute("SELECT modified_time, file_size FROM images WHERE file_path=?", (value,)).fetchone()
            known.discard(value)
            if not row or row[0] != stat.st_mtime or row[1] != stat.st_size:
                _write_image(connection, file_path, read_metadata(file_path))
            if progress: progress(current, total)
        if not (cancelled and cancelled()):
            for stale in known: connection.execute("DELETE FROM images WHERE file_path=?", (stale,))
            connection.execute("UPDATE indexed_folders SET last_scan_at=? WHERE folder_path=?", (_now(), str(folder)))
    return total


def indexed_folders(path: Path | None = None) -> list[tuple[Path, bool, str]]:
    with _connection(path) as connection:
        return [(Path(row[0]), bool(row[1]), row[2] or "") for row in connection.execute("SELECT folder_path,recursive,last_scan_at FROM indexed_folders ORDER BY folder_path")]


def remove_indexed_folder(folder: Path, path: Path | None = None) -> None:
    folder = folder.resolve(); prefix = str(folder) + "/%"
    with _connection(path) as connection:
        connection.execute("DELETE FROM images WHERE directory_path=? OR directory_path LIKE ?", (str(folder), prefix))
        connection.execute("DELETE FROM indexed_folders WHERE folder_path=?", (str(folder),))


def update_indexed_image(file_path: Path, metadata: dict[str, str], path: Path | None = None) -> bool:
    with _connection(path) as connection:
        if connection.execute("SELECT 1 FROM images WHERE file_path=?", (str(file_path),)).fetchone() is None:
            return False
        _write_image(connection, file_path, metadata)
    return True

def search_images(person: str = '', place: str = '', comment: str = '', path: Path | None = None) -> list[Path]:
    if not any((person.strip(), place.strip(), comment.strip())): return []
    sql = "SELECT DISTINCT images.file_path FROM images"
    clauses=[]; values=[]
    if person.strip():
        sql += " JOIN image_people ON image_people.image_id=images.id JOIN people ON people.id=image_people.person_id"; clauses.append("people.normalized_name=?"); values.append(_normalized(person))
    if place.strip(): clauses.append("lower(images.place_name)=?"); values.append(_normalized(place))
    if comment.strip(): clauses.append("lower(images.comment) LIKE ?"); values.append('%' + comment.casefold() + '%')
    with _connection(path) as connection:
        return [Path(row[0]) for row in connection.execute(sql + " WHERE " + " AND ".join(clauses) + " ORDER BY images.file_name", values) if Path(row[0]).is_file()]
