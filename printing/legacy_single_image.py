"""Compatibility helpers retained by the active single-image dialog."""

from __future__ import annotations

from printing.layout import ImageSourceInfo


def rotated_source_info(source: ImageSourceInfo, rotation_degrees: int) -> ImageSourceInfo:
    """Return source dimensions as seen after a right-angle rotation."""
    if rotation_degrees % 180:
        return ImageSourceInfo(
            source.path, source.pixel_height, source.pixel_width,
            source.dpi_x, source.dpi_y, source.filename, source.capture_date,
        )
    return source
