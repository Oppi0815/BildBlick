from pathlib import Path

from PySide6.QtCore import QPoint, QSettings
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLabel, QGroupBox, QMenu

from bildbetrachter import ImageViewer


def _viewer(tmp_path):
    application = QApplication.instance() or QApplication([])
    viewer = ImageViewer(tmp_path)
    viewer.window.show()
    application.processEvents()
    return application, viewer


def test_main_menus_status_and_navigation_are_translated_in_all_languages(tmp_path):
    application, viewer = _viewer(tmp_path)
    expected = {
        "en": ("File", "Edit", "Image", "View", "Tools", "No image selected", "Previous image"),
        "fr": ("Fichier", "Édition", "Image", "Affichage", "Outils", "Aucune image sélectionnée", "Image précédente"),
        "es": ("Archivo", "Editar", "Imagen", "Ver", "Herramientas", "Ninguna imagen seleccionada", "Imagen anterior"),
        "uk": ("Файл", "Редагування", "Зображення", "Вигляд", "Інструменти", "Зображення не вибрано", "Попереднє зображення"),
    }
    for code, texts in expected.items():
        viewer._set_language(code)
        assert (viewer.file_menu.title(), viewer.edit_menu.title(), viewer.image_menu.title(), viewer.view_menu.title(), viewer.tools_menu.title()) == texts[:5]
        assert viewer.status_info_label.text() == texts[5]
        assert viewer.previous_button.toolTip() == texts[6]
    viewer.window.close()
    application.processEvents()


def test_image_and_thumbnail_context_menus_use_translated_actions(tmp_path, monkeypatch):
    application, viewer = _viewer(tmp_path)
    viewer._set_language("fr")
    image_menu = QMenu()
    image_menu.addAction(viewer.rename_image_action)
    rotation_menu = viewer._add_rotation_context_submenu(image_menu, None)
    assert viewer.rename_image_action.text() == "Renommer …"
    assert rotation_menu.title() == "Pivoter"
    viewer._set_language("uk")
    thumbnail_menu = QMenu()
    thumbnail_menu.addAction(viewer.copy_image_action)
    thumbnail_menu.addAction(viewer.trash_image_action)
    rotation_menu = viewer._add_rotation_context_submenu(thumbnail_menu, None)
    assert viewer.copy_image_action.text() == "Копіювати"
    assert rotation_menu.title() == "Повернути"
    viewer.window.close()
    application.processEvents()


def test_information_panel_and_live_switch_refresh_visible_text(tmp_path):
    application, viewer = _viewer(tmp_path)
    image_path = tmp_path / "plain.png"
    image = QImage(20, 10, QImage.Format.Format_RGB32)
    assert image.save(str(image_path))
    viewer.current_image = image_path
    viewer._show_information_panel()
    viewer._set_language("en")
    assert viewer.information_toggle_button.toolTip() == "Image information (I)"
    assert any(group.title() == "IMAGE" for group in viewer.information_content.findChildren(QGroupBox))
    viewer._set_language("uk")
    assert viewer.all_metadata_toggle.text().endswith("Усі метадані")
    viewer.current_image = None
    viewer._populate_all_metadata()
    assert any(label.text() == "Додаткові метадані відсутні" for label in viewer.all_metadata_content.findChildren(QLabel))
    viewer.window.close()
    application.processEvents()
