from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from bildbetrachter import (
    ImageViewer,
    activate_startup_fullscreen,
    create_command_line_parser,
    resolve_startup_path,
    schedule_startup_fullscreen,
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
