from PySide6.QtCore import QRectF, QSize

from printing.multi_image_print import MultiImagePrintSettings, calculate_multi_image_page


def test_fixed_and_custom_layouts_are_valid():
    sizes = [QSize(1600, 900)] * 100
    for settings in (
        MultiImagePrintSettings(images_per_page=4),
        MultiImagePrintSettings(images_per_page=0, custom_rows=4, custom_columns=3),
        MultiImagePrintSettings(images_per_page=0, custom_rows=10, custom_columns=10),
    ):
        page = calculate_multi_image_page(sizes, QRectF(0, 0, 2400, 3400), settings.effective_images_per_page, 300, False, 0, settings=settings)
        assert page.valid


def test_invalid_small_page_is_reported():
    settings = MultiImagePrintSettings(images_per_page=0, custom_rows=12, custom_columns=12, page_margin_mm=30, cell_spacing_mm=20)
    page = calculate_multi_image_page([QSize(10, 10)], QRectF(0, 0, 300, 400), settings.effective_images_per_page, 300, False, 0, settings=settings)
    assert not page.valid


def test_small_contact_sheet_keeps_filename_and_hides_date():
    settings = MultiImagePrintSettings(
        images_per_page=32,
        contact_sheet=True,
        show_filename=True,
        show_capture_date=True,
    )
    page = calculate_multi_image_page(
        [QSize(1600, 900)] * 32,
        QRectF(0, 0, 600, 800),
        settings.effective_images_per_page,
        300,
        False,
        0,
        settings=settings,
    )
    assert page.valid
    assert all(not cell.filename_rect.isEmpty() for cell in page.cells)
    assert any(cell.date_rect.isEmpty() for cell in page.cells)
    assert all(cell.image_rect.width() >= 0 and cell.image_rect.height() >= 0 for cell in page.cells)


def test_header_space_is_only_reserved_for_nonempty_text():
    base = MultiImagePrintSettings(images_per_page=4)
    empty_header = MultiImagePrintSettings(
        images_per_page=4, show_header=True, header_text="   "
    )
    with_header = MultiImagePrintSettings(
        images_per_page=4, show_header=True, header_text="Familienfotos 2012"
    )
    drawable = QRectF(0, 0, 2400, 3400)
    base_page = calculate_multi_image_page(
        [QSize(1600, 900)] * 4, drawable, 4, 300, False, 0, settings=base
    )
    empty_page = calculate_multi_image_page(
        [QSize(1600, 900)] * 4, drawable, 4, 300, False, 0,
        settings=empty_header,
    )
    header_page = calculate_multi_image_page(
        [QSize(1600, 900)] * 4, drawable, 4, 300, False, 0,
        settings=with_header,
    )
    assert base_page.header_rect.isEmpty()
    assert empty_page.header_rect.isEmpty()
    assert empty_page.grid_rect == base_page.grid_rect
    assert header_page.valid
    assert not header_page.header_rect.isEmpty()
    assert header_page.grid_rect.top() > header_page.header_rect.bottom()
    assert header_page.grid_rect.height() < base_page.grid_rect.height()


def test_header_and_footer_do_not_overlap_grid():
    settings = MultiImagePrintSettings(
        images_per_page=9,
        show_header=True,
        header_text="Eine sehr lange Überschrift " * 30,
        show_page_number=True,
    )
    page = calculate_multi_image_page(
        [QSize(1600, 900)] * 9,
        QRectF(0, 0, 1800, 2500),
        9,
        300,
        False,
        0,
        settings=settings,
    )
    assert page.valid
    assert page.header_rect.bottom() < page.grid_rect.top()
    assert page.grid_rect.bottom() < page.footer_rect.top()
    assert all(
        cell.rect.width() >= 0 and cell.rect.height() >= 0 for cell in page.cells
    )


def test_header_handles_small_and_invalid_layouts():
    small = MultiImagePrintSettings(
        images_per_page=1, show_header=True, header_text="A6"
    )
    page = calculate_multi_image_page(
        [QSize(1600, 900)], QRectF(0, 0, 900, 1300), 1, 300, False, 0,
        settings=small,
    )
    assert page.valid
    custom = MultiImagePrintSettings(
        images_per_page=0,
        custom_rows=3,
        custom_columns=4,
        show_header=True,
        header_text="Raster",
    )
    page = calculate_multi_image_page(
        [QSize(1600, 900)] * 12, QRectF(0, 0, 2400, 3400), 12, 300,
        False, 0, settings=custom,
    )
    assert page.valid
    assert (page.rows, page.columns) == (3, 4)
    invalid = MultiImagePrintSettings(
        images_per_page=1,
        page_margin_mm=30,
        show_header=True,
        header_text="Zu wenig Platz",
    )
    page = calculate_multi_image_page(
        [QSize(10, 10)], QRectF(0, 0, 300, 400), 1, 300, False, 0,
        settings=invalid,
    )
    assert not page.valid


def test_footer_is_only_reserved_when_content_is_enabled():
    drawable = QRectF(0, 0, 2400, 3400)
    no_footer = MultiImagePrintSettings(
        images_per_page=4, show_page_number=False
    )
    page_number = MultiImagePrintSettings(images_per_page=4)
    date_only = MultiImagePrintSettings(
        images_per_page=4, show_page_number=False, show_print_date=True
    )
    empty_folder = MultiImagePrintSettings(
        images_per_page=4,
        show_page_number=False,
        show_folder_in_footer=True,
    )
    folder_only = MultiImagePrintSettings(
        images_per_page=4,
        show_page_number=False,
        show_folder_in_footer=True,
        footer_folder_name="Urlaub Südafrika",
    )
    pages = [
        calculate_multi_image_page([QSize(1600, 900)] * 4, drawable, 4, 300, False, 0, settings=settings)
        for settings in (no_footer, page_number, date_only, empty_folder, folder_only)
    ]
    assert pages[0].footer_rect.isEmpty()
    assert pages[3].footer_rect.isEmpty()
    assert not pages[1].footer_rect.isEmpty()
    assert not pages[2].footer_rect.isEmpty()
    assert not pages[4].footer_rect.isEmpty()
    assert pages[0].grid_rect.height() > pages[1].grid_rect.height()


def test_extended_footer_does_not_overlap_header_or_grid():
    settings = MultiImagePrintSettings(
        images_per_page=9,
        show_header=True,
        header_text="Familienfotos",
        show_page_number=True,
        show_print_date=True,
        show_folder_in_footer=True,
        footer_folder_name="Ein außergewöhnlich langer Ordnername " * 20,
    )
    page = calculate_multi_image_page(
        [QSize(1600, 900)] * 9,
        QRectF(0, 0, 1800, 2500),
        9,
        300,
        False,
        0,
        settings=settings,
    )
    assert page.valid
    assert page.header_rect.bottom() < page.grid_rect.top()
    assert page.grid_rect.bottom() < page.footer_rect.top()
    assert all(cell.rect.width() >= 0 and cell.rect.height() >= 0 for cell in page.cells)


def test_extended_footer_handles_small_and_invalid_pages():
    small = MultiImagePrintSettings(
        images_per_page=1,
        show_page_number=False,
        show_print_date=True,
        show_folder_in_footer=True,
        footer_folder_name="A6",
    )
    page = calculate_multi_image_page(
        [QSize(1600, 900)], QRectF(0, 0, 900, 1300), 1, 300, False, 0,
        settings=small,
    )
    assert page.valid
    invalid = MultiImagePrintSettings(
        images_per_page=1,
        page_margin_mm=30,
        show_print_date=True,
        show_folder_in_footer=True,
        footer_folder_name="Zu wenig Platz",
    )
    page = calculate_multi_image_page(
        [QSize(10, 10)], QRectF(0, 0, 300, 400), 1, 300, False, 0,
        settings=invalid,
    )
    assert not page.valid
