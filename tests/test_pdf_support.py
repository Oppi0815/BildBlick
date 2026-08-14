from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QSize, QSizeF, QTimer, Qt
from PySide6.QtGui import QColor, QImage, QPageSize, QPainter, QPdfWriter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication, QToolTip

import bildbetrachter
from bildbetrachter import PDF_FULLSCREEN_NAVIGATION_HINT_DURATION, ImageViewer
from pdf_support import (
    PDF_SCREEN_RENDER_MAX_EDGE,
    pdf_display_target_size,
    load_pdf,
    pdf_page_render_size,
    pdf_render_size_matches,
    prepare_pdf_rendered_image,
    render_pdf_page,
    render_pdf_page_for_printer,
    render_pdf_page_with_fallback,
)


def test_pdf_render_size_match_tolerates_only_rounding_differences():
    assert pdf_render_size_matches(QSize(417, 590), QSize(420, 587))
    assert not pdf_render_size_matches(QSize(417, 590), QSize(421, 590))


def test_pdf_printer_render_uses_print_area_not_screen_pixmap(tmp_path: Path):
    application = QApplication.instance() or QApplication([])
    pdf_path = tmp_path / "printer-render.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)])
    document = load_pdf(pdf_path).document

    image = render_pdf_page_for_printer(document, 0, QSize(2400, 1800))

    assert image.size() == QSize(900, 1800)
    application.processEvents()


def _write_pdf(path: Path, page_sizes: list[QSizeF]) -> None:
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(page_sizes[0], QPageSize.Unit.Point))
    painter = QPainter(writer)
    for index, page_size in enumerate(page_sizes):
        if index:
            writer.newPage()
        painter.drawText(20, 30, f"Seite {index + 1}")
    painter.end()


def _viewer(tmp_path: Path) -> tuple[QApplication, ImageViewer]:
    application = QApplication.instance() or QApplication([])
    viewer = ImageViewer(tmp_path)
    viewer.window.resize(900, 700)
    viewer.window.show()
    application.processEvents()
    return application, viewer


def _open_pdf(viewer: ImageViewer, path: Path) -> None:
    viewer.current_image = path
    viewer._load_current_image()


def test_fullscreen_pdf_page_thumbnails_are_pdf_only_and_follow_navigation(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "pages.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)] * 4)
    try:
        _open_pdf(viewer, pdf_path)
        assert viewer.pdf_thumbnail_bar.isHidden()
        viewer._enter_fullscreen()
        application.processEvents()
        assert viewer.pdf_thumbnail_bar.isVisible()
        assert viewer.pdf_thumbnail_bar.count() == 4
        assert viewer.pdf_thumbnail_bar.currentRow() == 0
        assert viewer._pdf_thumbnail_document is not viewer._pdf_document
        assert [
            viewer.pdf_thumbnail_bar.item(page).data(Qt.ItemDataRole.UserRole)
            for page in range(4)
        ] == [0, 1, 2, 3]

        initial_hints = [
            viewer.pdf_thumbnail_bar.item(page).sizeHint()
            for page in range(viewer.pdf_thumbnail_bar.count())
        ]
        assert all(hint == QSize(140, 212) for hint in initial_hints)
        assert viewer.pdf_thumbnail_panel.width() == (
            174 + viewer._pdf_print_checkbox_column_width
        )
        checkbox = viewer._pdf_print_checkboxes[1]
        assert viewer._pdf_print_checkbox_column_width >= checkbox.sizeHint().width() + 12
        checkbox.click()
        assert viewer.selected_pdf_pages() == [1]
        assert viewer._pdf_page == 0
        assert viewer.pdf_thumbnail_bar.horizontalScrollBar().maximum() == 0
        assert viewer.pdf_thumbnail_bar.toolTip() == ""

        third_page = viewer.pdf_thumbnail_bar.item(2)
        QTest.mouseClick(
            viewer.pdf_thumbnail_bar.viewport(),
            Qt.MouseButton.LeftButton,
            pos=viewer.pdf_thumbnail_bar.visualItemRect(third_page).center(),
        )
        application.processEvents()
        assert viewer._pdf_page == 2
        assert viewer.pdf_thumbnail_bar.currentRow() == 2
        assert viewer.selected_pdf_pages() == [1]
        assert third_page.toolTip() == ""

        fourth_page = viewer.pdf_thumbnail_bar.item(3)
        QTest.mouseClick(
            viewer.pdf_thumbnail_bar.viewport(),
            Qt.MouseButton.LeftButton,
            pos=viewer.pdf_thumbnail_bar.visualItemRect(fourth_page).center(),
        )
        assert viewer._pdf_page == 3
        assert viewer.pdf_thumbnail_bar.currentRow() == 3
        assert viewer.selected_pdf_pages() == [1]
        assert [
            viewer.pdf_thumbnail_bar.item(page).sizeHint()
            for page in range(viewer.pdf_thumbnail_bar.count())
        ] == initial_hints

        for page in (0, 1, 2, 0, 3, 1):
            item = viewer.pdf_thumbnail_bar.item(page)
            QTest.mouseClick(
                viewer.pdf_thumbnail_bar.viewport(),
                Qt.MouseButton.LeftButton,
                pos=viewer.pdf_thumbnail_bar.visualItemRect(item).center(),
            )
            application.processEvents()
            assert viewer._pdf_page == page
            assert viewer.pdf_thumbnail_bar.currentRow() == page

        viewer._change_pdf_page(-1)
        assert viewer._pdf_page == 0
        assert viewer.pdf_thumbnail_bar.currentRow() == 0
        viewer._leave_fullscreen()
        assert viewer.pdf_thumbnail_bar.isHidden()
    finally:
        viewer.window.close()
        application.processEvents()


def test_first_and_second_pdf_open_have_identical_thumbnail_navigation(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "reopen-pages.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)] * 10)
    try:
        expected_hints = []
        for _open_number in range(2):
            _open_pdf(viewer, pdf_path)
            viewer._enter_fullscreen()
            application.processEvents()
            hints = [
                viewer.pdf_thumbnail_bar.item(page).sizeHint()
                for page in range(viewer.pdf_thumbnail_bar.count())
            ]
            assert len(hints) == 10
            assert all(hint == QSize(140, 212) for hint in hints)
            if not expected_hints:
                expected_hints = hints
            assert hints == expected_hints

            target = viewer.pdf_thumbnail_bar.item(3)
            QTest.mouseClick(
                viewer.pdf_thumbnail_bar.viewport(),
                Qt.MouseButton.LeftButton,
                pos=viewer.pdf_thumbnail_bar.visualItemRect(target).center(),
            )
            assert viewer._pdf_page == 3
            viewer._leave_fullscreen()
    finally:
        viewer.window.close()
        application.processEvents()


def test_fullscreen_pdf_thumbnail_list_stays_scrollable_and_translates(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "many-pages.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)] * 20)
    try:
        _open_pdf(viewer, pdf_path)
        viewer._enter_fullscreen()
        application.processEvents()
        assert viewer.pdf_thumbnail_bar.verticalScrollBar().maximum() > 0
        viewer._render_pdf_page(15)
        application.processEvents()
        assert viewer.pdf_thumbnail_bar.currentRow() == 15
        assert viewer.pdf_thumbnail_bar.verticalScrollBar().value() > 0
        for language, expected in {
            "de": ("Seite 16", "↑ / ↓ – vorherige/nächste Seite", "Wird geladen …"),
            "en": ("Page 16", "↑ / ↓ – previous/next page", "Loading …"),
            "fr": ("Page 16", "↑ / ↓ – page précédente/suivante", "Chargement…"),
            "es": ("Página 16", "↑ / ↓ – página anterior/siguiente", "Cargando…"),
            "uk": ("Сторінка 16", "↑ / ↓ – попередня/наступна сторінка", "Завантаження…"),
        }.items():
            viewer._set_language(language)
            assert viewer.pdf_thumbnail_bar.item(15).text() == expected[0]
            viewer._show_pdf_fullscreen_navigation_hint()
            assert viewer.pdf_fullscreen_navigation_hint.text() == expected[1]
            assert viewer.pdf_thumbnail_busy_label.text() == expected[2]
    finally:
        viewer._set_language("de")
        viewer.window.close()
        application.processEvents()


def test_fullscreen_pdf_arrow_navigation_and_busy_indicator(tmp_path: Path, monkeypatch):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "keyboard-pages.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)] * 10)
    try:
        _open_pdf(viewer, pdf_path)
        viewer._enter_fullscreen()
        application.processEvents()
        assert viewer.pdf_fullscreen_navigation_hint.isVisible()
        assert viewer.pdf_fullscreen_navigation_hint_timer.isActive()
        assert viewer.pdf_fullscreen_navigation_hint.text() == (
            "↑ / ↓ – vorherige/nächste Seite"
        )
        assert viewer.pdf_fullscreen_navigation_hint.width() > 0
        assert viewer.pdf_fullscreen_navigation_hint.height() > 0
        assert viewer.pdf_fullscreen_navigation_hint.sizeHint().width() > 200
        assert viewer.pdf_fullscreen_navigation_hint.sizeHint().height() > 30
        assert viewer.pdf_fullscreen_navigation_hint.contentsRect().width() > 0
        assert viewer.pdf_fullscreen_navigation_hint.children() == []
        assert viewer.pdf_fullscreen_navigation_hint.graphicsEffect() is None
        assert viewer.pdf_thumbnail_busy.isHidden()
        assert viewer._pdf_busy_timer.isActive() is False

        QTest.keyClick(viewer.window, Qt.Key.Key_Down)
        assert viewer._pdf_page == 1
        assert viewer.pdf_thumbnail_bar.currentRow() == 1
        QTest.keyClick(viewer.pdf_thumbnail_bar, Qt.Key.Key_Up)
        assert viewer._pdf_page == 0
        QTest.keyClick(viewer.window, Qt.Key.Key_Up)
        assert viewer._pdf_page == 0
        viewer._render_pdf_page(9)
        QTest.keyClick(viewer.window, Qt.Key.Key_Down)
        assert viewer._pdf_page == 9
        assert viewer.pdf_thumbnail_bar.currentRow() == 9
        assert viewer.pdf_thumbnail_bar.verticalScrollBar().value() > 0

        original_render = bildbetrachter.render_pdf_page_with_fallback
        busy_states = []

        def observe_busy(*args, **kwargs):
            busy_states.append(viewer.pdf_thumbnail_busy.isVisible())
            return original_render(*args, **kwargs)

        monkeypatch.setattr(
            bildbetrachter, "render_pdf_page_with_fallback", observe_busy
        )
        viewer._render_pdf_page(8)
        assert busy_states == [True]
        assert viewer.pdf_thumbnail_busy.isHidden()
        assert viewer._pdf_busy_timer.isActive() is False
        viewer._leave_fullscreen()
        assert viewer.pdf_fullscreen_navigation_hint.isHidden()
        assert viewer.pdf_thumbnail_busy.isHidden()
        assert viewer._pdf_busy_timer.isActive() is False
    finally:
        viewer.window.close()
        application.processEvents()


def test_pdf_fullscreen_navigation_hint_is_theme_independent_and_readable(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    try:
        assert bildbetrachter.PDF_FULLSCREEN_NAVIGATION_HINT_DURATION == 8000
        style = viewer.pdf_fullscreen_navigation_hint.styleSheet()
        assert "background-color: rgba(20, 20, 20, 220)" in style
        assert "color: #ffffff" in style
        assert "border: 1px solid rgba(255, 255, 255, 90)" in style
        assert "font-size: 12pt" in style
        for scheme_name in ("System", "Hell", "Dunkel"):
            viewer._color_scheme = scheme_name
            viewer._apply_color_scheme()
            assert viewer.pdf_fullscreen_navigation_hint.styleSheet() == style
    finally:
        viewer.settings.setValue("colorScheme", "System")
        viewer._color_scheme = "System"
        viewer._apply_color_scheme()
        viewer.window.close()
        application.processEvents()


def test_bottom_slider_uses_contrasting_palette_roles_in_all_themes(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    try:
        slider = viewer.thumbnail_size_slider
        assert viewer.bottom_control_bar.isAncestorOf(slider)
        for scheme_name in ("System", "Hell", "Dunkel"):
            viewer._color_scheme = scheme_name
            viewer._apply_color_scheme()
            stylesheet = application.styleSheet()
            assert "QWidget#bottomControlBar QSlider::groove:horizontal" in stylesheet
            assert "border: 1px solid palette(dark)" in stylesheet
            assert "background: palette(midlight)" in stylesheet
            assert "background: palette(highlight)" in stylesheet
    finally:
        viewer.settings.setValue("colorScheme", "System")
        viewer._color_scheme = "System"
        viewer._apply_color_scheme()
        viewer.window.close()
        application.processEvents()


def test_pdf_fullscreen_navigation_hint_only_shows_for_pdfs_and_reappears(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "hint-pages.pdf"
    image_path = tmp_path / "hint-image.png"
    _write_pdf(pdf_path, [QSizeF(200, 400)] * 2)
    image = QImage(80, 50, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.blue)
    assert image.save(str(image_path))
    try:
        _open_pdf(viewer, pdf_path)
        viewer._enter_fullscreen()
        application.processEvents()
        assert viewer.pdf_fullscreen_navigation_hint.isVisible()
        viewer.pdf_fullscreen_navigation_hint_timer.timeout.emit()
        assert viewer.pdf_fullscreen_navigation_hint.isHidden()
        QTest.mouseMove(viewer.image_scroll_area.viewport())
        application.processEvents()
        assert viewer.pdf_fullscreen_navigation_hint.isHidden()
        viewer._leave_fullscreen()

        viewer._enter_fullscreen()
        application.processEvents()
        assert viewer.pdf_fullscreen_navigation_hint.isVisible()
        viewer._leave_fullscreen()

        viewer.current_image = image_path
        viewer._load_current_image()
        viewer._enter_fullscreen()
        application.processEvents()
        assert viewer.pdf_fullscreen_navigation_hint.isHidden()
    finally:
        viewer._leave_fullscreen()
        viewer.window.close()
        application.processEvents()


def test_pdf_fullscreen_suppresses_native_image_tooltips_but_images_keep_them(
    tmp_path: Path, monkeypatch
):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "tooltip-pages.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)] * 2)
    try:
        _open_pdf(viewer, pdf_path)
        viewer._enter_fullscreen()
        assert PDF_FULLSCREEN_NAVIGATION_HINT_DURATION == 8000
        assert viewer.pdf_fullscreen_navigation_hint.isVisible()
        tooltip_event = QEvent(QEvent.Type.ToolTip)
        assert viewer.eventFilter(viewer.image_label, tooltip_event) is True
        assert viewer.pdf_fullscreen_navigation_hint_timer.isActive()
        shown_tooltips = []
        monkeypatch.setattr(
            QToolTip,
            "showText",
            lambda *args: shown_tooltips.append(args),
        )
        shown_hints = []
        monkeypatch.setattr(
            viewer,
            "_show_pdf_fullscreen_navigation_hint",
            lambda: shown_hints.append(True),
        )
        QTest.mouseMove(viewer.image_label, QPoint(1, 1))
        application.processEvents()
        assert shown_tooltips == []
        assert shown_hints == []
        assert viewer.pdf_fullscreen_navigation_hint_timer.isActive()
        viewer._leave_fullscreen()

        image_path = tmp_path / "tooltip-image.png"
        image = QImage(80, 50, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.blue)
        assert image.save(str(image_path))
        viewer.current_image = image_path
        viewer._load_current_image()
        viewer._enter_fullscreen()
        tooltip_event = QEvent(QEvent.Type.ToolTip)
        assert viewer.eventFilter(viewer.image_label, tooltip_event) is True
        assert viewer._fullscreen_tooltip_visible is True
    finally:
        viewer._leave_fullscreen()
        viewer.window.close()
        application.processEvents()


def test_fullscreen_pdf_thumbnail_press_navigates_immediately_during_lazy_render(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "immediate-pages.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)] * 5)
    try:
        _open_pdf(viewer, pdf_path)
        viewer._enter_fullscreen()
        application.processEvents()
        page_two = viewer.pdf_thumbnail_bar.item(1)
        assert page_two is not None
        # A/B regression guard: page navigation must stay correct even while
        # the thumbnail queue is deliberately paused.
        viewer._pause_pdf_thumbnail_rendering()
        QTest.mouseClick(
            viewer.pdf_thumbnail_bar.viewport(),
            Qt.MouseButton.LeftButton,
            pos=viewer.pdf_thumbnail_bar.visualItemRect(page_two).center(),
        )
        assert viewer._pdf_page == 1

        first_page = viewer.pdf_thumbnail_bar.item(0)
        QTest.mouseClick(
            viewer.pdf_thumbnail_bar.viewport(),
            Qt.MouseButton.LeftButton,
            pos=viewer.pdf_thumbnail_bar.visualItemRect(first_page).center(),
        )
        assert viewer._pdf_page == 0

        for page in (2, 3, 4):
            item = viewer.pdf_thumbnail_bar.item(page)
            viewer.pdf_thumbnail_bar.scrollToItem(
                item, QAbstractItemView.ScrollHint.EnsureVisible
            )
            application.processEvents()
            QTest.mouseClick(
                viewer.pdf_thumbnail_bar.viewport(),
                Qt.MouseButton.LeftButton,
                pos=viewer.pdf_thumbnail_bar.visualItemRect(item).center(),
            )
        assert viewer._pdf_page == 4
        assert viewer.pdf_thumbnail_bar.currentRow() == 4
    finally:
        viewer.window.close()
        application.processEvents()


def test_pdf_thumbnail_background_queue_completes_without_overwriting_navigation(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "background-pages.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)] * 20)
    try:
        _open_pdf(viewer, pdf_path)
        viewer._enter_fullscreen()
        application.processEvents()
        item_data_before_rendering = [
            viewer.pdf_thumbnail_bar.item(page).data(Qt.ItemDataRole.UserRole)
            for page in range(viewer.pdf_thumbnail_bar.count())
        ]
        rect_heights_before_rendering = [
            viewer.pdf_thumbnail_bar.visualItemRect(
                viewer.pdf_thumbnail_bar.item(page)
            ).height()
            for page in range(6)
        ]
        assert len(set(rect_heights_before_rendering)) == 1
        page_two = viewer.pdf_thumbnail_bar.item(1)
        QTest.mouseClick(
            viewer.pdf_thumbnail_bar.viewport(),
            Qt.MouseButton.LeftButton,
            pos=viewer.pdf_thumbnail_bar.visualItemRect(page_two).center(),
        )
        assert viewer._pdf_page == 1
        QTest.qWait(350)
        assert viewer._pdf_page == 1
        assert viewer.pdf_thumbnail_busy.isHidden()
        assert viewer._pdf_busy_timer.isActive() is False
        assert len(viewer._pdf_thumbnail_cache) == 20
        assert viewer.pdf_thumbnail_bar.item(19).icon().isNull() is False
        assert [
            viewer.pdf_thumbnail_bar.item(page).data(Qt.ItemDataRole.UserRole)
            for page in range(viewer.pdf_thumbnail_bar.count())
        ] == item_data_before_rendering
        assert [
            viewer.pdf_thumbnail_bar.visualItemRect(
                viewer.pdf_thumbnail_bar.item(page)
            ).height()
            for page in range(6)
        ] == rect_heights_before_rendering
    finally:
        viewer.window.close()
        application.processEvents()


def test_fullscreen_image_does_not_show_the_pdf_page_thumbnail_bar(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    image_path = tmp_path / "plain.png"
    image = QImage(80, 50, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.blue)
    assert image.save(str(image_path))
    try:
        viewer.current_image = image_path
        viewer._load_current_image()
        viewer._enter_fullscreen()
        application.processEvents()
        assert viewer.pdf_thumbnail_bar.isHidden()
    finally:
        viewer._leave_fullscreen()
        viewer.window.close()
        application.processEvents()


def test_pdf_portrait_rendering_preserves_page_aspect_ratio(tmp_path: Path):
    application = QApplication.instance() or QApplication([])
    pdf_path = tmp_path / "portrait.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)])

    result = load_pdf(pdf_path)
    image = render_pdf_page(result.document, 0, QSize(240, 160))

    assert result.error is None
    assert image.size() == QSize(80, 160)
    application.processEvents()


def test_pdf_landscape_rendering_preserves_page_aspect_ratio(tmp_path: Path):
    application = QApplication.instance() or QApplication([])
    pdf_path = tmp_path / "landscape.pdf"
    _write_pdf(pdf_path, [QSizeF(400, 200)])

    result = load_pdf(pdf_path)
    image = render_pdf_page(result.document, 0, QSize(160, 240))

    assert result.error is None
    assert image.size() == QSize(160, 80)
    application.processEvents()


def test_pdf_render_and_thumbnail_sizes_fit_without_distortion(tmp_path: Path):
    application = QApplication.instance() or QApplication([])
    pdf_path = tmp_path / "thumbnail.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)])
    document = load_pdf(pdf_path).document

    assert pdf_page_render_size(document, 0, QSize(500, 300)) == QSize(150, 300)
    assert pdf_page_render_size(document, 0, QSize(160, 120)) == QSize(60, 120)
    application.processEvents()


def test_pdf_render_size_has_a_screen_resolution_limit(tmp_path: Path):
    application = QApplication.instance() or QApplication([])
    pdf_path = tmp_path / "large-render.pdf"
    _write_pdf(pdf_path, [QSizeF(400, 200)])
    document = load_pdf(pdf_path).document

    render_size = pdf_page_render_size(document, 0, QSize(12000, 12000))

    assert max(render_size.width(), render_size.height()) == PDF_SCREEN_RENDER_MAX_EDGE
    assert render_size == QSize(PDF_SCREEN_RENDER_MAX_EDGE, PDF_SCREEN_RENDER_MAX_EDGE // 2)
    application.processEvents()


def test_pdf_display_target_uses_the_actual_viewport_size():
    assert pdf_display_target_size(QSize()) == QSize(1, 1)
    assert pdf_display_target_size(QSize(1, 1)) == QSize(1, 1)


def test_pdf_display_target_accounts_for_hidpi_physical_pixels():
    target = pdf_display_target_size(QSize(1200, 1700), device_pixel_ratio=1.5)

    assert target == QSize(1800, 2550)


def test_pdf_display_target_grows_for_zoom_and_a_larger_viewport():
    normal = pdf_display_target_size(QSize(900, 600), device_pixel_ratio=1.0)
    fullscreen = pdf_display_target_size(QSize(1600, 1000), device_pixel_ratio=1.0)
    zoomed = pdf_display_target_size(QSize(1600, 1000), zoom_factor=2.0)

    assert fullscreen.width() > normal.width()
    assert zoomed.width() > fullscreen.width()


def test_pdf_main_display_render_follows_the_visible_page_size(tmp_path: Path):
    application = QApplication.instance() or QApplication([])
    pdf_path = tmp_path / "display-quality.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)])
    document = load_pdf(pdf_path).document

    thumbnail_size = pdf_page_render_size(document, 0, QSize(160, 120))
    display_size = pdf_page_render_size(
        document,
        0,
        pdf_display_target_size(QSize(500, 400)),
    )

    assert thumbnail_size == QSize(60, 120)
    assert display_size == QSize(200, 400)
    assert display_size.height() > thumbnail_size.height()
    application.processEvents()


def test_many_pdf_pages_render_without_retaining_all_pages(tmp_path: Path):
    application = QApplication.instance() or QApplication([])
    pdf_path = tmp_path / "many-pages.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)] * 100)
    document = load_pdf(pdf_path).document

    assert document.pageCount() == 100
    for page in (0, 1, 50, 99):
        image = render_pdf_page(document, page, QSize(500, 400))
        assert not image.isNull()
        assert image.width() > 0
        assert image.height() > 0
    application.processEvents()


def test_pdf_render_fallback_retries_once_at_half_the_render_size():
    class FailingOnceDocument:
        def __init__(self):
            self.render_sizes: list[QSize] = []

        def pageCount(self) -> int:
            return 1

        def pagePointSize(self, _page: int) -> QSizeF:
            return QSizeF(200, 400)

        def render(self, _page: int, size: QSize) -> QImage:
            self.render_sizes.append(size)
            if len(self.render_sizes) == 1:
                return QImage()
            return QImage(size, QImage.Format.Format_RGB32)

    document = FailingOnceDocument()
    image = render_pdf_page_with_fallback(document, 0, QSize(800, 800))

    assert not image.isNull()
    assert document.render_sizes == [QSize(400, 800), QSize(200, 400)]


def test_transparent_pdf_render_is_composited_onto_opaque_white():
    rendered = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    rendered.fill(Qt.GlobalColor.transparent)

    prepared = prepare_pdf_rendered_image(rendered)

    assert prepared.format() == QImage.Format.Format_ARGB32_Premultiplied
    assert prepared.pixelColor(1, 1) == QColor(Qt.GlobalColor.white)
    assert prepared.pixelColor(1, 1).alpha() == 255


def test_half_transparent_black_pdf_content_is_composited_not_darkened():
    rendered = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    rendered.fill(QColor(0, 0, 0, 128))

    prepared = prepare_pdf_rendered_image(rendered)
    color = prepared.pixelColor(1, 1)

    assert color.alpha() == 255
    assert 126 <= color.red() <= 128
    assert color.red() == color.green() == color.blue()


def test_opaque_pdf_colors_and_rgb_images_remain_color_correct():
    rendered = QImage(4, 4, QImage.Format.Format_RGB32)
    original_color = QColor(35, 130, 220)
    rendered.fill(original_color)

    prepared = prepare_pdf_rendered_image(rendered)

    assert prepared.pixelColor(1, 1) == original_color
    assert rendered.pixelColor(1, 1) == original_color


def test_argb32_pdf_render_is_made_opaque_without_changing_opaque_pixels():
    rendered = QImage(4, 4, QImage.Format.Format_ARGB32)
    original_color = QColor(210, 80, 40, 255)
    rendered.fill(original_color)

    prepared = prepare_pdf_rendered_image(rendered)

    assert prepared.pixelColor(1, 1) == original_color
    assert prepared.pixelColor(1, 1).alpha() == 255


def test_thumbnail_and_full_view_use_the_same_pdf_image_preparation():
    class TransparentDocument:
        def pageCount(self) -> int:
            return 1

        def pagePointSize(self, _page: int) -> QSizeF:
            return QSizeF(200, 400)

        def render(self, _page: int, size: QSize) -> QImage:
            image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            return image

    document = TransparentDocument()
    thumbnail = render_pdf_page(document, 0, QSize(160, 120))
    full_view = render_pdf_page_with_fallback(document, 0, QSize(800, 600))

    assert thumbnail.pixelColor(0, 0) == QColor(Qt.GlobalColor.white)
    assert full_view.pixelColor(0, 0) == QColor(Qt.GlobalColor.white)


def test_one_page_pdf_hides_navigation(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "one.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)])

    _open_pdf(viewer, pdf_path)

    assert viewer.pdf_page_navigation.isHidden()
    assert viewer.pdf_page_label.text() == "Seite 1 von 1"
    assert not viewer.previous_pdf_page_button.isEnabled()
    assert not viewer.next_pdf_page_button.isEnabled()
    viewer.window.close()
    application.processEvents()


def test_pdf_page_buttons_follow_current_page(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "three-pages.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)] * 3)

    _open_pdf(viewer, pdf_path)
    assert not viewer.pdf_page_navigation.isHidden()
    assert viewer.pdf_page_navigation.parentWidget() is viewer.preview_panel
    assert viewer.previous_pdf_page_button.toolTip() == "Vorherige PDF-Seite"
    assert viewer.next_pdf_page_button.toolTip() == "Nächste PDF-Seite"
    assert viewer.previous_pdf_page_button.accessibleName() == "Vorherige PDF-Seite"
    assert viewer.next_pdf_page_button.accessibleName() == "Nächste PDF-Seite"
    assert not viewer.previous_pdf_page_button.isEnabled()
    assert viewer.next_pdf_page_button.isEnabled()

    viewer.next_pdf_page_button.click()
    assert viewer.pdf_page_label.text() == "Seite 2 von 3"
    assert viewer.previous_pdf_page_button.isEnabled()
    assert viewer.next_pdf_page_button.isEnabled()

    viewer.next_pdf_page_button.click()
    assert viewer.pdf_page_label.text() == "Seite 3 von 3"
    assert viewer.previous_pdf_page_button.isEnabled()
    assert not viewer.next_pdf_page_button.isEnabled()
    viewer.window.close()
    application.processEvents()


def test_pdf_to_pdf_transition_detaches_link_model_before_replacing_document(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    first_pdf = tmp_path / "first.pdf"
    second_pdf = tmp_path / "second.pdf"
    _write_pdf(first_pdf, [QSizeF(200, 400)] * 3)
    _write_pdf(second_pdf, [QSizeF(400, 200)] * 2)

    _open_pdf(viewer, first_pdf)
    first_document = viewer._pdf_document
    viewer._pdf_page = 99
    viewer._render_pdf_page()
    assert viewer.pdf_page_label.text() == "Seite 3 von 3"

    _open_pdf(viewer, second_pdf)
    assert viewer._pdf_document is not first_document
    assert viewer._pdf_link_model.document() is viewer._pdf_document
    assert viewer.pdf_page_label.text() == "Seite 1 von 2"
    viewer.window.close()
    application.processEvents()


def test_failed_pdf_page_render_keeps_the_visible_page_index(tmp_path: Path, monkeypatch):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "fallback.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)] * 3)
    _open_pdf(viewer, pdf_path)

    monkeypatch.setattr(
        bildbetrachter,
        "render_pdf_page_with_fallback",
        lambda *_args: QImage(),
    )
    viewer._change_pdf_page(1)

    assert viewer._pdf_page == 0
    assert viewer.pdf_page_label.text() == "Seite 1 von 3"
    assert viewer.image_label.text() == "Die PDF-Seite konnte nicht gerendert werden"
    viewer.window.close()
    application.processEvents()


def test_pdf_quality_refresh_rerenders_when_target_render_size_changes(
    tmp_path: Path, monkeypatch
):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "quality-refresh.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)])
    _open_pdf(viewer, pdf_path)
    rendered_pages: list[tuple[int | None, bool]] = []
    render_scale = viewer._zoom_factor if viewer._zoom_mode == "manual" else 1.0
    required_size = pdf_page_render_size(
        viewer._pdf_document,
        viewer._pdf_page,
        pdf_display_target_size(
            viewer.image_scroll_area.viewport().size(),
            render_scale,
            viewer.image_scroll_area.viewport().devicePixelRatioF(),
        ),
    )

    monkeypatch.setattr(
        viewer,
        "_render_pdf_page",
        lambda page, schedule_quality_refresh: rendered_pages.append(
            (page, schedule_quality_refresh)
        ),
    )
    viewer._pdf_render_size = QSize(
        max(1, required_size.width() // 2),
        max(1, required_size.height() // 2),
    )
    viewer._refresh_pdf_render_quality()
    assert rendered_pages == [(0, False)]

    rendered_pages.clear()
    viewer._pdf_render_size = QSize(required_size.width() * 2, required_size.height() * 2)
    viewer._refresh_pdf_render_quality()
    assert rendered_pages == [(0, False)]

    rendered_pages.clear()
    viewer._pdf_render_size = required_size
    viewer._refresh_pdf_render_quality()
    assert rendered_pages == []
    viewer.window.close()
    application.processEvents()


def test_pdf_to_jpg_transition_detaches_link_model(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "document.pdf"
    image_path = tmp_path / "photo.jpg"
    _write_pdf(pdf_path, [QSizeF(200, 400)])
    image = QImage(120, 80, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.red)
    assert image.save(str(image_path))

    _open_pdf(viewer, pdf_path)
    _open_pdf(viewer, image_path)

    assert viewer._pdf_document is None
    assert viewer._pdf_link_model.document() is None
    assert viewer.pdf_page_navigation.isHidden()
    assert viewer.pdf_page_label.text() == ""
    viewer.window.close()
    application.processEvents()


def test_page_shortcuts_use_the_same_navigation_logic(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "shortcuts.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)] * 3)
    _open_pdf(viewer, pdf_path)

    assert viewer.next_pdf_page_action.shortcut() == Qt.Key.Key_PageDown
    assert viewer.previous_pdf_page_action.shortcut() == Qt.Key.Key_PageUp
    viewer.window.activateWindow()
    viewer.image_label.setFocus()
    application.processEvents()
    QTest.keyClick(viewer.window, Qt.Key.Key_PageDown)
    assert viewer.pdf_page_label.text() == "Seite 2 von 3"
    QTest.keyClick(viewer.window, Qt.Key.Key_PageUp)
    assert viewer.pdf_page_label.text() == "Seite 1 von 3"
    viewer.window.close()
    application.processEvents()


def test_fullscreen_hides_thumbnail_container_and_restores_splitters(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    image_path = tmp_path / "fullscreen.png"
    image = QImage(120, 80, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.blue)
    assert image.save(str(image_path))
    _open_pdf(viewer, image_path)
    main_sizes = viewer.splitter.sizes()
    right_sizes = viewer.right_splitter.sizes()

    viewer._enter_fullscreen()
    application.processEvents()
    assert viewer.thumbnail_panel.isHidden()
    assert viewer.directory_panel.isHidden()
    assert viewer.status_bar.isHidden()
    assert not viewer.image_scroll_area.isHidden()

    viewer._leave_fullscreen()
    application.processEvents()
    assert not viewer.status_bar.isHidden()
    assert not viewer.thumbnail_panel.isHidden()
    assert not viewer.directory_panel.isHidden()
    assert viewer.splitter.sizes() == main_sizes
    assert viewer.right_splitter.sizes() == right_sizes
    viewer.window.close()
    application.processEvents()


def test_fullscreen_state_is_stable_for_a_pdf(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "fullscreen.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)] * 2)
    _open_pdf(viewer, pdf_path)

    for _ in range(2):
        viewer._enter_fullscreen()
        application.processEvents()
        assert viewer.thumbnail_panel.isHidden()
        assert viewer.pdf_page_navigation.isHidden()
        assert viewer.preview_panel.layout().indexOf(viewer.pdf_page_navigation) == -1
        assert viewer.preview_content.height() == viewer.preview_panel.contentsRect().height()
        assert viewer.pdf_print_button.isVisible()
        assert viewer.pdf_print_bar.height() == viewer.pdf_print_button.sizeHint().height() + 11
        assert viewer.pdf_thumbnail_content.geometry().bottom() < viewer.pdf_print_bar.geometry().top()
        assert viewer.pdf_print_bar.rect().contains(viewer.pdf_print_button.geometry())
        QTest.mouseMove(
            viewer.image_scroll_area.viewport(),
            QPoint(
                viewer.image_scroll_area.viewport().width() // 2,
                viewer.image_scroll_area.viewport().height() - 1,
            ),
        )
        application.processEvents()
        assert viewer.pdf_page_navigation.isHidden()
        assert viewer.status_bar.isHidden()
        viewer._change_pdf_page(1)
        assert viewer.pdf_page_label.text() == "Seite 2 von 2"
        viewer._leave_fullscreen()
        application.processEvents()
        assert not viewer.thumbnail_panel.isHidden()
        assert viewer.preview_panel.layout().indexOf(viewer.pdf_page_navigation) >= 0
        assert not viewer.pdf_page_navigation.isHidden()
    viewer.window.close()
    application.processEvents()


def test_pdf_print_choice_passes_current_or_all_pages(tmp_path: Path, monkeypatch):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "print-pages.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)] * 4)
    _open_pdf(viewer, pdf_path)
    viewer._render_pdf_page(2)
    printed: list[list[int]] = []
    monkeypatch.setattr(viewer, "_print_pdf_pages", lambda pages: printed.append(pages))

    def choose(label: str) -> None:
        def click_button():
            dialog = application.activeModalWidget()
            for button in dialog.buttons():
                if button.text() == label:
                    button.click()
                    return
        QTimer.singleShot(0, click_button)
        viewer._choose_pdf_pages_to_print()

    choose("Aktuelle Seite")
    choose("Alle Seiten")
    viewer._pdf_print_selection = {3, 1}
    choose("Auswahl")
    choose("Abbrechen")

    assert printed == [[2], [0, 1, 2, 3], [1, 3]]
    assert viewer._pdf_page == 2
    viewer.window.close()
    application.processEvents()


def test_pdf_print_selection_option_tracks_checkbox_state(tmp_path: Path):
    application, viewer = _viewer(tmp_path)
    pdf_path = tmp_path / "selection-option.pdf"
    _write_pdf(pdf_path, [QSizeF(200, 400)] * 2)
    _open_pdf(viewer, pdf_path)
    viewer._enter_fullscreen()
    application.processEvents()
    enabled_states: list[bool] = []

    def inspect_and_cancel():
        dialog = application.activeModalWidget()
        selection = next(button for button in dialog.buttons() if button.text() == "Auswahl")
        enabled_states.append(selection.isEnabled())
        next(button for button in dialog.buttons() if button.text() == "Abbrechen").click()

    QTimer.singleShot(0, inspect_and_cancel)
    viewer._choose_pdf_pages_to_print()
    viewer._pdf_print_checkboxes[1].click()
    QTimer.singleShot(0, inspect_and_cancel)
    viewer._choose_pdf_pages_to_print()

    assert enabled_states == [False, True]
    assert viewer._pdf_page == 0
    viewer.window.close()
    application.processEvents()
