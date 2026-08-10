"""UI- and device-independent page planning in millimetres."""

from __future__ import annotations

from math import ceil
from typing import Sequence

from printing.layout import (
    CaptionOptions,
    ImageElementPlan,
    ImageSourceInfo,
    MarginsMm,
    MultiImagePrintDocument,
    PagePlan,
    PageSizeMm,
    Position,
    RectMm,
    SingleImageLayout,
    SizeMm,
    TextElementPlan,
    printable_rect_mm,
)


DEFAULT_IMAGE_DPI = 300.0
MIN_VALID_DPI = 30.0
MAX_VALID_DPI = 1200.0


def effective_dpi(value: float | None) -> float:
    """Normalize absent or implausible metadata to BildBlick's 300 DPI default."""

    if value is None:
        return DEFAULT_IMAGE_DPI
    try:
        valid = MIN_VALID_DPI <= float(value) <= MAX_VALID_DPI
    except (TypeError, ValueError):
        valid = False
    if not valid:
        return DEFAULT_IMAGE_DPI
    return float(value)


def original_size_mm(source: ImageSourceInfo) -> SizeMm:
    """Return the physical size encoded by image pixels and normalized DPI."""

    return SizeMm(
        source.pixel_width / effective_dpi(source.dpi_x) * 25.4,
        source.pixel_height / effective_dpi(source.dpi_y) * 25.4,
    )


def _fitted_size(source: ImageSourceInfo, bounds: RectMm, fill: bool) -> SizeMm:
    if bounds.width_mm <= 0 or bounds.height_mm <= 0:
        raise ValueError("Die verfügbare Bildfläche muss größer als 0 mm sein.")
    scale = (
        max(bounds.width_mm / source.pixel_width, bounds.height_mm / source.pixel_height)
        if fill else min(bounds.width_mm / source.pixel_width, bounds.height_mm / source.pixel_height)
    )
    return SizeMm(source.pixel_width * scale, source.pixel_height * scale)


def _fixed_size(source: ImageSourceInfo, requested: SizeMm, lock_aspect_ratio: bool) -> SizeMm:
    width, height = requested.width_mm, requested.height_mm
    aspect = source.pixel_width / source.pixel_height
    if width is None:
        return SizeMm(height * aspect, height)
    if height is None:
        return SizeMm(width, width / aspect)
    if not lock_aspect_ratio:
        return SizeMm(width, height)
    scale = min(width / source.pixel_width, height / source.pixel_height)
    return SizeMm(source.pixel_width * scale, source.pixel_height * scale)


def positioned_rect(size: SizeMm, container: RectMm, position: Position) -> RectMm:
    """Place a size within a rectangle without modifying either size."""

    assert size.width_mm is not None and size.height_mm is not None
    horizontal = position in {"center", "top", "bottom"}
    vertical = position in {"center", "left", "right"}
    x = (
        container.x_mm + (container.width_mm - size.width_mm) / 2
        if horizontal else container.x_mm
        if position in {"left", "top_left", "bottom_left"}
        else container.right_mm - size.width_mm
    )
    y = (
        container.y_mm + (container.height_mm - size.height_mm) / 2
        if vertical else container.y_mm
        if position in {"top", "top_left", "top_right"}
        else container.bottom_mm - size.height_mm
    )
    return RectMm(x, y, size.width_mm, size.height_mm)


def plan_single_image(
    source: ImageSourceInfo,
    layout: SingleImageLayout,
    page_number: int = 1,
    rotation_degrees: float = 0.0,
) -> PagePlan:
    """Create one finished single-image plan from physical layout decisions."""

    page_size = layout.oriented_page_size
    if layout.available_rect is None:
        printable = printable_rect_mm(page_size, layout.margins)
    else:
        # Hardware paint areas can start inside the physical page. Future
        # user margins are inset from that area, never applied a second time
        # by the renderer.
        hardware_rect = layout.available_rect
        inset = printable_rect_mm(
            PageSizeMm(hardware_rect.width_mm, hardware_rect.height_mm),
            layout.margins,
        )
        printable = RectMm(
            hardware_rect.x_mm + inset.x_mm,
            hardware_rect.y_mm + inset.y_mm,
            inset.width_mm,
            inset.height_mm,
        )
    if printable.width_mm == 0 or printable.height_mm == 0:
        raise ValueError("Die Druckränder lassen keine bedruckbare Fläche übrig.")
    caption_lines = []
    if layout.captions.show_filename and source.filename:
        caption_lines.append(source.filename)
    if layout.captions.show_capture_date and source.capture_date:
        caption_lines.append(source.capture_date)
    caption_height = max(4.0, layout.captions.font_size_pt * 0.5 + 2.0) if caption_lines else 0.0
    caption_gap = 1.0 if caption_lines else 0.0
    # Reserve a strip first, so "fit" captions are reliably below rather
    # than disappearing because the image consumed the full printable area.
    content = RectMm(
        printable.x_mm, printable.y_mm, printable.width_mm,
        printable.height_mm - caption_height - caption_gap,
    ) if caption_lines and printable.height_mm > caption_height + caption_gap else printable
    if layout.custom_rect is not None:
        target = layout.custom_rect
        size = None
    elif layout.scale_mode == "fit":
        size = _fitted_size(source, content, fill=False)
    elif layout.scale_mode == "fill":
        size = _fitted_size(source, content, fill=True)
    elif layout.scale_mode == "original":
        size = original_size_mm(source)
    else:
        assert layout.requested_size is not None
        size = _fixed_size(source, layout.requested_size, layout.lock_aspect_ratio)
    if size is not None:
        target = positioned_rect(size, content, layout.position)
    image = ImageElementPlan(
        source=source,
        target_rect=target,
        rotation_degrees=rotation_degrees,
        clip_rect=content if layout.scale_mode == "fill" else None,
    )
    texts: tuple[TextElementPlan, ...] = ()
    # Captions are deliberately optional: when an intentionally oversized
    # image leaves no space below it, retain the image plan and omit the label.
    if caption_lines:
        caption_y = content.bottom_mm + caption_gap
        if caption_y + caption_height <= printable.bottom_mm + 1e-9:
            texts = (TextElementPlan(
                "\n".join(caption_lines),
                RectMm(printable.x_mm, caption_y, printable.width_mm, caption_height),
                layout.captions.alignment,
                layout.captions.font_size_pt,
            ),)
    return PagePlan(page_size, printable, (image,), texts, page_number=page_number)


def _fit_in_rect(source: ImageSourceInfo, rect: RectMm) -> RectMm:
    return positioned_rect(_fitted_size(source, rect, False), rect, "center")


def _plan_multi_image_document(document: MultiImagePrintDocument) -> list[PagePlan]:
    """Turn an ordered multi-image document into output-ready PagePlans."""

    if not document.sources:
        return []
    paint = document.printable_rect
    margin = document.page_margin_mm
    footer_needed = (
        document.show_page_number
        or document.show_print_date
        or (document.show_folder_in_footer and bool(document.folder_name.strip()))
    )
    footer_height = 6.0 if footer_needed else 0.0
    content = RectMm(
        paint.x_mm + margin,
        paint.y_mm + margin,
        paint.width_mm - 2 * margin,
        paint.height_mm - 2 * margin - footer_height,
    )
    if content.width_mm <= 0 or content.height_mm <= 0:
        raise ValueError("Die Seitenränder lassen keinen bedruckbaren Bereich übrig.")
    header_text = document.header_text.strip() if document.show_header else ""
    header_height = max(7.0, 14.0 / 72.0 * 25.4 * 1.45) if header_text else 0.0
    header_gap = 2.0 if header_text else 0.0
    grid = RectMm(
        content.x_mm, content.y_mm + header_height + header_gap,
        content.width_mm, content.height_mm - header_height - header_gap,
    )
    if grid.width_mm <= 0 or grid.height_mm <= 0:
        raise ValueError("Kopfzeile und Ränder lassen keinen Bildbereich übrig.")
    cell_width = (grid.width_mm - document.cell_spacing_mm * (document.columns - 1)) / document.columns
    cell_height = (grid.height_mm - document.cell_spacing_mm * (document.rows - 1)) / document.rows
    if cell_width <= 0 or cell_height <= 0:
        raise ValueError("Raster und Bildabstände lassen keine Bildzellen übrig.")
    per_page = document.rows * document.columns
    page_count = ceil(len(document.sources) / per_page)
    footer = RectMm(content.x_mm, content.bottom_mm + margin, content.width_mm, footer_height) if footer_needed else None
    pages: list[PagePlan] = []
    for page_index in range(page_count):
        images: list[ImageElementPlan] = []
        texts: list[TextElementPlan] = []
        if header_text:
            texts.append(TextElementPlan(
                header_text, RectMm(content.x_mm, content.y_mm, content.width_mm, header_height),
                font_size_pt=14.0, bold=True, alignment="center", elide_policy="right", semantic_role="header",
            ))
        page_sources = document.sources[page_index * per_page:(page_index + 1) * per_page]
        for offset, source in enumerate(page_sources):
            row, column = divmod(offset, document.columns)
            cell = RectMm(
                grid.x_mm + column * (cell_width + document.cell_spacing_mm),
                grid.y_mm + row * (cell_height + document.cell_spacing_mm), cell_width, cell_height,
            )
            filename = document.contact_sheet and document.show_filename and bool(source.filename or source.path.name)
            capture_date = document.contact_sheet and document.show_capture_date and bool(source.capture_date)
            line_height = 4.2
            if filename and capture_date and cell.height_mm < line_height * 4 + 1.2:
                capture_date = False
            line_count = int(filename) + int(capture_date)
            caption_height = min(cell.height_mm, line_count * line_height + (1.2 if line_count else 0.0))
            image_area = RectMm(cell.x_mm, cell.y_mm, cell.width_mm, cell.height_mm - caption_height)
            images.append(ImageElementPlan(source, _fit_in_rect(source, image_area)))
            if filename:
                filename_rect = RectMm(cell.x_mm, cell.bottom_mm - caption_height, cell.width_mm, caption_height / line_count)
                texts.append(TextElementPlan(source.filename or source.path.name, filename_rect, font_size_pt=8.0, alignment="center", elide_policy="middle", semantic_role="filename"))
            if capture_date:
                date_y = cell.bottom_mm - caption_height + (caption_height / line_count if filename else 0.0)
                texts.append(TextElementPlan(source.capture_date or "", RectMm(cell.x_mm, date_y, cell.width_mm, caption_height / line_count), font_size_pt=8.0, alignment="center", elide_policy="right", semantic_role="capture_date"))
        if footer is not None:
            # The central page number receives a guaranteed, independently
            # planned strip so folder/date text can never displace it.
            center_width = min(footer.width_mm, max(footer.width_mm / 3, 42.0 if document.show_page_number else 0.0))
            center_x = footer.x_mm + (footer.width_mm - center_width) / 2
            if document.show_folder_in_footer and document.folder_name.strip():
                texts.append(TextElementPlan(document.folder_name.strip(), RectMm(footer.x_mm, footer.y_mm, max(0.0, center_x - footer.x_mm), footer.height_mm), alignment="left", font_size_pt=9.0, elide_policy="right", semantic_role="folder"))
            if document.show_page_number:
                texts.append(TextElementPlan(f"Seite {page_index + 1} von {page_count}", RectMm(center_x, footer.y_mm, center_width, footer.height_mm), font_size_pt=9.0, alignment="center", elide_policy="right", semantic_role="page_number"))
            if document.show_print_date and document.print_date_text:
                texts.append(TextElementPlan(document.print_date_text, RectMm(center_x + center_width, footer.y_mm, max(0.0, footer.right_mm - (center_x + center_width)), footer.height_mm), alignment="right", font_size_pt=9.0, elide_policy="right", semantic_role="print_date"))
        pages.append(PagePlan(document.page_size, paint, tuple(images), tuple(texts), page_index + 1))
    return pages


def plan_multi_image_pages(
    sources: Sequence[ImageSourceInfo] | MultiImagePrintDocument,
    page_size: PageSizeMm | None = None,
    margins: MarginsMm | None = None,
    rows: int | None = None,
    columns: int | None = None,
    spacing_mm: float = 0.0,
) -> list[PagePlan]:
    """Prepare output-ready, pure-mm contact-sheet PagePlans."""

    if isinstance(sources, MultiImagePrintDocument):
        return _plan_multi_image_document(sources)
    if not sources:
        return []
    if page_size is None or margins is None or rows is None or columns is None:
        raise ValueError("Seitenformat, Ränder und Raster müssen angegeben werden.")
    if rows <= 0 or columns <= 0:
        raise ValueError("Rasterzeilen und -spalten müssen größer als 0 sein.")
    if spacing_mm < 0:
        raise ValueError("Der Bildabstand darf nicht negativ sein.")
    printable = printable_rect_mm(page_size, margins)
    return _plan_multi_image_document(MultiImagePrintDocument(
        tuple(sources), "all", page_size, printable, rows, columns,
        0.0, spacing_mm, show_page_number=False,
    ))
