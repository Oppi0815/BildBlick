from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidgetItem

from bildbetrachter import ImageViewer


def _viewer_with_selected_source(
    source_directory: Path, source_path: Path
) -> tuple[QApplication, ImageViewer]:
    application = QApplication.instance() or QApplication([])
    viewer = ImageViewer(source_directory)
    item = QListWidgetItem(source_path.name)
    item.setData(Qt.ItemDataRole.UserRole, str(source_path))
    viewer.thumbnail_list.addItem(item)
    item.setSelected(True)
    return application, viewer


def _select_paste_target(viewer: ImageViewer, target_directory: Path) -> None:
    target_index = viewer.directory_model.index(str(target_directory))
    assert target_index.isValid()
    viewer.directory_tree.setCurrentIndex(target_index)
    viewer._clipboard_changed()


def test_copy_then_paste_uses_the_selected_target_folder(tmp_path: Path):
    source_directory = tmp_path / "source"
    target_directory = tmp_path / "target"
    source_directory.mkdir()
    target_directory.mkdir()
    source_path = source_directory / "photo.jpg"
    source_path.write_bytes(b"image data")
    application, viewer = _viewer_with_selected_source(source_directory, source_path)

    viewer._put_current_image_on_clipboard("copy")
    _select_paste_target(viewer, target_directory)

    assert viewer.paste_image_action.isEnabled()
    viewer._paste_image_from_clipboard()

    assert source_path.exists()
    assert (target_directory / source_path.name).read_bytes() == b"image data"
    viewer.clipboard.clear()
    viewer.window.close()
    application.processEvents()


def test_cut_then_paste_preserves_the_cut_operation_between_folders(tmp_path: Path):
    source_directory = tmp_path / "source"
    target_directory = tmp_path / "target"
    source_directory.mkdir()
    target_directory.mkdir()
    source_path = source_directory / "photo.jpg"
    source_path.write_bytes(b"image data")
    application, viewer = _viewer_with_selected_source(source_directory, source_path)

    viewer._put_current_image_on_clipboard("cut")
    _select_paste_target(viewer, target_directory)

    assert viewer._clipboard_files()[1] == "cut"
    assert viewer.paste_image_action.isEnabled()
    viewer._paste_image_from_clipboard()

    assert not source_path.exists()
    assert (target_directory / source_path.name).read_bytes() == b"image data"
    assert viewer._clipboard_files() == ([], "copy")
    viewer.window.close()
    application.processEvents()
