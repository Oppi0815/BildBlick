from pathlib import Path

from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLabel, QMessageBox

import bildbetrachter
from bildbetrachter import ImageViewer
from face_recognition import DetectedFace


def viewer(tmp_path):
    app = QApplication.instance() or QApplication([])
    result = ImageViewer(tmp_path)
    result.window.show(); app.processEvents()
    return app, result


def test_face_overlay_is_rendered_and_typed_person_is_handled(tmp_path, monkeypatch):
    app, window = viewer(tmp_path)
    from PySide6.QtGui import QImage
    window.original_image = QImage(200, 100, QImage.Format.Format_RGB32)
    window._face_overlay_boxes = [(1, 20, 10, 80, 60)]
    window._render_current_image()
    assert not window.image_label.pixmap().isNull()
    face = DetectedFace(1, (20, 10, 80, 60), 0.9, __import__("numpy").ones(128, dtype="float32"))
    monkeypatch.setattr(bildbetrachter, "suggest_people", lambda _prefix: [])
    created = []
    monkeypatch.setattr(bildbetrachter, "person_id_for_name", lambda name: created.append(name) or 7)
    monkeypatch.setattr(bildbetrachter, "add_face_reference", lambda *args: True)
    def accept_with_typed_person(dialog):
        dialog.findChildren(QComboBox)[0].setCurrentText("Testperson")
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(QDialog, "exec", accept_with_typed_person)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    window._show_face_suggestions([(face, [], True)], {})
    assert created == ["Testperson"]
    assert window.manual_metadata_fields["people"].text() == "Testperson"
    window.window.close(); app.processEvents()


def test_face_dialog_cancel_removes_overlays(tmp_path, monkeypatch):
    app, window = viewer(tmp_path)
    face = DetectedFace(1, (1, 1, 20, 20), 0.9, __import__("numpy").ones(128, dtype="float32"))
    window._face_overlay_boxes = [("Face 1", 1, 1, 20, 20)]
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    window._show_face_suggestions([(face, [], True)], {})
    assert window._face_overlay_boxes == []
    window.window.close(); app.processEvents()


def test_current_image_people_are_deduplicated_and_prioritized(tmp_path, monkeypatch):
    app, window = viewer(tmp_path)
    window.manual_metadata_fields["people"].setText("Ingeborg, Rosa, Ingeborg")
    assert window._face_people_from_metadata() == ["Ingeborg", "Rosa"]
    window._face_image_people = window._face_people_from_metadata()
    face = DetectedFace(1, (1, 1, 20, 20), 0.9, __import__("numpy").ones(128, dtype="float32"))
    monkeypatch.setattr(bildbetrachter, "suggest_people", lambda _prefix: ["Rosa", "Hans"])
    captured = []
    def reject(dialog):
        captured.extend(combo.itemText(index) for combo in dialog.findChildren(QComboBox) for index in range(combo.count()))
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(QDialog, "exec", reject)
    window._show_face_suggestions([(face, [], True)], {})
    assert captured[:2] == ["Unbekannt", "Ingeborg"]
    assert "Rosa" in captured and "Hans" in captured
    window.window.close(); app.processEvents()


def test_overlay_only_mode_labels_known_and_uncertain_faces_without_dialog(tmp_path):
    from bildbetrachter import FaceOverlaySession
    app, window = viewer(tmp_path)
    image = tmp_path / "current.jpg"; image.touch()
    window.current_image = image; window._face_overlay_mode = True
    known = DetectedFace(1, (1, 2, 20, 20), .9, __import__("numpy").ones(128, dtype="float32"))
    uncertain = DetectedFace(2, (30, 2, 20, 20), .9, __import__("numpy").ones(128, dtype="float32"))
    session = FaceOverlaySession([(known, [{"name": "Ingeborg"}], False), (uncertain, [{"name": "Rosa"}], True)])
    window._show_face_overlay_results(image, session)
    assert [box[0] for box in window._face_overlay_boxes] == ["Ingeborg?", "Face 2"]
    window._set_face_overlay_mode(False)
    assert window._face_overlay_boxes == [] and window._face_overlay_cache == {}
    window.window.close(); app.processEvents()


def test_overlay_suggestions_are_confirmed_sequentially_without_reanalysis(tmp_path, monkeypatch):
    from bildbetrachter import FaceOverlaySession
    app, window = viewer(tmp_path)
    image = tmp_path / "group.jpg"; image.touch(); window.current_image = image; window._face_overlay_mode = True
    window.manual_metadata_fields["people"].setText("Ingeborg")
    faces = [DetectedFace(index, (index * 10, 1, 8, 8), .9, __import__("numpy").ones(128, dtype="float32")) for index in range(1, 5)]
    session = FaceOverlaySession([
        (faces[0], [{"name": "Ingeborg"}], False),
        (faces[1], [{"name": "Hans"}], False),
        (faces[2], [], True),
        (faces[3], [{"name": "Rosa"}], False),
    ])
    window._face_overlay_cache[image] = session
    saved = []; monkeypatch.setattr(window, "_capture_manual_metadata", lambda: saved.append(window.manual_metadata_fields["people"].text()))
    monkeypatch.setattr(bildbetrachter, "person_id_for_name", lambda _name: 7); monkeypatch.setattr(bildbetrachter, "face_reference_owner", lambda *_: None); monkeypatch.setattr(bildbetrachter, "add_face_reference", lambda *_: True)
    window._show_face_overlay_results(image, session)
    assert [item[0] for item in window._face_overlay_boxes] == ["Ingeborg", "Hans?", "Face 3", "Rosa?"]
    assert "Face 2 – Hans?" in window.face_suggestion_label.text() and "1/2" in window.face_suggestion_label.text()
    window._confirm_current_face_suggestion()
    assert [item[0] for item in window._face_overlay_boxes][1] == "Hans"
    assert "Face 4 – Rosa?" in window.face_suggestion_label.text() and saved == ["Ingeborg, Hans"]
    window._reject_current_face_suggestion()
    assert [item[0] for item in window._face_overlay_boxes][3] == "Face 4"
    assert not window.face_suggestion_widget.isVisible()
    window.window.close(); app.processEvents()


def test_single_face_single_image_person_is_a_non_biometric_hint(tmp_path, monkeypatch):
    from bildbetrachter import FACE_SUGGESTION_IMAGE_METADATA, FaceOverlaySession
    app, window = viewer(tmp_path)
    image = tmp_path / "horst.jpg"; image.touch()
    window.current_image = image; window._face_overlay_mode = True
    window.manual_metadata_fields["people"].setText("Horst")
    face = DetectedFace(1, (1, 1, 8, 8), .9, __import__("numpy").ones(128, dtype="float32"))
    session = FaceOverlaySession([(face, [], True)])
    window._face_overlay_cache[image] = session
    window._show_face_overlay_results(image, session)
    assert [item[0] for item in window._face_overlay_boxes] == ["Horst?"]
    assert "Face 1 – Horst?" in window.face_suggestion_label.text()
    assert session.pending_sources[1] == FACE_SUGGESTION_IMAGE_METADATA
    saved = []; learned = []
    monkeypatch.setattr(window, "_capture_manual_metadata", lambda: saved.append(True))
    monkeypatch.setattr(bildbetrachter, "person_id_for_name", lambda _name: 7)
    monkeypatch.setattr(bildbetrachter, "face_reference_owner", lambda *_: None)
    monkeypatch.setattr(bildbetrachter, "add_face_reference", lambda *args: learned.append(args) or True)
    window._confirm_current_face_suggestion()
    assert [item[0] for item in window._face_overlay_boxes] == ["Horst"]
    assert window.manual_metadata_fields["people"].text() == "Horst"
    assert learned and saved
    window.window.close(); app.processEvents()


def test_rejecting_metadata_hint_keeps_image_people_unchanged(tmp_path):
    from bildbetrachter import FaceOverlaySession
    app, window = viewer(tmp_path)
    image = tmp_path / "horst.jpg"; image.touch()
    window.current_image = image; window._face_overlay_mode = True
    window.manual_metadata_fields["people"].setText("Horst")
    face = DetectedFace(1, (1, 1, 8, 8), .9, __import__("numpy").ones(128, dtype="float32"))
    session = FaceOverlaySession([(face, [], True)])
    window._face_overlay_cache[image] = session
    window._show_face_overlay_results(image, session)
    window._reject_current_face_suggestion()
    assert [item[0] for item in window._face_overlay_boxes] == ["Face 1"]
    assert window.manual_metadata_fields["people"].text() == "Horst"
    window.window.close(); app.processEvents()


def test_image_people_never_assign_faces_in_a_group_photo(tmp_path):
    from bildbetrachter import FaceOverlaySession
    app, window = viewer(tmp_path)
    image = tmp_path / "group.jpg"; image.touch()
    window.current_image = image; window._face_overlay_mode = True
    window.manual_metadata_fields["people"].setText("Horst")
    faces = [DetectedFace(number, (number, 1, 8, 8), .9, __import__("numpy").ones(128, dtype="float32")) for number in (1, 2)]
    session = FaceOverlaySession([(face, [], True) for face in faces])
    window._show_face_overlay_results(image, session)
    assert [item[0] for item in window._face_overlay_boxes] == ["Face 1", "Face 2"]
    assert not session.pending
    window.window.close(); app.processEvents()


def test_safe_sface_match_for_an_image_person_is_confirmed_without_question(tmp_path):
    from bildbetrachter import FACE_SUGGESTION_CONFIRMED, FaceOverlaySession
    app, window = viewer(tmp_path)
    image = tmp_path / "horst.jpg"; image.touch()
    window.current_image = image; window._face_overlay_mode = True
    window.manual_metadata_fields["people"].setText("Horst")
    face = DetectedFace(1, (1, 1, 8, 8), .9, __import__("numpy").ones(128, dtype="float32"))
    session = FaceOverlaySession([(face, [{"name": "Horst"}], False)])
    window._show_face_overlay_results(image, session)
    assert [item[0] for item in window._face_overlay_boxes] == ["Horst"]
    assert not session.pending and session.suggestion_sources[1] == FACE_SUGGESTION_CONFIRMED
    window.window.close(); app.processEvents()


def test_single_face_dialog_marks_metadata_hint_without_similarity(tmp_path, monkeypatch):
    app, window = viewer(tmp_path)
    window._face_image_people = ["Horst"]
    face = DetectedFace(1, (1, 1, 8, 8), .9, __import__("numpy").ones(128, dtype="float32"))
    observed = {}
    def reject(dialog):
        observed["labels"] = [label.text() for label in dialog.findChildren(QLabel)]
        observed["selection"] = dialog.findChildren(QComboBox)[0].currentText()
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(QDialog, "exec", reject)
    window._show_face_suggestions([(face, [], True)], {})
    assert "Horst" in observed["labels"]
    assert "Vorschlag aus Bildinformationen" in observed["labels"]
    assert observed["selection"] == "Horst"
    window.window.close(); app.processEvents()


def test_saved_jpeg_people_drive_fresh_overlay_after_stale_unknown_cache(tmp_path, monkeypatch):
    """Regression for the real save → green-overlay flow on an unindexed JPG."""
    from PIL import Image
    from bildbetrachter import FACE_SUGGESTION_IMAGE_METADATA, FaceOverlaySession
    app, window = viewer(tmp_path)
    image = tmp_path / "unindexed-horst.jpg"
    Image.new("RGB", (40, 30), "white").save(image)
    window.current_image = image
    window._refresh_manual_metadata_editor(image)
    window.manual_metadata_fields["people"].setText("Horst")
    face = DetectedFace(1, (1, 1, 8, 8), .9, __import__("numpy").ones(128, dtype="float32"))
    # This models the first (pre-save) recognition pass.  It must not be used
    # after PersonInImage has gone through the normal ExifTool save path.
    window._face_overlay_cache[image] = FaceOverlaySession([(face, [{"name": "Fremd", "top3_mean": .2}], True)])
    monkeypatch.setattr(window, "_ensure_face_overlay_for_current_image", lambda: None)
    window._capture_manual_metadata()
    assert bildbetrachter.read_manual_image_metadata(image)["people"] == "Horst"
    assert image not in window._face_overlay_cache

    window._face_overlay_mode = True
    # This is the normal completed-worker entry point, with an insufficient
    # SFace candidate just as the real image produced.
    window._face_overlay_finished([(face, [{"name": "Fremd", "top3_mean": .2}], True)], image)
    session = window._face_overlay_cache[image]
    assert [item[0] for item in window._face_overlay_boxes] == ["Horst?"]
    assert "Face 1 – Horst?" in window.face_suggestion_label.text()
    assert session.pending_sources[1] == FACE_SUGGESTION_IMAGE_METADATA

    window._face_image_people = window._face_people_from_metadata()
    observed = {}
    def reject(dialog):
        observed["labels"] = [label.text() for label in dialog.findChildren(QLabel)]
        observed["selection"] = dialog.findChildren(QComboBox)[0].currentText()
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(QDialog, "exec", reject)
    window._show_face_suggestions([(face, [{"name": "Fremd", "top3_mean": .2}], True)], {})
    assert "Vorschlag aus Bildinformationen" in observed["labels"]
    assert observed["selection"] == "Horst"
    window.window.close(); app.processEvents()


def test_saved_jpeg_people_hint_is_identical_for_an_indexed_image(tmp_path, monkeypatch):
    """Index presence is irrelevant; the overlay reads persisted JPG metadata."""
    from PIL import Image
    from image_index import index_folder
    from bildbetrachter import FaceOverlaySession
    app, window = viewer(tmp_path)
    image = tmp_path / "indexed-horst.jpg"
    Image.new("RGB", (40, 30), "white").save(image)
    window.current_image = image; window._refresh_manual_metadata_editor(image)
    window.manual_metadata_fields["people"].setText("Horst")
    monkeypatch.setattr(window, "_ensure_face_overlay_for_current_image", lambda: None)
    window._capture_manual_metadata()
    assert index_folder(image.parent, False, bildbetrachter.read_manual_image_metadata, path=tmp_path / "index.db") == 1
    face = DetectedFace(1, (1, 1, 8, 8), .9, __import__("numpy").ones(128, dtype="float32"))
    window._face_overlay_mode = True
    window._show_face_overlay_results(image, FaceOverlaySession([(face, [], True)]))
    assert [item[0] for item in window._face_overlay_boxes] == ["Horst?"]
    window.window.close(); app.processEvents()


def test_red_workflow_opens_dialog_from_cached_overlay_results(tmp_path, monkeypatch):
    from bildbetrachter import FaceOverlaySession
    app, window = viewer(tmp_path)
    image = tmp_path / "cached.jpg"; image.touch(); window.current_image = image
    face = DetectedFace(1, (1, 1, 8, 8), .9, __import__("numpy").ones(128, dtype="float32"))
    window._face_overlay_cache[image] = FaceOverlaySession([(face, [{"name": "Ingeborg", "best_similarity": .9, "top3_mean": .9}], False)])
    monkeypatch.setattr(window, "_selected_image_paths", lambda: [image])
    opened = []; monkeypatch.setattr(window, "_show_face_suggestions", lambda results, timings: opened.append((results, timings)))
    window._start_face_detection()
    assert len(opened) == 1 and opened[0][0][0][0] is face
    window.window.close(); app.processEvents()


def test_red_workflow_reports_zero_faces(tmp_path, monkeypatch):
    app, window = viewer(tmp_path)
    image = tmp_path / "empty.jpg"; image.touch(); window.current_image = image; window._face_generation += 1
    message = []; monkeypatch.setattr(QMessageBox, "information", lambda *_args: message.append(_args[2]))
    window._face_detection_finished(window._face_generation, [], {}, image)
    assert message == ["In diesem Bild wurden keine Gesichter erkannt."]
    window.window.close(); app.processEvents()
