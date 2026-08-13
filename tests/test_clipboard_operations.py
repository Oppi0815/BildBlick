from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from bildbetrachter import CLIPBOARD_OPERATION_MIME_TYPE, ImageViewer


def _viewer(directory: Path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        "bildbetrachter.QSettings",
        lambda *_args: QSettings(
            str(directory.parent / "viewer.ini"), QSettings.Format.IniFormat
        ),
    )
    viewer = ImageViewer(directory)
    viewer.window.show()
    for _ in range(100):
        application.processEvents()
        QTest.qWait(5)
        if viewer._directory_iterator is None and viewer.thumbnail_list.count():
            break
    return application, viewer


def _image(directory: Path, name="bild.jpg") -> Path:
    path = directory / name
    image = QImage(8, 6, QImage.Format.Format_RGB32)
    image.fill(0xFF336699)
    assert image.save(str(path))
    return path


def _select_first(viewer, application):
    viewer.thumbnail_list.setCurrentRow(0)
    application.processEvents()
    assert viewer.thumbnail_list.selectedItems()


def _close(viewer, application):
    QApplication.clipboard().clear()
    viewer.window.close()
    application.processEvents()


def test_copy_writes_local_file_urls_and_enables_paste(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    image_path = _image(source)
    application, viewer = _viewer(source, monkeypatch)
    try:
        _select_first(viewer, application)
        viewer.copy_image_action.trigger()

        mime_data = QApplication.clipboard().mimeData()
        assert mime_data.hasUrls()
        assert mime_data.hasFormat(CLIPBOARD_OPERATION_MIME_TYPE)
        assert [url.toLocalFile() for url in mime_data.urls()] == [str(image_path)]
        assert viewer.paste_image_action.isEnabled()
    finally:
        _close(viewer, application)


def test_cut_writes_local_file_urls_and_enables_paste(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    image_path = _image(source)
    application, viewer = _viewer(source, monkeypatch)
    try:
        _select_first(viewer, application)
        viewer.cut_image_action.trigger()

        mime_data = QApplication.clipboard().mimeData()
        assert mime_data.hasUrls()
        assert mime_data.hasFormat(CLIPBOARD_OPERATION_MIME_TYPE)
        assert [url.toLocalFile() for url in mime_data.urls()] == [str(image_path)]
        assert viewer._clipboard_files()[1] == "cut"
        assert viewer.paste_image_action.isEnabled()
    finally:
        _close(viewer, application)


def test_copy_and_paste_copies_file_to_current_target_directory(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir(); target.mkdir()
    image_path = _image(source)
    application, viewer = _viewer(source, monkeypatch)
    try:
        _select_first(viewer, application)
        viewer.copy_image_action.trigger()
        viewer._show_directory(target)
        application.processEvents()
        viewer._paste_image_from_clipboard()

        assert image_path.exists()
        assert (target / image_path.name).is_file()
    finally:
        _close(viewer, application)


def test_cut_and_paste_moves_file_and_resets_cut_state(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir(); target.mkdir()
    image_path = _image(source)
    application, viewer = _viewer(source, monkeypatch)
    try:
        _select_first(viewer, application)
        viewer.cut_image_action.trigger()
        viewer._show_directory(target)
        application.processEvents()
        viewer._paste_image_from_clipboard()

        assert not image_path.exists()
        assert (target / image_path.name).is_file()
        assert viewer._clipboard_operation is None
        mime_data = QApplication.clipboard().mimeData()
        assert mime_data is None or not mime_data.hasUrls()
        assert not viewer.paste_image_action.isEnabled()
    finally:
        _close(viewer, application)


def test_copy_and_cut_actions_remain_connected_after_language_switch(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    image_path = _image(source)
    application, viewer = _viewer(source, monkeypatch)
    try:
        _select_first(viewer, application)
        copy_action = viewer.copy_image_action
        cut_action = viewer.cut_image_action
        viewer._set_language("fr")

        assert viewer.copy_image_action is copy_action
        assert viewer.cut_image_action is cut_action
        viewer.copy_image_action.trigger()
        assert [url.toLocalFile() for url in QApplication.clipboard().mimeData().urls()] == [str(image_path)]
        viewer.cut_image_action.trigger()
        assert viewer._clipboard_files()[1] == "cut"
        assert viewer.paste_image_action.isEnabled()
    finally:
        _close(viewer, application)
