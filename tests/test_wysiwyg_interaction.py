from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from printing.layout import ImageSourceInfo, RectMm
from printing.wysiwyg_dialog import SingleImageWysiwygPrintDialog


def _dialog(tmp_path):
    QApplication.instance() or QApplication([])
    image = QImage(1200, 800, QImage.Format.Format_RGB32)
    source = ImageSourceInfo(Path("example.jpg"), 1200, 800, 300, 300, "example.jpg")
    return SingleImageWysiwygPrintDialog(image, source, QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))


def test_custom_geometry_updates_the_same_page_plan_and_reset_restores_planner(tmp_path):
    dialog = _dialog(tmp_path)
    planned = dialog.build_page_plan().image_elements[0].target_rect
    custom = RectMm(12, 15, 80, 50)
    dialog._set_custom_geometry(custom)
    assert dialog.position.currentData() == "custom"
    assert dialog.build_page_plan().image_elements[0].target_rect == custom
    dialog._reset_custom_geometry()
    assert dialog.position.currentData() == "center"
    assert dialog.build_page_plan().image_elements[0].target_rect == planned


def test_named_layout_change_discards_custom_geometry(tmp_path):
    dialog = _dialog(tmp_path)
    dialog._set_custom_geometry(RectMm(12, 15, 80, 50))
    dialog.paper.setCurrentText("10 × 15 cm")
    assert dialog._custom_rect_mm is None
    assert dialog.build_page_plan().image_elements[0].target_rect != RectMm(12, 15, 80, 50)


def test_preview_constrains_and_snaps_geometry_in_mm(tmp_path):
    dialog = _dialog(tmp_path)
    preview = dialog.preview
    bounds = preview._content_rect_mm()
    snapped = preview._constrain_and_snap(RectMm(bounds.x_mm + 0.1, bounds.y_mm + 0.1, 20, 20), 10.0)
    assert snapped.x_mm == bounds.x_mm and snapped.y_mm == bounds.y_mm
    assert preview._guide_lines == (True, True)
    outside = preview._constrain_and_snap(RectMm(-100, -100, 20, 20), 10.0)
    assert outside.x_mm == bounds.x_mm and outside.y_mm == bounds.y_mm


def test_preview_resize_honours_aspect_lock(tmp_path):
    dialog = _dialog(tmp_path)
    preview = dialog.preview
    rect = RectMm(20, 20, 60, 40)
    preview._start_rect = rect
    preview._drag_mode = "bottom_right"
    preview.set_lock_aspect_ratio(True)
    locked = preview._resized_rect(30, 1)
    assert round(locked.width_mm / locked.height_mm, 6) == round(rect.width_mm / rect.height_mm, 6)
    preview.set_lock_aspect_ratio(False)
    unlocked = preview._resized_rect(30, 1)
    assert unlocked.width_mm == 90 and unlocked.height_mm == 41
