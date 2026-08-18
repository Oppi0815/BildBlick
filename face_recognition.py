"""Local YuNet/SFace service used by BildBlick; no network access or uploads."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np

FACE_THRESHOLD = 0.55
FACE_MARGIN = 0.05
# Advisory only: reference quality is deliberately more tolerant than recognition.
REFERENCE_OUTLIER_WARNING_THRESHOLD = 0.35
MODEL_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets" / "models"
YUNET_MODEL = MODEL_DIR / "face_detection_yunet_2023mar.onnx"
SFACE_MODEL = MODEL_DIR / "face_recognition_sface_2021dec.onnx"


@dataclass
class DetectedFace:
    number: int
    box: tuple[int, int, int, int]
    confidence: float
    embedding: np.ndarray
    display_crop: np.ndarray | None = None


def supported(path: Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg"}


def analyze(path: Path, max_edge: int = 1600) -> tuple[list[DetectedFace], dict[str, float]]:
    if not YUNET_MODEL.is_file() or not SFACE_MODEL.is_file():
        raise ValueError("Gesichtsmodelle fehlen in assets/models.")
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Bild kann nicht gelesen werden: {path}")
    height, width = image.shape[:2]; scale = min(1.0, max_edge / max(width, height)) if max_edge else 1.0
    work = image if scale == 1 else cv2.resize(image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    detector = cv2.FaceDetectorYN.create(str(YUNET_MODEL), "", (work.shape[1], work.shape[0]), 0.85, 0.3, 5000)
    recognizer = cv2.FaceRecognizerSF.create(str(SFACE_MODEL), "")
    started = perf_counter(); _result, rows = detector.detect(work); detection = perf_counter() - started
    embedding_started = perf_counter(); faces = []
    for number, raw in enumerate(rows if rows is not None else [], 1):
        row = raw.copy(); row[:14] /= scale
        aligned = recognizer.alignCrop(image, row); embedding = recognizer.feature(aligned).astype(np.float32).reshape(-1)
        x, y, box_width, box_height = (round(value) for value in row[:4])
        margin = round(max(box_width, box_height) * 0.18)
        left, top = max(0, x-margin), max(0, y-margin)
        right, bottom = min(width, x+box_width+margin), min(height, y+box_height+margin)
        faces.append(DetectedFace(number, (x, y, box_width, box_height), float(row[14]), embedding, image[top:bottom, left:right].copy()))
    return faces, {"detection": detection, "embedding": perf_counter() - embedding_started}


def candidates(embedding: np.ndarray, references: dict[int, tuple[str, list[np.ndarray]]]) -> list[dict]:
    query = embedding.astype(np.float32).reshape(-1); results = []
    for person_id, (name, vectors) in references.items():
        scores = sorted((float(np.dot(query, vector) / (np.linalg.norm(query) * np.linalg.norm(vector))) for vector in vectors), reverse=True)
        results.append({"person_id": person_id, "name": name, "best_similarity": scores[0], "top3_mean": float(np.mean(scores[:3]))})
    return sorted(results, key=lambda item: (item["top3_mean"], item["best_similarity"]), reverse=True)


def suggest(embedding: np.ndarray, references: dict[int, tuple[str, list[np.ndarray]]], threshold: float = FACE_THRESHOLD) -> tuple[list[dict], bool]:
    ranked = candidates(embedding, references)
    uncertain = not ranked or ranked[0]["top3_mean"] < threshold or (len(ranked) > 1 and ranked[0]["top3_mean"] - ranked[1]["top3_mean"] < FACE_MARGIN)
    return ranked, uncertain
