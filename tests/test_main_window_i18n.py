from pathlib import Path

from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLabel, QGroupBox, QListView, QListWidgetItem, QMenu
from PySide6.QtTest import QTest

from bildbetrachter import COLOR_SCHEMES, ImageViewer, color_scheme_stylesheet


def _viewer(tmp_path):
    application = QApplication.instance() or QApplication([])
    viewer = ImageViewer(tmp_path)
    viewer.window.show()
    application.processEvents()
    return application, viewer


def test_main_menus_status_and_navigation_are_translated_in_all_languages(tmp_path):
    application, viewer = _viewer(tmp_path)
    expected = {
        "de": ("Datei", "Bearbeiten", "Ansicht", "Gehe zu", "Werkzeuge", "Hilfe", "Bereit", "Vorheriges Bild"),
        "en": ("File", "Edit", "View", "Go", "Tools", "Help", "Ready", "Previous image"),
        "fr": ("Fichier", "Édition", "Affichage", "Aller à", "Outils", "Aide", "Prêt", "Image précédente"),
        "es": ("Archivo", "Editar", "Ver", "Ir a", "Herramientas", "Ayuda", "Listo", "Imagen anterior"),
        "uk": ("Файл", "Редагування", "Вигляд", "Перейти", "Інструменти", "Довідка", "Готово", "Попереднє зображення"),
    }
    viewer.set_status("ready")
    for code, texts in expected.items():
        viewer._set_language(code)
        assert [action.text() for action in viewer.window.menuBar().actions()] == list(texts[:6])
        assert viewer.status_info_label.text() == texts[6]
        assert viewer.previous_button.toolTip() == texts[7]
    viewer.window.close()
    application.processEvents()


def test_main_menu_reuses_existing_actions_in_their_new_groups(tmp_path):
    application, viewer = _viewer(tmp_path)

    assert viewer.copy_image_action in viewer.edit_menu.actions()
    assert viewer.cut_image_action in viewer.edit_menu.actions()
    assert viewer.paste_image_action in viewer.edit_menu.actions()
    assert viewer.rename_image_action in viewer.edit_menu.actions()
    assert viewer.trash_image_action in viewer.edit_menu.actions()
    assert viewer.rotate_left_action in viewer.edit_menu.actions()
    assert viewer.rotate_right_action in viewer.edit_menu.actions()
    assert viewer.previous_folder_action in viewer.go_to_menu.actions()
    assert viewer.next_folder_action in viewer.go_to_menu.actions()
    assert viewer.parent_folder_action in viewer.go_to_menu.actions()
    assert viewer.compare_images_action in viewer.tools_menu.actions()
    assert viewer.find_duplicates_action in viewer.tools_menu.actions()
    assert viewer.slideshow_menu.menuAction() in viewer.view_menu.actions()
    assert viewer.information_toggle_action in viewer.view_menu.actions()

    viewer.window.close()
    application.processEvents()


def test_thumbnail_position_switching_persists_and_keeps_the_same_list(tmp_path):
    application, viewer = _viewer(tmp_path)
    thumbnail_list = viewer.thumbnail_list
    try:
        first, second = QListWidgetItem("first"), QListWidgetItem("second")
        first.setData(Qt.ItemDataRole.UserRole, str(tmp_path / "first.jpg"))
        second.setData(Qt.ItemDataRole.UserRole, str(tmp_path / "second.jpg"))
        thumbnail_list.addItem(first)
        thumbnail_list.addItem(second)
        first.setSelected(True)
        second.setSelected(True)
        for position in ("top", "left", "right", "hidden", "top"):
            viewer._set_thumbnail_position(position)
            assert viewer.thumbnail_list is thumbnail_list
            assert {item.text() for item in thumbnail_list.selectedItems()} == {"first", "second"}
            assert viewer.thumbnail_position_actions[position].isChecked()
            assert sum(action.isChecked() for action in viewer.thumbnail_position_actions.values()) == 1
            assert viewer.thumbnail_panel.isHidden() is (position == "hidden")
        assert viewer.settings.value("view/thumbnail_position", type=str) == "top"

        viewer.settings.setValue("view/thumbnail_position", "left")
        viewer.settings.sync()
        restored = ImageViewer(tmp_path)
        try:
            assert restored._thumbnail_position == "left"
            assert restored.thumbnail_list.flow() == QListView.Flow.TopToBottom
            assert restored.thumbnail_list.isWrapping() is False
        finally:
            restored.settings.setValue("view/thumbnail_position", "top")
            restored.settings.sync()
            restored.window.close()
    finally:
        viewer.settings.setValue("view/thumbnail_position", "top")
        viewer.settings.sync()
        viewer.window.close()
        application.processEvents()


def test_top_thumbnail_position_wraps_into_rows_and_side_positions_stay_vertical(tmp_path):
    application, viewer = _viewer(tmp_path)
    try:
        viewer.window.resize(900, 700)
        for page in range(12):
            item = QListWidgetItem(f"image-{page}")
            item.setSizeHint(viewer._thumbnail_grid_size)
            item.setData(Qt.ItemDataRole.UserRole, str(tmp_path / f"image-{page}.jpg"))
            viewer.thumbnail_list.addItem(item)
        viewer._set_thumbnail_position("top")
        application.processEvents()
        assert viewer.thumbnail_list.flow() == QListView.Flow.LeftToRight
        assert viewer.thumbnail_list.isWrapping() is True
        first_row_y = viewer.thumbnail_list.visualItemRect(
            viewer.thumbnail_list.item(0)
        ).y()
        assert any(
            viewer.thumbnail_list.visualItemRect(viewer.thumbnail_list.item(page)).y()
            > first_row_y
            for page in range(1, viewer.thumbnail_list.count())
        )

        for position in ("left", "right"):
            viewer._set_thumbnail_position(position)
            assert viewer.thumbnail_list.flow() == QListView.Flow.TopToBottom
            assert viewer.thumbnail_list.isWrapping() is False

        viewer._set_thumbnail_position("top")
        assert viewer.thumbnail_list.flow() == QListView.Flow.LeftToRight
        assert viewer.thumbnail_list.isWrapping() is True
    finally:
        viewer.settings.setValue("view/thumbnail_position", "top")
        viewer.settings.sync()
        viewer.window.close()
        application.processEvents()


def test_thumbnail_position_menu_translates_live_in_all_languages(tmp_path):
    application, viewer = _viewer(tmp_path)
    expected = {
        "de": ("Vorschaubilder", "Oben", "Links", "Rechts", "Ausblenden"),
        "en": ("Thumbnails", "Top", "Left", "Right", "Hide"),
        "fr": ("Vignettes", "En haut", "À gauche", "À droite", "Masquer"),
        "es": ("Miniaturas", "Arriba", "Izquierda", "Derecha", "Ocultar"),
        "uk": ("Мініатюри", "Вгорі", "Ліворуч", "Праворуч", "Приховати"),
    }
    try:
        for code, texts in expected.items():
            viewer._set_language(code)
            assert viewer.thumbnail_position_menu.title() == texts[0]
            assert [action.text() for action in viewer.thumbnail_position_menu.actions()] == list(texts[1:])
    finally:
        viewer._set_language("de")
        viewer.window.close()
        application.processEvents()


def test_directory_header_count_and_splitter_remain_live_and_translated(tmp_path):
    application, viewer = _viewer(tmp_path)
    directory_tree = viewer.directory_tree
    try:
        viewer.current_directory = tmp_path
        for name in ("first.jpg", "second.jpg"):
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, str(tmp_path / name))
            viewer.thumbnail_list.addItem(item)
        expected_count = {
            "de": "2 Bilder", "en": "2 images", "fr": "2 images",
            "es": "2 imágenes", "uk": "2 зображень",
        }
        for language, count_text in expected_count.items():
            viewer._set_language(language)
            viewer._update_directory_heading()
            assert viewer.directory_heading_label.text() == tmp_path.name
            assert count_text in viewer.directory_path_label.toolTip()

        viewer.splitter.setSizes([260, 640])
        application.processEvents()
        assert viewer.directory_tree is directory_tree
        assert viewer.splitter.sizes()[0] > 0
    finally:
        viewer._set_language("de")
        viewer.window.close()
        application.processEvents()


def test_system_directory_tree_selection_uses_palette_for_active_and_inactive_rows():
    stylesheet = color_scheme_stylesheet(None)
    selector = "QWidget#centralwidget QTreeView::item"

    assert f"{selector}:selected," in stylesheet
    assert f"{selector}:selected:active," in stylesheet
    assert f"{selector}:selected:!active" in stylesheet
    assert "background-color: palette(highlight); color: palette(highlighted-text);" in stylesheet


def test_system_top_thumbnail_strip_has_its_own_palette_surface_and_divider(tmp_path):
    application, viewer = _viewer(tmp_path)
    try:
        stylesheet = color_scheme_stylesheet(None)
        selector = 'QWidget#thumbnailPanel[thumbnailPosition="top"]'
        assert selector in stylesheet
        assert "background-color: palette(alternate-base);" in stylesheet
        assert "border-bottom: 1px solid palette(mid);" in stylesheet
        assert f"{selector} QListWidget#thumbnailList" in stylesheet
        assert "background-color: transparent;" in stylesheet

        viewer._color_scheme = "System"
        viewer._apply_color_scheme()
        viewer._set_thumbnail_position("top")
        assert viewer.thumbnail_panel.property("thumbnailPosition") == "top"
    finally:
        viewer.window.close()
        application.processEvents()


def test_explicit_color_schemes_keep_their_existing_directory_tree_selection_colors():
    for scheme in ("Hell", "Dunkel"):
        stylesheet = color_scheme_stylesheet(COLOR_SCHEMES[scheme])
        assert "background-color: palette(highlight); color: palette(highlighted-text);" not in stylesheet


def test_explicit_color_schemes_do_not_add_the_system_thumbnail_strip_rule():
    selector = 'QWidget#thumbnailPanel[thumbnailPosition="top"]'
    for scheme in ("Hell", "Dunkel"):
        assert selector not in color_scheme_stylesheet(COLOR_SCHEMES[scheme])


def test_bottom_information_button_is_round_accented_and_keeps_its_behavior(tmp_path):
    application, viewer = _viewer(tmp_path)
    try:
        button = viewer.information_toggle_button
        assert button.parent() is viewer.bottom_control_bar
        assert button.width() == button.height() == 24
        assert button.toolTip() == "Bildinformationen (I)"

        system_stylesheet = color_scheme_stylesheet(None)
        selector = "QWidget#bottomControlBar QToolButton#informationToggleButton"
        assert selector in system_stylesheet
        assert "border-radius: 12px; padding: 0;" in system_stylesheet
        assert "background: #2878c8; color: #ffffff;" in system_stylesheet

        for scheme in ("Hell", "Dunkel"):
            colors = COLOR_SCHEMES[scheme]
            stylesheet = color_scheme_stylesheet(colors)
            assert f"background-color: {colors['selection']}; color: {colors['selection_text']};" in stylesheet

        assert not viewer.information_panel.isVisible()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        application.processEvents()
        assert viewer.information_panel.isVisible()
        assert button.isChecked()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        application.processEvents()
        assert not viewer.information_panel.isVisible()
        assert not button.isChecked()
    finally:
        viewer.window.close()
        application.processEvents()


def test_default_main_proportions_prioritize_the_image_without_fixing_panels(tmp_path):
    application, viewer = _viewer(tmp_path)
    try:
        main_sizes = viewer.splitter.sizes()
        right_sizes = viewer.right_splitter.sizes()
        assert main_sizes[1] > main_sizes[0]
        assert main_sizes[0] <= 270
        assert right_sizes[1] > right_sizes[0]
        assert right_sizes[0] <= 200
        assert viewer.information_panel.minimumWidth() == 300
        assert viewer.information_panel.maximumWidth() > 1_000_000

        viewer.splitter.setSizes([330, 570])
        viewer.right_splitter.setSizes([260, 440])
        application.processEvents()
        assert viewer.splitter.sizes()[0] > 0
        assert viewer.right_splitter.sizes()[0] > 0
    finally:
        viewer.window.close()
        application.processEvents()


def test_bottom_control_bar_auto_hides_and_returns_for_the_bottom_activation_zone(tmp_path):
    application, viewer = _viewer(tmp_path)
    try:
        viewer.set_status("ready")
        assert viewer.status_bar.isVisible()
        assert viewer.bottom_control_bar_start_timer.isActive()

        viewer.bottom_control_bar_start_timer.timeout.emit()
        assert viewer.bottom_control_bar_hide_timer.isActive()
        viewer.bottom_control_bar_hide_timer.timeout.emit()
        assert viewer.status_bar.isHidden()

        bottom_position = viewer.window.mapToGlobal(
            QPoint(viewer.window.width() // 2, viewer.window.height() - 8)
        )
        viewer._update_bottom_control_bar_visibility(bottom_position)
        assert viewer.status_bar.isVisible()

        viewer._bottom_control_bar_active = True
        viewer.bottom_control_bar_hide_timer.timeout.emit()
        assert viewer.status_bar.isVisible()
        viewer._bottom_control_bar_active = False
        viewer._schedule_bottom_control_bar_hide()
        assert viewer.bottom_control_bar_hide_timer.isActive()
        viewer.bottom_control_bar_hide_timer.timeout.emit()
        assert viewer.status_bar.isHidden()
    finally:
        viewer.window.close()
        application.processEvents()


def test_bottom_control_bar_statuses_control_visibility_and_slider(tmp_path):
    application, viewer = _viewer(tmp_path)
    try:
        viewer.set_status("busy", "Bild wird geladen …")
        assert viewer.status_info_label.text() == "Bild wird geladen …"
        assert "#f59e0b" in viewer.bottom_status_dot.styleSheet()
        assert viewer.status_bar.isVisible()
        assert not viewer.bottom_control_bar_start_timer.isActive()
        assert not viewer.bottom_control_bar_hide_timer.isActive()

        viewer.set_status("error", "Bild konnte nicht geladen werden")
        assert "#ef4444" in viewer.bottom_status_dot.styleSheet()
        viewer._hide_bottom_control_bar()
        assert viewer.status_bar.isVisible()

        viewer.set_status("ready")
        assert viewer.status_info_label.text() == "Bereit"
        assert "#20c977" in viewer.bottom_status_dot.styleSheet()
        assert viewer.bottom_control_bar_start_timer.isActive()
        viewer.bottom_control_bar_start_timer.timeout.emit()
        assert viewer.bottom_control_bar_hide_timer.isActive()

        viewer.window.resize(640, 500)
        viewer._update_bottom_control_bar_layout()
        assert viewer.thumbnail_size_slider.isHidden()
        viewer.window.resize(900, 500)
        viewer._update_bottom_control_bar_layout()
        assert viewer.thumbnail_size_slider.isVisible()
    finally:
        viewer.window.close()
        application.processEvents()


def test_repeated_ready_status_does_not_reshow_an_auto_hidden_bar(tmp_path):
    application, viewer = _viewer(tmp_path)
    try:
        viewer.set_status("busy")
        viewer.set_status("ready")
        viewer.bottom_control_bar_start_timer.stop()
        viewer.bottom_control_bar_start_timer.timeout.emit()
        viewer.bottom_control_bar_hide_timer.stop()
        viewer.bottom_control_bar_hide_timer.timeout.emit()
        assert viewer.status_bar.isHidden()

        viewer.set_status("ready")

        assert viewer.status_bar.isHidden()
        assert not viewer.bottom_control_bar_start_timer.isActive()
        assert not viewer.bottom_control_bar_hide_timer.isActive()
    finally:
        viewer.window.close()
        application.processEvents()


def test_quick_switches_reuse_existing_states_and_live_translations(tmp_path):
    application, viewer = _viewer(tmp_path)
    image_path = tmp_path / "quick-switches.png"
    image = QImage(30, 20, QImage.Format.Format_RGB32)
    assert image.save(str(image_path))
    try:
        quick_switches = [
            viewer.thumbnail_quick_toggle,
            viewer.details_quick_toggle,
            viewer.fullscreen_quick_toggle,
        ]
        assert [button.objectName() for button in quick_switches] == [
            "thumbnailQuickToggle", "detailsQuickToggle", "fullscreenQuickToggle",
        ]
        assert all(button.isCheckable() for button in quick_switches)

        viewer._set_thumbnail_position("left")
        assert viewer.thumbnail_quick_toggle.isChecked()
        viewer.thumbnail_quick_toggle.click()
        assert viewer._thumbnail_position == "hidden"
        assert not viewer.thumbnail_quick_toggle.isChecked()
        viewer.thumbnail_quick_toggle.click()
        assert viewer._thumbnail_position == "left"
        assert viewer.thumbnail_quick_toggle.isChecked()
        viewer._set_thumbnail_position("hidden")
        assert not viewer.thumbnail_quick_toggle.isChecked()
        viewer._set_thumbnail_position("right")
        assert viewer.thumbnail_quick_toggle.isChecked()

        assert not viewer.details_quick_toggle.isChecked()
        QTest.keyClick(viewer.window, Qt.Key.Key_I)
        assert viewer.information_panel.isVisible()
        assert viewer.details_quick_toggle.isChecked()
        QTest.keyClick(viewer.window, Qt.Key.Key_Escape)
        assert not viewer.information_panel.isVisible()
        assert not viewer.details_quick_toggle.isChecked()

        viewer.current_image = image_path
        viewer._load_current_image()
        QTest.keyClick(viewer.window, Qt.Key.Key_F11)
        assert viewer._fullscreen_mode
        assert viewer.fullscreen_quick_toggle.isChecked()
        QTest.keyClick(viewer.window, Qt.Key.Key_Escape)
        assert not viewer._fullscreen_mode
        assert not viewer.fullscreen_quick_toggle.isChecked()

        expected = {
            "de": ("Vorschaubilder", "Details", "Vollbild"),
            "en": ("Thumbnails", "Details", "Fullscreen"),
            "fr": ("Vignettes", "Détails", "Plein écran"),
            "es": ("Miniaturas", "Detalles", "Pantalla completa"),
            "uk": ("Мініатюри", "Деталі", "Повний екран"),
        }
        for language, labels in expected.items():
            viewer._set_language(language)
            application.processEvents()
            assert [button.text() for button in quick_switches] == list(labels)
            for button, label in zip(quick_switches, labels):
                assert button.width() >= button.fontMetrics().horizontalAdvance(label) + 10
    finally:
        viewer._set_language("de")
        viewer._set_thumbnail_position("top")
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
