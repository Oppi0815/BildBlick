"""In-memory, local folder-face scan primitives; no metadata or DB writes."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, Signal

from face_recognition import DetectedFace, analyze, suggest, supported
from metadata_database import face_reference_vectors


@dataclass
class ScanFace:
    path: Path
    face: DetectedFace
    candidates: list[dict]
    uncertain: bool
    cluster: int | None = None

    status: str = "UNKNOWN"
    best_similarity: float | None = None
    top3_mean: float | None = None
    margin: float | None = None
    # These fields are deliberately only session state.  Phase 2 may change
    # them freely; Phase 3 is the sole place that persists assignments.
    suggested_person_id: int | None = None
    suggested_name: str | None = None
    confirmed_person_id: int | None = None
    confirmed_name: str | None = None
    ignored: bool = False
    reference_requested: bool = False


@dataclass
class FolderScanResult:
    root_folder: Path; recursive: bool; images_total: int
    images_processed: int = 0; faces_total: int = 0; known_count: int = 0; uncertain_count: int = 0; unknown_count: int = 0
    faces: list[ScanFace] = field(default_factory=list); errors: list[str] = field(default_factory=list); unknown_clusters: list[UnknownFaceCluster] = field(default_factory=list)
    discovery_time: float = 0; detection_time: float = 0; embedding_time: float = 0; recognition_time: float = 0; clustering_time: float = 0; total_time: float = 0

    @property
    def known_faces(self): return [face for face in self.faces if face.status == "KNOWN"]
    @property
    def uncertain_faces(self): return [face for face in self.faces if face.status == "UNCERTAIN"]
    @property
    def unknown_faces(self): return [face for face in self.faces if face.status == "UNKNOWN"]


@dataclass
class UnknownFaceCluster:
    cluster_id: int; faces: list[ScanFace]; mean_similarity: float | None; min_similarity: float | None; nearest_external_similarity: float | None; representative_face: ScanFace; same_image_warning: bool; same_image_paths: list[Path]


UNKNOWN_CLUSTER_THRESHOLD = 0.55


def cluster_unknown_faces(faces: list[ScanFace], threshold: float = UNKNOWN_CLUSTER_THRESHOLD) -> list[UnknownFaceCluster]:
    import numpy as np
    groups = [[face] for face in faces]
    score = lambda a, b: float(np.dot(a.face.embedding, b.face.embedding) / (np.linalg.norm(a.face.embedding) * np.linalg.norm(b.face.embedding)))
    while True:
        choices = [(min(score(a, b) for a in groups[left] for b in groups[right]), left, right) for left in range(len(groups)) for right in range(left + 1, len(groups))]
        choices = [item for item in choices if item[0] >= threshold]
        if not choices: break
        _value, left, right = max(choices); groups[left].extend(groups[right]); del groups[right]
    result = []
    for ident, group in enumerate(sorted(groups, key=len, reverse=True), 1):
        pairs = [score(a,b) for index,a in enumerate(group) for b in group[index+1:]]
        external = [score(a,b) for a in group for b in faces if b not in group]
        centroid = np.mean(np.vstack([face.face.embedding for face in group]), axis=0)
        representative = max(group, key=lambda face: float(np.dot(face.face.embedding, centroid)/(np.linalg.norm(face.face.embedding)*np.linalg.norm(centroid))))
        paths = sorted({face.path for face in group if sum(item.path == face.path for item in group) > 1}, key=str)
        for face in group: face.cluster = ident
        result.append(UnknownFaceCluster(ident, group, float(np.mean(pairs)) if pairs else None, min(pairs) if pairs else None, max(external) if external else None, representative, bool(paths), paths))
    return result


class FolderScanSignals(QObject):
    progress = Signal(str, int, int, str, int, int, int, int, int)
    finished = Signal(object); cancelled = Signal(object); error = Signal(str)


class FolderScanTask(QRunnable):
    def __init__(self, folder: Path, recursive: bool = False):
        super().__init__(); self.folder = folder; self.recursive = recursive; self.signals = FolderScanSignals(); self._cancelled = False
    def cancel(self): self._cancelled = True
    def run(self):
        try:
            self.signals.progress.emit("DISCOVERY", 0, 0, "", 0, 0, 0, 0, 0)
            result = scan_folder(
                self.folder, self.recursive, cancelled=lambda: self._cancelled,
                progress=lambda current, total, path, state: self.signals.progress.emit(
                    "ANALYZE", current, total, str(path), state.faces_total,
                    state.known_count, state.uncertain_count, state.unknown_count,
                    len(state.errors),
                ),
            )
            self.signals.progress.emit("CLUSTER", result.images_processed, result.images_total, "", result.faces_total, result.known_count, result.uncertain_count, result.unknown_count, len(result.errors))
            (self.signals.cancelled if self._cancelled else self.signals.finished).emit(result)
        except Exception as error: self.signals.error.emit(str(error))


def jpeg_paths(folder: Path, recursive: bool = False) -> list[Path]:
    iterator = folder.rglob("*") if recursive else folder.glob("*")
    return sorted((path for path in iterator if path.is_file() and supported(path)), key=lambda path: str(path).casefold())


def scan_folder(folder: Path, recursive: bool = False, progress: Callable[[int, int, Path, FolderScanResult], None] | None = None, cancelled: Callable[[], bool] | None = None) -> FolderScanResult:
    import numpy as np
    started = perf_counter(); discovery = perf_counter(); paths = jpeg_paths(folder, recursive); result = FolderScanResult(folder, recursive, len(paths)); result.discovery_time = perf_counter()-discovery
    refs = {pid: (name, [np.frombuffer(blob, dtype=np.float32).copy() for blob in blobs]) for pid, (name, blobs) in face_reference_vectors().items()}
    for number, path in enumerate(paths, 1):
        if cancelled and cancelled(): break
        try: faces, timings = analyze(path)
        except Exception as error:
            result.errors.append(f"{path}: {error}"); result.images_processed += 1
            if progress: progress(number, len(paths), path, result)
            continue
        result.detection_time += timings["detection"]; result.embedding_time += timings["embedding"]
        for face in faces:
            started_rec = perf_counter(); candidates, uncertain = suggest(face.embedding, refs); result.recognition_time += perf_counter()-started_rec
            best = candidates[0] if candidates else None; margin = None if len(candidates)<2 else best["top3_mean"]-candidates[1]["top3_mean"]
            status = "KNOWN" if best and not uncertain else "UNCERTAIN" if best else "UNKNOWN"
            scan = ScanFace(
                path, face, candidates, uncertain, status=status,
                best_similarity=best and best["best_similarity"],
                top3_mean=best and best["top3_mean"], margin=margin,
                suggested_person_id=best and best["person_id"],
                suggested_name=best and best["name"],
            ); result.faces.append(scan); result.faces_total += 1
            if status == "KNOWN": result.known_count += 1
            elif status == "UNCERTAIN": result.uncertain_count += 1
            else: result.unknown_count += 1
        result.images_processed += 1
        if progress: progress(number, len(paths), path, result)
    cluster_started = perf_counter(); result.unknown_clusters = cluster_unknown_faces(result.unknown_faces); result.clustering_time = perf_counter()-cluster_started
    result.total_time = perf_counter()-started
    return result
