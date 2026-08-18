from pathlib import Path
import numpy as np
from face_folder_scan import FolderScanResult, ScanFace, cluster_unknown_faces, jpeg_paths
from face_recognition import DetectedFace

def make(path, number, vector):
    return ScanFace(Path(path), DetectedFace(number, (0,0,1,1), .9, np.array(vector, dtype=np.float32)), [], True)

def test_filter_and_complete_linkage_same_image_warning(tmp_path):
    (tmp_path / "a.jpg").touch(); (tmp_path / "b.JPEG").touch(); (tmp_path / "x.png").touch()
    assert [p.name for p in jpeg_paths(tmp_path)] == ["a.jpg", "b.JPEG"]
    first, second, other = make("same.jpg", 1, [1,0]), make("same.jpg", 2, [.9,.1]), make("other.jpg", 1, [0,1])
    clusters = cluster_unknown_faces([first, second, other])
    assert len(clusters) == 2
    assert clusters[0].same_image_warning
    assert clusters[0].representative_face in clusters[0].faces


def test_folder_result_is_editable_in_memory_without_database_write(tmp_path):
    from PySide6.QtWidgets import QApplication, QPushButton
    from bildbetrachter import FolderFaceResultsDialog
    app = QApplication.instance() or QApplication([])
    known = make("known.jpg", 1, [1, 0]); known.status = "KNOWN"; known.suggested_person_id = 9; known.suggested_name = "Ingeborg"
    unknown = make("unknown.jpg", 1, [0, 1]); unknown.status = "UNKNOWN"
    result = FolderScanResult(tmp_path, False, 2, images_processed=2, faces_total=2, known_count=1, unknown_count=1, faces=[known, unknown])
    result.unknown_clusters = cluster_unknown_faces([unknown])
    dialog = FolderFaceResultsDialog(result)
    assert not dialog.confirm_known_button.isEnabled()
    assert not any("Referenz markieren" in button.text() for button in dialog.findChildren(QPushButton))
    dialog.known_faces.setCurrentRow(0)
    assert dialog.confirm_known_button.isEnabled()
    dialog._confirm_known()
    assert known.confirmed_name == "Ingeborg"
    dialog.clusters.setCurrentRow(0); dialog.cluster_faces.setCurrentRow(0); dialog._remove_cluster_faces()
    assert unknown.cluster is None
    assert "Bestätigt:" in dialog.summary.text()
    dialog.close(); app.processEvents()


def test_same_image_cluster_warning_is_shown(tmp_path):
    from PySide6.QtWidgets import QApplication
    from bildbetrachter import FolderFaceResultsDialog
    app = QApplication.instance() or QApplication([])
    first, second = make("same.jpg", 1, [1, 0]), make("same.jpg", 2, [.99, .01])
    result = FolderScanResult(tmp_path, False, 1, faces=[first, second], faces_total=2, unknown_count=2)
    result.unknown_clusters = cluster_unknown_faces([first, second])
    dialog = FolderFaceResultsDialog(result)
    assert "mehrere Gesichter" in dialog.cluster_details.text()
    dialog.close(); app.processEvents()


def test_phase_three_plan_only_contains_confirmed_deduplicated_faces(tmp_path):
    from bildbetrachter import ImageViewer
    first = make("a.jpg", 1, [1, 0]); first.confirmed_name = "Ingeborg"
    duplicate = make("a.jpg", 2, [.9, .1]); duplicate.confirmed_name = "Ingeborg"
    suggested = make("a.jpg", 3, [.8, .2]); suggested.suggested_name = "Hans"
    ignored = make("b.jpg", 1, [0, 1]); ignored.confirmed_name = "Rosa"; ignored.ignored = True
    result = FolderScanResult(tmp_path, False, 2, faces=[first, duplicate, suggested, ignored])
    assignments, references = ImageViewer._folder_face_save_plan(object(), result)
    assert assignments == {Path("a.jpg"): ["Ingeborg"]}
    assert references == [first, duplicate]


def test_phase_three_batch_continues_after_single_error_and_only_saves_explicit_reference(monkeypatch, tmp_path):
    import bildbetrachter
    from bildbetrachter import FolderFaceSaveTask
    good, bad = tmp_path / "good.jpg", tmp_path / "bad.jpg"
    calls, references, outcome = [], [], []
    def write(path, metadata):
        calls.append((path, metadata))
        if path == bad: raise RuntimeError("kaputt")
    monkeypatch.setattr(bildbetrachter, "write_manual_image_metadata", write)
    monkeypatch.setattr(bildbetrachter, "read_manual_image_metadata", lambda path: {"people": "Vorhanden"})
    monkeypatch.setattr(bildbetrachter, "upsert_person", lambda name: None)
    monkeypatch.setattr(bildbetrachter, "update_indexed_image", lambda path, data: False)
    monkeypatch.setattr(bildbetrachter, "person_id_for_name", lambda name: 7)
    monkeypatch.setattr(bildbetrachter, "face_reference_owner", lambda *args: None)
    monkeypatch.setattr(bildbetrachter, "add_face_reference", lambda *args: references.append(args) or True)
    face = make(good, 1, [1, 0]); face.confirmed_name = "Ingeborg"
    task = FolderFaceSaveTask({good: ["Ingeborg"], bad: ["Rosa"]}, [face])
    task.signals.finished.connect(lambda *args: outcome.extend(args)); task.run()
    assert len(calls) == 2 and next(metadata for path, metadata in calls if path == good)["people"] == "Vorhanden, Ingeborg"
    assert len(outcome[0]) == 1 and len(outcome[1]) == 1 and outcome[3] == 1
    assert len(references) == 1


def test_confirmed_low_quality_or_conflicting_face_still_saves_person_without_reference(monkeypatch, tmp_path):
    import bildbetrachter
    from bildbetrachter import FolderFaceSaveTask
    path = tmp_path / "face.jpg"; writes, outcome = [], []
    monkeypatch.setattr(bildbetrachter, "write_manual_image_metadata", lambda path, data: writes.append(data))
    monkeypatch.setattr(bildbetrachter, "read_manual_image_metadata", lambda path: {"people": ""})
    monkeypatch.setattr(bildbetrachter, "upsert_person", lambda name: None)
    monkeypatch.setattr(bildbetrachter, "update_indexed_image", lambda *args: False)
    monkeypatch.setattr(bildbetrachter, "person_id_for_name", lambda name: 7)
    monkeypatch.setattr(bildbetrachter, "face_reference_owner", lambda *args: "Andere Person")
    monkeypatch.setattr(bildbetrachter, "add_face_reference", lambda *args: (_ for _ in ()).throw(AssertionError("must not learn")))
    weak = make(path, 1, [1, 0]); weak.confirmed_name = "Ingeborg"; weak.face.confidence = .4
    conflict = make(path, 2, [1, 0]); conflict.confirmed_name = "Ingeborg"
    task = FolderFaceSaveTask({path: ["Ingeborg"]}, [weak, conflict]); task.signals.finished.connect(lambda *args: outcome.extend(args)); task.run()
    assert writes == [{"people": "Ingeborg"}]
    assert outcome[3:6] == [0, 1, 1]
