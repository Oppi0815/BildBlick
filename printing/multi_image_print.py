from dataclasses import dataclass
from datetime import datetime
from math import ceil
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter

from printing.layout import ImageSourceInfo, MultiImagePrintDocument, PageSizeMm, RectMm

if TYPE_CHECKING:
    from printing.printer_geometry import PrinterGeometryMm


OUTER_MARGIN_MM = 5.0
CELL_SPACING_MM = 4.0


@dataclass
class MultiImagePrintSettings:
    source: str = "current"
    orientation: str = "automatic"
    images_per_page: int = 4
    custom_rows: int = 4
    custom_columns: int = 3
    page_margin_mm: float = OUTER_MARGIN_MM
    cell_spacing_mm: float = CELL_SPACING_MM
    contact_sheet: bool = False
    show_filename: bool = True
    show_capture_date: bool = False
    show_page_number: bool = True
    show_header: bool = False
    header_text: str = ""
    use_folder_name_as_title: bool = False
    show_print_date: bool = False
    show_folder_in_footer: bool = False
    footer_folder_name: str = ""

    @property
    def is_custom(self) -> bool:
        return self.images_per_page == 0

    @property
    def effective_images_per_page(self) -> int:
        return self.custom_rows * self.custom_columns if self.is_custom else self.images_per_page


def ordered_paths_for_source(
    source: str,
    visible_paths: list[Path],
    current_path: Path | None = None,
    selected_paths: list[Path] | None = None,
) -> list[Path]:
    """Freeze print order from the visible thumbnail order.

    ``selected_paths`` is treated as membership only: it intentionally cannot
    impose the arbitrary order returned by Qt's ``selectedItems()``.
    """

    if source == "current":
        return [current_path] if current_path is not None else []
    if source == "all":
        return list(visible_paths)
    if source == "selected":
        selected = {path.resolve(strict=False) for path in selected_paths or []}
        return [path for path in visible_paths if path.resolve(strict=False) in selected]
    raise ValueError("Unbekannte Bildquelle.")


def multi_image_document_from_settings(
    sources: list[ImageSourceInfo] | tuple[ImageSourceInfo, ...],
    settings: MultiImagePrintSettings,
    page_size: PageSizeMm | None = None,
    printable_rect: RectMm | None = None,
    *,
    source_kind: str | None = None,
    folder_name: str = "",
    print_date_text: str = "",
    landscape: bool | None = None,
    printer_geometry: "PrinterGeometryMm | None" = None,
) -> MultiImagePrintDocument:
    """Adapt all existing multi-print settings into the common document model."""

    if settings.is_custom and (settings.custom_rows <= 0 or settings.custom_columns <= 0):
        raise ValueError("Rasterzeilen und -spalten müssen größer als 0 sein.")
    ordered_sources = tuple(sources)
    if landscape is None:
        landscape = settings.orientation == "landscape" or (
            settings.orientation == "automatic"
            and settings.effective_images_per_page == 1
            and bool(ordered_sources)
            and ordered_sources[0].pixel_width > ordered_sources[0].pixel_height
        )
    orientation = "landscape" if landscape else "portrait"
    if printer_geometry is not None:
        if page_size is not None or printable_rect is not None:
            raise ValueError("Druckergeometrie kann nicht mit separatem Papierformat kombiniert werden.")
        physical_page = printer_geometry.page_size
        paint_rect = printer_geometry.paint_rect
        # The accepted QPrintDialog geometry is authoritative; this avoids a
        # second, stale orientation correction during final printing.
        landscape = physical_page.width_mm > physical_page.height_mm
        orientation = "landscape" if landscape else "portrait"
    else:
        physical_page = (page_size or PageSizeMm.a4()).for_orientation(orientation)
        paint_rect = printable_rect or RectMm(0.0, 0.0, physical_page.width_mm, physical_page.height_mm)
    if (
        paint_rect.x_mm < 0 or paint_rect.y_mm < 0
        or paint_rect.right_mm > physical_page.width_mm
        or paint_rect.bottom_mm > physical_page.height_mm
    ):
        raise ValueError("Der bedruckbare Bereich liegt außerhalb des Papierformats.")
    rows, columns = (
        (settings.custom_rows, settings.custom_columns)
        if settings.is_custom else grid_for(settings.effective_images_per_page, landscape)
    )
    return MultiImagePrintDocument(
        sources=ordered_sources,
        source_kind=source_kind or settings.source,
        page_size=physical_page,
        printable_rect=paint_rect,
        rows=rows,
        columns=columns,
        page_margin_mm=settings.page_margin_mm,
        cell_spacing_mm=settings.cell_spacing_mm,
        orientation=orientation,
        contact_sheet=settings.contact_sheet,
        show_filename=settings.show_filename,
        show_capture_date=settings.show_capture_date,
        show_page_number=settings.show_page_number,
        show_header=settings.show_header,
        header_text=effective_header_text(settings),
        use_folder_name_as_title=settings.use_folder_name_as_title,
        folder_name=folder_name or effective_footer_folder_name(settings),
        show_folder_in_footer=settings.show_folder_in_footer,
        show_print_date=settings.show_print_date,
        print_date_text=print_date_text,
    )


@dataclass(frozen=True)
class MultiImageCellLayout:
    image_index: int
    rect: QRectF
    image_rect: QRectF
    caption_rect: QRectF
    filename_rect: QRectF
    date_rect: QRectF


@dataclass(frozen=True)
class MultiImagePageLayout:
    page_index: int
    page_count: int
    rows: int
    columns: int
    cells: list[MultiImageCellLayout]
    header_rect: QRectF
    grid_rect: QRectF
    footer_rect: QRectF
    valid: bool = True


def grid_for(images_per_page: int, landscape: bool) -> tuple[int, int]:
    grids = {1: (1, 1), 4: (2, 2), 9: (3, 3), 16: (4, 4), 32: (8, 4)}
    if images_per_page == 2:
        return (1, 2) if landscape else (2, 1)
    if images_per_page == 6:
        return (2, 3) if landscape else (3, 2)
    if images_per_page == 32 and landscape:
        return 4, 8
    return grids[images_per_page]


def mm_to_pixels(value: float, resolution: int) -> float:
    return value / 25.4 * resolution


def effective_header_text(settings: MultiImagePrintSettings) -> str:
    if not settings.show_header:
        return ""
    return settings.header_text.strip() if isinstance(settings.header_text, str) else ""


def folder_title_from_path(directory: Path | None) -> str:
    if not isinstance(directory, Path) or directory.parent == directory:
        return ""
    return directory.name


def current_print_date_text() -> str:
    return datetime.now().strftime("%d.%m.%Y")


def effective_footer_folder_name(settings: MultiImagePrintSettings) -> str:
    if not settings.show_folder_in_footer:
        return ""
    return (
        settings.footer_folder_name.strip()
        if isinstance(settings.footer_folder_name, str) else ""
    )


def draw_multi_print_header(
    painter: QPainter,
    layout: MultiImagePageLayout,
    settings: MultiImagePrintSettings,
) -> None:
    text = effective_header_text(settings)
    if not text or layout.header_rect.isEmpty():
        return
    painter.save()
    font = QFont(painter.font())
    font.setBold(True)
    font.setPixelSize(max(7, int(layout.header_rect.height() * 0.70)))
    painter.setFont(font)
    painter.setPen(QColor("#202020"))
    displayed_text = painter.fontMetrics().elidedText(
        text,
        Qt.TextElideMode.ElideRight,
        max(0, int(layout.header_rect.width())),
    )
    painter.drawText(
        layout.header_rect,
        Qt.AlignmentFlag.AlignCenter,
        displayed_text,
    )
    painter.restore()


def draw_multi_print_footer(
    painter: QPainter,
    layout: MultiImagePageLayout,
    settings: MultiImagePrintSettings,
    page_number: int,
    page_count: int,
    print_date_text: str,
) -> None:
    if layout.footer_rect.isEmpty():
        return
    folder_name = effective_footer_folder_name(settings)
    page_text = (
        f"Seite {page_number} von {page_count}"
        if settings.show_page_number else ""
    )
    date_text = print_date_text if settings.show_print_date else ""
    painter.save()
    font = QFont(painter.font())
    font.setPixelSize(max(6, int(layout.footer_rect.height() * 0.55)))
    painter.setFont(font)
    painter.setPen(QColor("#202020"))
    metrics = painter.fontMetrics()
    footer_width = layout.footer_rect.width()
    minimum_center_width = metrics.horizontalAdvance(page_text) + 8
    center_width = min(
        footer_width,
        max(footer_width / 3.0, minimum_center_width) if page_text else footer_width / 3.0,
    )
    center_x = layout.footer_rect.center().x() - center_width / 2.0
    left_rect = QRectF(
        layout.footer_rect.x(), layout.footer_rect.y(),
        max(0.0, center_x - layout.footer_rect.x()),
        layout.footer_rect.height(),
    )
    center_rect = QRectF(
        center_x, layout.footer_rect.y(), center_width,
        layout.footer_rect.height(),
    )
    right_rect = QRectF(
        center_rect.right(), layout.footer_rect.y(),
        max(0.0, layout.footer_rect.right() - center_rect.right()),
        layout.footer_rect.height(),
    )
    folder_text = metrics.elidedText(
        folder_name,
        Qt.TextElideMode.ElideRight,
        max(0, int(left_rect.width())),
    )
    page_text = metrics.elidedText(
        page_text,
        Qt.TextElideMode.ElideRight,
        max(0, int(center_rect.width())),
    )
    date_text = metrics.elidedText(
        date_text,
        Qt.TextElideMode.ElideRight,
        max(0, int(right_rect.width())),
    )
    painter.drawText(
        left_rect,
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        folder_text,
    )
    painter.drawText(
        center_rect,
        Qt.AlignmentFlag.AlignCenter,
        page_text,
    )
    painter.drawText(
        right_rect,
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        date_text,
    )
    painter.restore()


def fitted_rect(image_size: QSize, rect: QRectF) -> QRectF:
    scale = min(rect.width() / image_size.width(), rect.height() / image_size.height())
    width, height = image_size.width() * scale, image_size.height() * scale
    return QRectF(
        rect.x() + (rect.width() - width) / 2,
        rect.y() + (rect.height() - height) / 2,
        width, height,
    )


def calculate_multi_image_page(
    image_sizes: list[QSize], drawable_rect: QRectF, images_per_page: int,
    resolution: int, landscape: bool, page_index: int, contact_sheet: bool = False,
    show_filename: bool = False, show_capture_date: bool = False,
    show_page_number: bool = False, custom_rows: int | None = None,
    custom_columns: int | None = None, page_margin_mm: float | None = None,
    cell_spacing_mm: float | None = None,
    settings: MultiImagePrintSettings | None = None,
) -> MultiImagePageLayout:
    if settings is not None:
        images_per_page = settings.effective_images_per_page
        custom_rows = settings.custom_rows if settings.is_custom else None
        custom_columns = settings.custom_columns if settings.is_custom else None
        page_margin_mm = settings.page_margin_mm
        cell_spacing_mm = settings.cell_spacing_mm
        contact_sheet = settings.contact_sheet
        show_filename = settings.show_filename
        show_capture_date = settings.show_capture_date
        show_page_number = settings.show_page_number
    rows, columns = custom_rows or grid_for(images_per_page, landscape)[0], custom_columns or grid_for(images_per_page, landscape)[1]
    page_count = max(1, ceil(len(image_sizes) / images_per_page))
    margin_mm = page_margin_mm if page_margin_mm is not None else (4.0 if images_per_page == 32 else OUTER_MARGIN_MM)
    spacing_mm = cell_spacing_mm if cell_spacing_mm is not None else (2.0 if images_per_page == 32 else CELL_SPACING_MM)
    margin = mm_to_pixels(margin_mm, resolution)
    spacing = mm_to_pixels(spacing_mm, resolution)
    footer_folder_name = (
        effective_footer_folder_name(settings) if settings is not None else ""
    )
    show_footer = (
        show_page_number
        or (settings.show_print_date if settings is not None else False)
        or bool(footer_folder_name)
    )
    footer_height = mm_to_pixels(6.0, resolution) if show_footer else 0.0
    content = drawable_rect.adjusted(margin, margin, -margin, -margin - footer_height)
    header_text = effective_header_text(settings) if settings is not None else ""
    header_rect = QRectF()
    grid_rect = QRectF(content)
    if header_text:
        header_height = max(
            mm_to_pixels(7.0, resolution),
            resolution * 14.0 / 72.0 * 1.45,
        )
        header_gap = mm_to_pixels(2.0, resolution)
        header_rect = QRectF(
            content.x(), content.y(), content.width(), header_height
        )
        grid_rect.adjust(0.0, header_height + header_gap, 0.0, 0.0)
    cell_width = (grid_rect.width() - spacing * (columns - 1)) / columns
    cell_height = (grid_rect.height() - spacing * (rows - 1)) / rows
    footer_rect = (
        QRectF(content.x(), content.bottom() + margin, content.width(), footer_height)
        if show_footer else QRectF()
    )
    if (
        rows <= 0
        or columns <= 0
        or grid_rect.width() <= 0
        or grid_rect.height() <= 0
        or cell_width <= 0
        or cell_height <= 0
    ):
        return MultiImagePageLayout(
            page_index, page_count, rows, columns, [], header_rect,
            grid_rect, footer_rect, False,
        )
    cells = []
    first_index = page_index * images_per_page
    for offset, image_size in enumerate(image_sizes[first_index:first_index + images_per_page]):
        row, column = divmod(offset, columns)
        rect = QRectF(
            grid_rect.x() + column * (cell_width + spacing),
            grid_rect.y() + row * (cell_height + spacing), cell_width, cell_height,
        )
        line_height = mm_to_pixels(4.2, resolution)
        show_filename_for_cell = contact_sheet and show_filename
        show_date_for_cell = contact_sheet and show_capture_date
        if show_filename_for_cell and show_date_for_cell:
            minimum_height_for_date = line_height * 4 + mm_to_pixels(1.2, resolution)
            show_date_for_cell = rect.height() >= minimum_height_for_date
        line_count = int(show_filename_for_cell) + int(show_date_for_cell)
        caption_height = line_count * line_height + (mm_to_pixels(1.2, resolution) if line_count else 0)
        caption_height = min(caption_height, rect.height())
        caption_rect = QRectF(rect.x(), rect.bottom() - caption_height, rect.width(), caption_height)
        image_area = QRectF(rect.x(), rect.y(), rect.width(), max(0.0, rect.height() - caption_height))
        text_line_height = caption_height / line_count if line_count else 0.0
        filename_rect = QRectF(caption_rect.x(), caption_rect.y(), caption_rect.width(), text_line_height) if show_filename_for_cell else QRectF()
        date_y = caption_rect.y() + (text_line_height if show_filename_for_cell else 0.0)
        date_rect = QRectF(caption_rect.x(), date_y, caption_rect.width(), text_line_height) if show_date_for_cell else QRectF()
        cells.append(MultiImageCellLayout(first_index + offset, rect, fitted_rect(image_size, image_area), caption_rect, filename_rect, date_rect))
    return MultiImagePageLayout(
        page_index, page_count, rows, columns, cells, header_rect, grid_rect,
        footer_rect,
    )
