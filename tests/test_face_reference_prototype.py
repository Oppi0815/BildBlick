from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / "experiments"))
from face_reference_test import candidates, connect, person_id, references, store_reference  # noqa: E402


def face(vector: list[float], image: str = "a.jpg", number: int = 1):
    return SimpleNamespace(embedding=np.asarray(vector, dtype=np.float32), image=Path(image), number=number, confidence=0.9, box=(0, 0, 500, 500))


def test_float32_roundtrip_multiple_references_and_duplicate(tmp_path):
    db = connect(tmp_path / "faces.db")
    person = person_id(db, "Ingeborg")
    first = face([1.0] + [0.0] * 127)
    second = face([0.9, 0.1] + [0.0] * 126, "b.jpg")
    assert store_reference(db, person, first)
    assert not store_reference(db, person, first)
    assert store_reference(db, person, second)
    loaded = references(db)
    assert len(loaded[person][1]) == 2
    assert loaded[person][1][0].dtype == np.float32
    assert np.array_equal(loaded[person][1][0], first.embedding)
    db.close()


def test_scores_top3_margin_and_unknown(tmp_path):
    db = connect(tmp_path / "faces.db")
    alice = person_id(db, "Alice")
    bob = person_id(db, "Bob")
    store_reference(db, alice, face([1.0] + [0.0] * 127, "a.jpg"))
    store_reference(db, alice, face([0.98, 0.02] + [0.0] * 126, "a2.jpg"))
    store_reference(db, bob, face([0.0, 1.0] + [0.0] * 126, "b.jpg"))
    ranked = candidates(face([1.0] + [0.0] * 127, "query.jpg"), references(db))
    assert ranked[0]["name"] == "Alice"
    assert ranked[0]["best_similarity"] > ranked[1]["best_similarity"]
    assert ranked[0]["top3_mean"] > 0.9
    assert ranked[0]["top3_mean"] - ranked[1]["top3_mean"] > 0.9
    db.close()
