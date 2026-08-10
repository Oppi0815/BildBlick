"""Adapters from BildBlick's current single-image UI to the new page model."""

from __future__ import annotations

from dataclasses import replace

from printing.layout import (
    ImageSourceInfo,
    PagePlan,
    PageSizeMm,
    RectMm,
    SingleImageLayout,
    SizeMm,
)
from printing.planner import plan_single_image
from printing.printer_geometry import PrinterGeometryMm


def single_image_layout_from_legacy_settings(
    page_size: PageSizeMm,
    paint_rect: RectMm,
    size_mode: str,
    centered: bool,
) -> SingleImageLayout:
    """Translate the unchanged Phase-2 UI settings to ``SingleImageLayout``.

    ``paint_rect`` is the QPrinter-reported hardware-printable area, already
    expressed in coordinates of the physical page. The current UI has no
    user-configurable margins, so it becomes the complete available area.
    """

    orientation = "landscape" if page_size.width_mm > page_size.height_mm else "portrait"
    position = "center" if centered else "top_left"
    requested_size = None
    if size_mode in {"10x15", "13x18"}:
        short_side, long_side = (100.0, 150.0) if size_mode == "10x15" else (130.0, 180.0)
        requested_size = SizeMm(
            long_side if paint_rect.width_mm > paint_rect.height_mm else short_side,
            short_side if paint_rect.width_mm > paint_rect.height_mm else long_side,
        )
        scale_mode = "fixed_size"
    elif size_mode in {"fit", "fill", "original", "a4"}:
        # The old A4 mode sets the initial printer paper to A4, then fits.
        scale_mode = "fit" if size_mode == "a4" else size_mode
    else:
        raise ValueError(f"Unbekannter bisheriger Bildgrößenmodus: {size_mode!r}")
    return SingleImageLayout(
        page_size=page_size,
        orientation=orientation,
        scale_mode=scale_mode,
        requested_size=requested_size,
        position=position,
        available_rect=paint_rect,
    )


def plan_single_image_from_legacy_settings(
    source: ImageSourceInfo,
    geometry: PrinterGeometryMm,
    size_mode: str,
    centered: bool,
    rotation_degrees: int = 0,
) -> PagePlan:
    """Use one UI adapter for both preview and physical single-image output.

    The caller supplies only the geometry: the preview uses its documented
    default geometry while printing uses the final QPrinter geometry.
    """

    layout = single_image_layout_from_legacy_settings(
        geometry.page_size, geometry.paint_rect, size_mode, centered,
    )
    return plan_single_image(
        rotated_source_info(source, rotation_degrees),
        layout,
        rotation_degrees=rotation_degrees,
    )


def rotated_source_info(source: ImageSourceInfo, rotation_degrees: int) -> ImageSourceInfo:
    """Describe the final dimensions after a renderer-applied right-angle rotation."""

    normalized = rotation_degrees % 360
    if normalized in {90, 270}:
        return replace(
            source,
            pixel_width=source.pixel_height,
            pixel_height=source.pixel_width,
            dpi_x=source.dpi_y,
            dpi_y=source.dpi_x,
        )
    return source


def image_exceeds_printable_area(target_rect: RectMm, printable_rect: RectMm) -> bool:
    """Return whether an intentionally un-clipped image extends past printable area."""

    epsilon = 1e-9
    return (
        target_rect.x_mm < printable_rect.x_mm - epsilon
        or target_rect.y_mm < printable_rect.y_mm - epsilon
        or target_rect.right_mm > printable_rect.right_mm + epsilon
        or target_rect.bottom_mm > printable_rect.bottom_mm + epsilon
    )
