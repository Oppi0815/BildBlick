from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHBoxLayout

from bildbetrachter import (
    ImageViewer,
    activate_startup_fullscreen,
    create_command_line_parser,
    resolve_startup_path,
    schedule_startup_fullscreen,
    should_auto_enter_pdf_preview,
)


def _viewer_with_image(tmp_path: Path) -> tuple[QApplication, ImageViewer, Path]:
    application = QApplication.instance() or QApplication([])
    image_path = tmp_path / "Bild mit Leerzeichen.png"
    image = QImage(120, 80, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.green)
    assert image.save(str(image_path))
    viewer = ImageViewer(tmp_path)
    viewer.window.resize(900, 700)
    viewer.window.show()
    viewer.current_image = image_path
    viewer._load_current_image()
    application.processEvents()
    return application, viewer, image_path


def test_fullscreen_option_is_recognized_with_a_path_containing_spaces(tmp_path: Path):
    image_path = tmp_path / "Bild mit Leerzeichen.png"
    parser = create_command_line_parser()

    parser.process(["BildBlick", "--fullscreen", str(image_path)])

    assert parser.isSet("fullscreen")
    assert parser.positionalArguments() == [str(image_path)]


def test_without_fullscreen_option_the_parser_leaves_it_disabled(tmp_path: Path):
    parser = create_command_line_parser()

    parser.process(["BildBlick", str(tmp_path / "bild.jpg")])

    assert not parser.isSet("fullscreen")


def test_file_menu_uses_only_the_standard_pageplan_print_actions(tmp_path: Path):
    QApplication.instance() or QApplication([])
    viewer = ImageViewer(tmp_path)
    print_actions = [action for action in viewer.file_menu.actions() if "drucken" in action.text().lower()]
    assert [action.text() for action in print_actions] == ["Drucken …", "Mehrere Bilder drucken …"]
    assert "Kontaktabzug …" not in [action.text() for action in viewer.file_menu.actions()]
    assert viewer.print_action.shortcut() == QKeySequence(QKeySequence.StandardKey.Print)
    assert not hasattr(viewer, "wysiwyg_print_action")
    assert not hasattr(viewer, "multi_wysiwyg_print_action")
    assert not hasattr(viewer, "contact_sheet_action")
    viewer.window.close()


def test_pdf_startup_path_is_preserved_for_fullscreen_launch(tmp_path: Path):
    pdf_path = tmp_path / "Dokument mit Leerzeichen.pdf"
    pdf_path.touch()

    directory, startup_file, error = resolve_startup_path(str(pdf_path))

    assert error is None
    assert directory == tmp_path
    assert startup_file == pdf_path


def test_startup_fullscreen_uses_existing_toggle_and_escape_and_f11_leave(
    tmp_path: Path,
):
    application, viewer, _image_path = _viewer_with_image(tmp_path)

    assert not viewer._fullscreen_mode
    assert activate_startup_fullscreen(viewer)
    assert viewer._fullscreen_mode
    viewer._handle_escape()
    assert not viewer._fullscreen_mode

    assert activate_startup_fullscreen(viewer)
    viewer.fullscreen_action.trigger()
    assert not viewer._fullscreen_mode
    viewer.window.close()
    application.processEvents()


def test_startup_fullscreen_waits_until_an_image_is_available(tmp_path: Path):
    application = QApplication.instance() or QApplication([])
    viewer = ImageViewer(tmp_path)

    assert not activate_startup_fullscreen(viewer)
    assert not viewer._fullscreen_mode
    viewer.window.close()
    application.processEvents()


def test_pdf_preview_hides_file_panes_and_escape_restores_them(tmp_path: Path):
    application, viewer, _image_path = _viewer_with_image(tmp_path)

    viewer._enter_pdf_preview()
    application.processEvents()

    assert viewer._pdf_preview_mode
    assert viewer.directory_panel.isHidden()
    assert viewer.thumbnail_panel.isHidden()
    assert viewer.leave_pdf_preview_action.isEnabled()

    viewer._handle_escape()
    application.processEvents()

    assert not viewer._pdf_preview_mode
    assert not viewer.directory_panel.isHidden()
    assert not viewer.thumbnail_panel.isHidden()
    assert not viewer.leave_pdf_preview_action.isEnabled()
    viewer.window.close()
    application.processEvents()


def test_pdf_preview_is_automatically_enabled_only_on_macos(
    tmp_path: Path, monkeypatch
):
    pdf_path = tmp_path / "Dokument.pdf"

    monkeypatch.setattr("bildbetrachter.sys.platform", "linux")
    assert not should_auto_enter_pdf_preview(pdf_path)

    monkeypatch.setattr("bildbetrachter.sys.platform", "darwin")
    assert should_auto_enter_pdf_preview(pdf_path)
    assert not should_auto_enter_pdf_preview(tmp_path / "Bild.png")


def test_compact_navigation_replaces_the_old_preview_layout(tmp_path: Path):
    application, viewer, image_path = _viewer_with_image(tmp_path)

    controls = viewer.thumbnail_size_slider.parentWidget()
    assert controls.objectName() == "thumbnailSizeControls"
    assert viewer.bottom_control_bar.isAncestorOf(viewer.previous_button)
    assert viewer.bottom_control_bar.isAncestorOf(viewer.next_button)
    assert viewer.bottom_control_bar.isAncestorOf(viewer.file_name_label)
    viewer._set_file_name_text(image_path.name)
    assert viewer.file_name_label.toolTip() == image_path.name
    assert viewer.thumbnail_size_slider.width() == 132
    assert viewer.thumbnail_size_slider.height() == 14
    assert viewer.window.findChild(QHBoxLayout, "navigationLayout") is None
    assert viewer.bottom_control_bar.isAncestorOf(viewer.thumbnail_size_slider)
    viewer.window.close()
    application.processEvents()


def test_scheduled_startup_fullscreen_activates_after_the_window_is_ready(
    tmp_path: Path,
):
    application, viewer, _image_path = _viewer_with_image(tmp_path)

    schedule_startup_fullscreen(viewer)
    QTest.qWait(10)

    assert viewer._fullscreen_mode
    viewer._leave_fullscreen()
    viewer.window.close()
    application.processEvents()


def test_desktop_starters_keep_normal_and_pdf_launches_separate():
    project_directory = Path(__file__).resolve().parents[1]
    normal_starter = (project_directory / "bildblick.desktop").read_text()
    pdf_starter = (project_directory / "bildblick-pdf.desktop").read_text()

    assert "Exec=/home/horst/.local/bin/BildBlick %f" in normal_starter
    assert "--fullscreen" not in normal_starter
    assert "Exec=/home/horst/.local/bin/BildBlick --fullscreen %f" in pdf_starter
    assert "MimeType=application/pdf;" in pdf_starter
