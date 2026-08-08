from pathlib import Path

from PySide6.QtWidgets import QApplication

from bildbetrachter import ImageViewer, SHOW_HIDDEN_FILES_KEY


def test_show_hidden_action_remains_in_view_menu_when_toggled(tmp_path: Path):
    application = QApplication.instance() or QApplication([])
    viewer = ImageViewer(tmp_path)
    viewer.settings.setValue(SHOW_HIDDEN_FILES_KEY, False)
    viewer.show_hidden_action.setChecked(False)

    assert viewer.show_hidden_action.isCheckable()
    assert viewer.show_hidden_action in viewer.view_menu.actions()

    for expected in [True, False] * 5:
        viewer.show_hidden_action.setChecked(expected)
        assert viewer.show_hidden_action.isChecked() is expected
        assert viewer._show_hidden_files is expected
        assert viewer.settings.value(SHOW_HIDDEN_FILES_KEY, type=bool) is expected
        assert viewer.view_menu.actions().count(viewer.show_hidden_action) == 1

    viewer.window.close()
    application.processEvents()
