from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

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


def ordered_paths_for_source(source: str, visible_paths: list[Path], current_path: Path | None = None, selected_paths: list[Path] | None = None) -> list[Path]:
    """Freeze print order from the visible thumbnail order."""
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
    *, source_kind: str | None = None, folder_name: str = "", print_date_text: str = "",
    landscape: bool | None = None, printer_geometry: "PrinterGeometryMm | None" = None,
) -> MultiImagePrintDocument:
    """Adapt print settings into the shared output document model."""
    if settings.is_custom and (settings.custom_rows <= 0 or settings.custom_columns <= 0):
        raise ValueError("Rasterzeilen und -spalten müssen größer als 0 sein.")
    ordered_sources = tuple(sources)
    if landscape is None:
        landscape = settings.orientation == "landscape" or (
            settings.orientation == "automatic" and settings.effective_images_per_page == 1
            and bool(ordered_sources) and ordered_sources[0].pixel_width > ordered_sources[0].pixel_height
        )
    orientation = "landscape" if landscape else "portrait"
    if printer_geometry is not None:
        if page_size is not None or printable_rect is not None:
            raise ValueError("Druckergeometrie kann nicht mit separatem Papierformat kombiniert werden.")
        physical_page, paint_rect = printer_geometry.page_size, printer_geometry.paint_rect
        orientation = "landscape" if physical_page.width_mm > physical_page.height_mm else "portrait"
    else:
        physical_page = (page_size or PageSizeMm.a4()).for_orientation(orientation)
        paint_rect = printable_rect or RectMm(0.0, 0.0, physical_page.width_mm, physical_page.height_mm)
    if paint_rect.x_mm < 0 or paint_rect.y_mm < 0 or paint_rect.right_mm > physical_page.width_mm or paint_rect.bottom_mm > physical_page.height_mm:
        raise ValueError("Der bedruckbare Bereich liegt außerhalb des Papierformats.")
    rows, columns = (settings.custom_rows, settings.custom_columns) if settings.is_custom else grid_for(settings.effective_images_per_page, orientation == "landscape")
    return MultiImagePrintDocument(
        sources=ordered_sources, source_kind=source_kind or settings.source, page_size=physical_page,
        printable_rect=paint_rect, rows=rows, columns=columns, page_margin_mm=settings.page_margin_mm,
        cell_spacing_mm=settings.cell_spacing_mm, orientation=orientation, contact_sheet=settings.contact_sheet,
        show_filename=settings.show_filename, show_capture_date=settings.show_capture_date,
        show_page_number=settings.show_page_number, show_header=settings.show_header,
        header_text=effective_header_text(settings), use_folder_name_as_title=settings.use_folder_name_as_title,
        folder_name=folder_name or effective_footer_folder_name(settings), show_folder_in_footer=settings.show_folder_in_footer,
        show_print_date=settings.show_print_date, print_date_text=print_date_text,
    )


def grid_for(images_per_page: int, landscape: bool) -> tuple[int, int]:
    grids = {1: (1, 1), 4: (2, 2), 9: (3, 3), 16: (4, 4), 32: (8, 4)}
    if images_per_page == 2:
        return (1, 2) if landscape else (2, 1)
    if images_per_page == 6:
        return (2, 3) if landscape else (3, 2)
    if images_per_page == 32 and landscape:
        return 4, 8
    return grids[images_per_page]


def effective_header_text(settings: MultiImagePrintSettings) -> str:
    return settings.header_text.strip() if settings.show_header and isinstance(settings.header_text, str) else ""


def folder_title_from_path(directory: Path | None) -> str:
    return directory.name if isinstance(directory, Path) and directory.parent != directory else ""


def current_print_date_text() -> str:
    return datetime.now().strftime("%d.%m.%Y")


def effective_footer_folder_name(settings: MultiImagePrintSettings) -> str:
    return settings.footer_folder_name.strip() if settings.show_folder_in_footer and isinstance(settings.footer_folder_name, str) else ""
