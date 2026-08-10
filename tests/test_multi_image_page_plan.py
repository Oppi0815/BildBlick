from pathlib import Path

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from printing.layout import ImageSourceInfo, PageSizeMm, RectMm
from printing.multi_image_print import (
    MultiImagePrintSettings,
    multi_image_document_from_settings,
    ordered_paths_for_source,
)
from printing.planner import plan_multi_image_pages
from printing.renderer import render_page_plan


def sources(count: int) -> list[ImageSourceInfo]:
    return [
        ImageSourceInfo(Path(f"{index}.jpg"), 1600, 900, filename=f"{index}.jpg", capture_date="10.08.2026")
        for index in range(count)
    ]


def test_source_order_is_frozen_from_visible_thumbnail_order():
    visible = [Path("third.jpg"), Path("first.jpg"), Path("second.jpg")]
    assert ordered_paths_for_source("all", visible) == visible
    assert ordered_paths_for_source("selected", visible, selected_paths=[visible[2], visible[0]]) == [visible[0], visible[2]]
    assert ordered_paths_for_source("current", visible, visible[1]) == [visible[1]]


@pytest.mark.parametrize("count,rows,columns", [(4, 2, 2), (9, 3, 3), (16, 4, 4), (32, 8, 4), (6, 3, 2)])
def test_adapter_preserves_grid_and_page_breaks(count, rows, columns):
    settings = MultiImagePrintSettings(
        images_per_page=0 if count == 6 else count,
        custom_rows=rows,
        custom_columns=columns,
        page_margin_mm=5,
        cell_spacing_mm=4,
    )
    document = multi_image_document_from_settings(sources(count + 1), settings)
    pages = plan_multi_image_pages(document)
    assert (document.rows, document.columns) == (rows, columns)
    assert [len(page.image_elements) for page in pages] == [count, 1]
    assert [page.page_number for page in pages] == [1, 2]


def test_plan_contains_mm_caption_header_and_footer_regions_without_overlap():
    settings = MultiImagePrintSettings(
        images_per_page=4,
        contact_sheet=True,
        show_filename=True,
        show_capture_date=True,
        show_header=True,
        header_text="Urlaub",
        show_folder_in_footer=True,
        footer_folder_name="Fotos",
        show_print_date=True,
    )
    document = multi_image_document_from_settings(sources(5), settings, print_date_text="10.08.2026")
    page = plan_multi_image_pages(document)[0]
    roles = {text.semantic_role for text in page.text_elements}
    assert {"header", "filename", "capture_date", "folder", "print_date", "page_number"} <= roles
    header = next(text.rect for text in page.text_elements if text.semantic_role == "header")
    footer = next(text.rect for text in page.text_elements if text.semantic_role == "page_number")
    assert all(image.target_rect.y_mm >= header.bottom_mm for image in page.image_elements)
    assert all(image.target_rect.bottom_mm < footer.y_mm for image in page.image_elements)
    assert isinstance(page.image_elements[0].target_rect, RectMm)


def test_adapter_rejects_invalid_printable_area_and_unknown_source():
    with pytest.raises(ValueError):
        ordered_paths_for_source("wrong", [])
    with pytest.raises(ValueError):
        multi_image_document_from_settings(
            sources(1), MultiImagePrintSettings(), PageSizeMm.a4(), RectMm(0, 0, 220, 297)
        )


def test_adapter_carries_every_profile_relevant_setting_and_renderer_uses_plan():
    settings = MultiImagePrintSettings(
        source="selected", orientation="landscape", images_per_page=0,
        custom_rows=2, custom_columns=3, page_margin_mm=6, cell_spacing_mm=3,
        contact_sheet=True, show_filename=True, show_capture_date=True,
        show_page_number=True, show_header=True, header_text="Titel",
        use_folder_name_as_title=True, show_print_date=True,
        show_folder_in_footer=True, footer_folder_name="Ordner",
    )
    document = multi_image_document_from_settings(sources(7), settings, print_date_text="10.08.2026")
    assert (document.source_kind, document.orientation, document.rows, document.columns) == ("selected", "landscape", 2, 3)
    assert document.use_folder_name_as_title and document.contact_sheet
    assert (document.page_margin_mm, document.cell_spacing_mm, document.folder_name) == (6, 3, "Ordner")
    pages = plan_multi_image_pages(document)
    assert [len(page.image_elements) for page in pages] == [6, 1]
    app = QApplication.instance() or QApplication([])
    canvas = QImage(600, 420, QImage.Format.Format_ARGB32)
    canvas.fill(QColor("white"))
    painter = QPainter(canvas)
    render_page_plan(painter, pages[0], QRectF(0, 0, 600, 420), lambda _: QImage(40, 20, QImage.Format.Format_ARGB32))
    painter.end()
    targets = [image.target_rect for image in pages[0].image_elements]
    assert all(not (left.right_mm > right.x_mm and right.right_mm > left.x_mm and left.bottom_mm > right.y_mm and right.bottom_mm > left.y_mm) for index, left in enumerate(targets) for right in targets[index + 1:])
