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
    place = " ".join(metadata.get("place", "").split())
    if place:
        connection.execute("""INSERT INTO places(name,normalized_name,use_count,created_at,updated_at,last_used_at)
            VALUES(?,?,0,?,?,?) ON CONFLICT(normalized_name) DO NOTHING""",
            (place, _normalized(place), _now(), _now(), _now()))


def _is_descendant(folder: Path, ancestor: Path) -> bool:
    """Return whether *folder* is below, but not equal to, *ancestor*."""
    try:
        folder.relative_to(ancestor)
    except ValueError:
        return False
    return folder != ancestor


def _remove_redundant_indexed_folders(connection) -> None:
    """Remove only folder registrations already covered by recursive roots."""
    entries = [
        (Path(row["folder_path"]), bool(row["recursive"]))
        for row in connection.execute("SELECT folder_path, recursive FROM indexed_folders")
    ]
    redundant = {
        child
        for child, _child_recursive in entries
        if any(parent_recursive and _is_descendant(child, parent) for parent, parent_recursive in entries)
    }
    for folder in redundant:
        connection.execute("DELETE FROM indexed_folders WHERE folder_path=?", (str(folder),))


def register_indexed_folder(folder: Path, recursive: bool, path: Path | None = None) -> Path | None:
    """Persist a deliberately selected folder before its image scan starts.

    Keeping this as a separate transaction is intentional: an empty directory
    (and a scan that is later cancelled) is still a folder the user chose to
    keep in the image index.
    """
    folder = folder.resolve()
    with _connection(path) as connection:
        _remove_redundant_indexed_folders(connection)
        existing = [
            (Path(row["folder_path"]), bool(row["recursive"]))
            for row in connection.execute("SELECT folder_path, recursive FROM indexed_folders")
        ]
        if any(is_recursive and _is_descendant(folder, parent) for parent, is_recursive in existing):
            return None
        connection.execute(
            "INSERT INTO indexed_folders(folder_path, recursive, added_at, last_scan_at) "
            "VALUES(?, ?, ?, NULL) "
            "ON CONFLICT(folder_path) DO UPDATE SET recursive=excluded.recursive",
            (str(folder), recursive, _now()),
        )
        if recursive:
            _remove_redundant_indexed_folders(connection)
    return folder


def index_folder(folder: Path, recursive: bool, read_metadata, path: Path | None = None,
                 progress: Callable[[int, int], None] | None = None,
                 cancelled: Callable[[], bool] | None = None) -> int:
    folder = register_indexed_folder(folder, recursive, path)
    if folder is None:
        if progress:
            progress(0, 0)
        return 0
    pattern = "**/*" if recursive else "*"
    files = [item for item in folder.glob(pattern) if item.is_file() and item.suffix.lower() in JPEG_EXTENSIONS]
    with _connection(path) as connection:
        if recursive:
            known = {row[0] for row in connection.execute(
                "SELECT file_path FROM images WHERE directory_path=? OR directory_path LIKE ?",
                (str(folder), str(folder) + "/%"),
            )}
        else:
            known = {row[0] for row in connection.execute(
                "SELECT file_path FROM images WHERE directory_path=?", (str(folder),)
            )}
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
        _remove_redundant_indexed_folders(connection)
        return [(Path(row[0]), bool(row[1]), row[2] or "") for row in connection.execute("SELECT folder_path,recursive,last_scan_at FROM indexed_folders ORDER BY folder_path")]


def refresh_indexed_metadata(
    read_metadata, path: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    folders: list[tuple[Path, bool]] | None = None,
) -> int:
    """Re-read metadata for exactly the folders already tracked by the index.

    This intentionally never calls the suggestion upsert helpers: imported
    metadata may create missing names, but must not increase user input counts.
    """
    folders = folders if folders is not None else indexed_folders(path)
    file_sets: list[tuple[Path, bool, list[Path]]] = []
    all_files: dict[str, Path] = {}
    for folder, recursive, _last_scan in folders:
        if not folder.is_dir():
            file_sets.append((folder, recursive, []))
            continue
        pattern = "**/*" if recursive else "*"
        files = [item for item in folder.glob(pattern) if item.is_file() and item.suffix.lower() in JPEG_EXTENSIONS]
        file_sets.append((folder, recursive, files))
        for file_path in files:
            all_files.setdefault(str(file_path), file_path)
    total = len(all_files)
    if progress:
        progress(0, total)
    completed = 0
    with _connection(path) as connection:
        for file_path in all_files.values():
            if cancelled and cancelled():
                break
            _write_image(connection, file_path, read_metadata(file_path))
            completed += 1
            if progress:
                progress(completed, total)
        was_cancelled = bool(cancelled and cancelled())
        if not was_cancelled:
            for folder, recursive, files in file_sets:
                prefix = str(folder) + "/%"
                if recursive:
                    known = {row[0] for row in connection.execute(
                        "SELECT file_path FROM images WHERE directory_path=? OR directory_path LIKE ?",
                        (str(folder), prefix),
                    )}
                else:
                    known = {row[0] for row in connection.execute(
                        "SELECT file_path FROM images WHERE directory_path=?", (str(folder),)
                    )}
                current = {str(file_path) for file_path in files}
                for stale in known - current:
                    connection.execute("DELETE FROM images WHERE file_path=?", (stale,))
                connection.execute(
                    "UPDATE indexed_folders SET last_scan_at=? WHERE folder_path=?",
                    (_now(), str(folder)),
                )
    return completed


def remove_indexed_folder(folder: Path, path: Path | None = None) -> None:
    folder = folder.resolve(); prefix = str(folder) + "/%"
    with _connection(path) as connection:
        row = connection.execute("SELECT recursive FROM indexed_folders WHERE folder_path=?", (str(folder),)).fetchone()
        if row and row[0]:
            connection.execute("DELETE FROM images WHERE directory_path=? OR directory_path LIKE ?", (str(folder), prefix))
        else:
            connection.execute("DELETE FROM images WHERE directory_path=?", (str(folder),))
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
