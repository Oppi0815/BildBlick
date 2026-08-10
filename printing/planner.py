"""UI- and device-independent page planning in millimetres."""

from __future__ import annotations

from math import ceil
from typing import Sequence

from printing.layout import (
    CaptionOptions,
    ImageElementPlan,
    ImageSourceInfo,
    MarginsMm,
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


def plan_multi_image_pages(
    sources: Sequence[ImageSourceInfo],
    page_size: PageSizeMm,
    margins: MarginsMm,
    rows: int,
    columns: int,
    spacing_mm: float = 0.0,
) -> list[PagePlan]:
    """Prepare a pure-mm contact-sheet grid without changing the legacy path.

    This intentionally small adapter is a migration seam for
    ``calculate_multi_image_page``. Header/footer allocation and the existing
    dialog remain owned by the proven legacy implementation for this phase.
    """

    if not sources:
        return []
    if rows <= 0 or columns <= 0:
        raise ValueError("Rasterzeilen und -spalten müssen größer als 0 sein.")
    if spacing_mm < 0:
        raise ValueError("Der Bildabstand darf nicht negativ sein.")
    printable = printable_rect_mm(page_size, margins)
    cell_width = (printable.width_mm - spacing_mm * (columns - 1)) / columns
    cell_height = (printable.height_mm - spacing_mm * (rows - 1)) / rows
    if cell_width <= 0 or cell_height <= 0:
        raise ValueError("Raster und Bildabstände lassen keine Bildzellen übrig.")
    per_page = rows * columns
    page_count = ceil(len(sources) / per_page)
    pages: list[PagePlan] = []
    for page_index in range(page_count):
        images: list[ImageElementPlan] = []
        for offset, source in enumerate(sources[page_index * per_page:(page_index + 1) * per_page]):
            row, column = divmod(offset, columns)
            cell = RectMm(
                printable.x_mm + column * (cell_width + spacing_mm),
                printable.y_mm + row * (cell_height + spacing_mm),
                cell_width,
                cell_height,
            )
            images.append(ImageElementPlan(source, positioned_rect(_fitted_size(source, cell, False), cell, "center")))
        pages.append(PagePlan(page_size, printable, tuple(images), page_number=page_index + 1))
    return pages
