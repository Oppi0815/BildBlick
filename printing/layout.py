"""Millimetergenaue, UI-unabhängige Drucklayoutdaten.

Diese Datentypen enthalten absichtlich keine Bildschirm- oder Drucker-Pixel.
Sie sind die gemeinsame fachliche Grundlage für spätere Vorschau-, Druck- und
PDF-Ausgaben.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


Orientation = Literal["portrait", "landscape"]
ScaleMode = Literal["fit", "fill", "original", "fixed_size"]
Position = Literal[
    "center", "left", "right", "top", "bottom", "top_left", "top_right",
    "bottom_left", "bottom_right", "custom",
]


@dataclass(frozen=True)
class PageSizeMm:
    """Physical paper size in millimetres."""

    width_mm: float
    height_mm: float

    def __post_init__(self) -> None:
        if self.width_mm <= 0 or self.height_mm <= 0:
            raise ValueError("Papierbreite und Papierhöhe müssen größer als 0 mm sein.")

    def for_orientation(self, orientation: Orientation) -> "PageSizeMm":
        if orientation not in ("portrait", "landscape"):
            raise ValueError(f"Unbekannte Papierausrichtung: {orientation!r}")
        short_side, long_side = sorted((self.width_mm, self.height_mm))
        return PageSizeMm(
            short_side if orientation == "portrait" else long_side,
            long_side if orientation == "portrait" else short_side,
        )

    @classmethod
    def a4(cls, orientation: Orientation = "portrait") -> "PageSizeMm":
        return cls(210.0, 297.0).for_orientation(orientation)

    @classmethod
    def photo_10x15(cls, orientation: Orientation = "portrait") -> "PageSizeMm":
        return cls(100.0, 150.0).for_orientation(orientation)

    @classmethod
    def photo_13x18(cls, orientation: Orientation = "portrait") -> "PageSizeMm":
        return cls(130.0, 180.0).for_orientation(orientation)


@dataclass(frozen=True)
class MarginsMm:
    """User-defined margins measured from the edge of the paper."""

    left_mm: float = 0.0
    top_mm: float = 0.0
    right_mm: float = 0.0
    bottom_mm: float = 0.0

    def __post_init__(self) -> None:
        if min(self.left_mm, self.top_mm, self.right_mm, self.bottom_mm) < 0:
            raise ValueError("Druckränder dürfen nicht negativ sein.")


@dataclass(frozen=True)
class RectMm:
    """A rectangle in physical page coordinates (millimetres)."""

    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float

    def __post_init__(self) -> None:
        if self.width_mm < 0 or self.height_mm < 0:
            raise ValueError("Rechteckbreite und -höhe dürfen nicht negativ sein.")

    @property
    def right_mm(self) -> float:
        return self.x_mm + self.width_mm

    @property
    def bottom_mm(self) -> float:
        return self.y_mm + self.height_mm


@dataclass(frozen=True)
class SourceCropRect:
    """Normalized source-image crop (0..1), independent of image pixels."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Der Bildausschnitt muss eine positive Größe haben.")
        if self.x < 0 or self.y < 0 or self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("Der Bildausschnitt muss innerhalb des Quellbilds liegen.")


@dataclass(frozen=True)
class SizeMm:
    """A requested physical size. Either dimension may be omitted."""

    width_mm: float | None = None
    height_mm: float | None = None

    def __post_init__(self) -> None:
        if self.width_mm is None and self.height_mm is None:
            raise ValueError("Für eine feste Bildgröße muss mindestens eine Seite gesetzt sein.")
        for value in (self.width_mm, self.height_mm):
            if value is not None and value <= 0:
                raise ValueError("Feste Bildgrößen müssen größer als 0 mm sein.")


@dataclass(frozen=True)
class ImageSourceInfo:
    """Already inspected image metadata supplied to a planner.

    Invalid DPI values are deliberately retained here. ``planner.effective_dpi``
    normalizes them centrally without making the model depend on EXIF readers.
    """

    path: Path
    pixel_width: int
    pixel_height: int
    dpi_x: float | None = None
    dpi_y: float | None = None
    filename: str | None = None
    capture_date: str | None = None

    def __post_init__(self) -> None:
        if self.pixel_width <= 0 or self.pixel_height <= 0:
            raise ValueError("Die Bildpixelmaße müssen größer als 0 sein.")
        object.__setattr__(self, "path", Path(self.path))


@dataclass(frozen=True)
class CaptionOptions:
    """Optional labels that later renderers may attach to a single image."""

    show_filename: bool = False
    show_capture_date: bool = False
    font_size_pt: float = 10.0
    alignment: str = "center"


@dataclass(frozen=True)
class SingleImageLayout:
    """All layout decisions for one image, expressed in physical units."""

    page_size: PageSizeMm
    orientation: Orientation = "portrait"
    margins: MarginsMm = field(default_factory=MarginsMm)
    scale_mode: ScaleMode = "fit"
    requested_size: SizeMm | None = None
    position: Position = "center"
    lock_aspect_ratio: bool = True
    captions: CaptionOptions = field(default_factory=CaptionOptions)
    available_rect: RectMm | None = None
    custom_rect: RectMm | None = None

    def __post_init__(self) -> None:
        if self.orientation not in ("portrait", "landscape"):
            raise ValueError(f"Unbekannte Papierausrichtung: {self.orientation!r}")
        if self.scale_mode not in ("fit", "fill", "original", "fixed_size"):
            raise ValueError(f"Unbekannter Skalierungsmodus: {self.scale_mode!r}")
        if self.position not in {
            "center", "left", "right", "top", "bottom", "top_left",
            "top_right", "bottom_left", "bottom_right", "custom",
        }:
            raise ValueError(f"Unbekannte Bildposition: {self.position!r}")
        if self.scale_mode == "fixed_size" and self.requested_size is None:
            raise ValueError("fixed_size benötigt eine gewünschte Bildgröße.")
        if self.position == "custom" and self.custom_rect is None:
            raise ValueError("custom benötigt eine benutzerdefinierte Bildgeometrie.")

    @property
    def oriented_page_size(self) -> PageSizeMm:
        return self.page_size.for_orientation(self.orientation)


@dataclass(frozen=True)
class ImageElementPlan:
    """A fully positioned image; its target geometry is always in mm."""

    source: ImageSourceInfo
    target_rect: RectMm
    source_crop_rect: SourceCropRect | None = None
    rotation_degrees: float = 0.0
    clip_rect: RectMm | None = None


@dataclass(frozen=True)
class TextElementPlan:
    """A fully positioned text label; font size is in typographic points."""

    text: str
    rect: RectMm
    alignment: str = "center"
    font_size_pt: float = 10.0
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.font_size_pt <= 0:
            raise ValueError("Die Schriftgröße muss größer als 0 Punkt sein.")


@dataclass(frozen=True)
class PagePlan:
    """Output-ready page plan with no dependency on a UI or output device."""

    page_size: PageSizeMm
    printable_rect: RectMm
    image_elements: tuple[ImageElementPlan, ...] = ()
    text_elements: tuple[TextElementPlan, ...] = ()
    page_number: int = 1

    def __post_init__(self) -> None:
        if self.page_number < 1:
            raise ValueError("Die Seitennummer muss mindestens 1 sein.")
        object.__setattr__(self, "image_elements", tuple(self.image_elements))
        object.__setattr__(self, "text_elements", tuple(self.text_elements))


def printable_rect_mm(page_size: PageSizeMm, margins: MarginsMm) -> RectMm:
    """Return the user-printable rectangle or reject margins larger than paper."""

    width = page_size.width_mm - margins.left_mm - margins.right_mm
    height = page_size.height_mm - margins.top_mm - margins.bottom_mm
    if width < 0 or height < 0:
        raise ValueError("Die Druckränder sind größer als das Papierformat.")
    return RectMm(margins.left_mm, margins.top_mm, width, height)
