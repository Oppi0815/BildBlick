from dataclasses import dataclass, replace
from uuid import uuid4

from PySide6.QtCore import QSettings

from printing.multi_image_print import MultiImagePrintSettings


PROFILE_ROOT = "printing/profiles/user"
ORDER_KEY = "printing/profiles/userOrder"
VALID_COUNTS = {0, 1, 2, 4, 6, 9, 16, 32}
MAX_PROFILE_NAME_LENGTH = 60
RESERVED_PROFILE_NAMES = {
    "Standard",
    "4 Bilder",
    "9 Bilder",
    "16 Bilder",
    "32 Bilder",
    "Kontaktabzug 9",
    "Kontaktabzug 16",
    "Kontaktabzug 32",
    "Benutzerdefiniert",
}


@dataclass(frozen=True)
class MultiImagePrintProfile:
    profile_id: str
    display_name: str
    settings: MultiImagePrintSettings
    built_in: bool = False


def profile_settings_key(settings: MultiImagePrintSettings) -> tuple:
    return (
        settings.orientation,
        settings.images_per_page,
        settings.custom_rows,
        settings.custom_columns,
        round(settings.page_margin_mm, 1),
        round(settings.cell_spacing_mm, 1),
        settings.contact_sheet,
        settings.show_filename,
        settings.show_capture_date,
        settings.show_page_number,
        settings.show_header,
        settings.header_text.strip()
        if isinstance(settings.header_text, str) else "",
        settings.use_folder_name_as_title,
        settings.show_print_date,
        settings.show_folder_in_footer,
    )


def profile_settings_equal(
    left: MultiImagePrintSettings,
    right: MultiImagePrintSettings,
) -> bool:
    return profile_settings_key(left) == profile_settings_key(right)


def find_matching_profile(
    print_settings: MultiImagePrintSettings,
    built_in_profiles: list[MultiImagePrintProfile],
    user_profiles: list[MultiImagePrintProfile],
    current_profile_id: str | None = None,
) -> MultiImagePrintProfile | None:
    candidates = [*user_profiles, *built_in_profiles]
    if current_profile_id is not None:
        current_profile = next(
            (
                profile for profile in candidates
                if profile.profile_id == current_profile_id
            ),
            None,
        )
        if current_profile is not None and profile_settings_equal(
            print_settings, current_profile.settings
        ):
            return current_profile
    for profile in user_profiles:
        if profile_settings_equal(print_settings, profile.settings):
            return profile
    for profile in built_in_profiles:
        if (
            profile.profile_id != "standard"
            and profile_settings_equal(print_settings, profile.settings)
        ):
            return profile
    return next(
        (
            profile for profile in built_in_profiles
            if profile.profile_id == "standard"
            and profile_settings_equal(print_settings, profile.settings)
        ),
        None,
    )


def normalize_profile_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    return name.strip()[:MAX_PROFILE_NAME_LENGTH]


def is_reserved_profile_name(name: str) -> bool:
    normalized_name = normalize_profile_name(name).casefold()
    return normalized_name in {
        reserved_name.casefold() for reserved_name in RESERVED_PROFILE_NAMES
    }


def user_profile_name_exists(
    profiles: list[MultiImagePrintProfile], name: str
) -> bool:
    normalized_name = normalize_profile_name(name).casefold()
    return any(
        normalize_profile_name(profile.display_name).casefold()
        == normalized_name
        for profile in profiles
    )


def _bounded(value, low, high, default):
    try:
        return min(high, max(low, type(default)(value)))
    except (TypeError, ValueError):
        return default


def _profile_settings(settings: QSettings, prefix: str) -> MultiImagePrintSettings:
    count = settings.value(f"{prefix}/imagesPerPage", 4, type=int)
    return MultiImagePrintSettings(
        orientation=settings.value(f"{prefix}/orientation", "automatic", type=str)
        if settings.value(f"{prefix}/orientation", "automatic", type=str) in {"automatic", "portrait", "landscape"} else "automatic",
        images_per_page=count if count in VALID_COUNTS else 4,
        custom_rows=_bounded(settings.value(f"{prefix}/customRows", 4), 1, 12, 4),
        custom_columns=_bounded(settings.value(f"{prefix}/customColumns", 3), 1, 12, 3),
        page_margin_mm=_bounded(settings.value(f"{prefix}/pageMarginMm", 5.0), 0.0, 30.0, 5.0),
        cell_spacing_mm=_bounded(settings.value(f"{prefix}/cellSpacingMm", 4.0), 0.0, 20.0, 4.0),
        contact_sheet=settings.value(f"{prefix}/contactSheet", False, type=bool),
        show_filename=settings.value(f"{prefix}/showFilename", True, type=bool),
        show_capture_date=settings.value(f"{prefix}/showCaptureDate", False, type=bool),
        show_page_number=settings.value(f"{prefix}/showPageNumber", True, type=bool),
        show_header=settings.value(f"{prefix}/showHeader", False, type=bool),
        header_text=settings.value(f"{prefix}/headerText", "", type=str),
        use_folder_name_as_title=settings.value(
            f"{prefix}/useFolderNameAsTitle", False, type=bool
        ),
        show_print_date=settings.value(f"{prefix}/showPrintDate", False, type=bool),
        show_folder_in_footer=settings.value(
            f"{prefix}/showFolderInFooter", False, type=bool
        ),
    )


def create_user_profile(display_name: str, print_settings: MultiImagePrintSettings) -> MultiImagePrintProfile:
    return MultiImagePrintProfile(str(uuid4()), display_name.strip()[:60], replace(print_settings))


def overwrite_user_profile(
    profile: MultiImagePrintProfile,
    display_name: str,
    print_settings: MultiImagePrintSettings,
) -> MultiImagePrintProfile:
    return MultiImagePrintProfile(
        profile.profile_id,
        normalize_profile_name(display_name),
        replace(print_settings),
    )


def save_user_profile(settings: QSettings, profile: MultiImagePrintProfile) -> None:
    prefix = f"{PROFILE_ROOT}/{profile.profile_id}"
    values = profile.settings
    settings.setValue(f"{prefix}/displayName", profile.display_name)
    for key, value in (("orientation", values.orientation), ("imagesPerPage", values.images_per_page), ("customRows", values.custom_rows), ("customColumns", values.custom_columns), ("pageMarginMm", values.page_margin_mm), ("cellSpacingMm", values.cell_spacing_mm), ("contactSheet", values.contact_sheet), ("showFilename", values.show_filename), ("showCaptureDate", values.show_capture_date), ("showPageNumber", values.show_page_number), ("showHeader", values.show_header), ("headerText", values.header_text), ("useFolderNameAsTitle", values.use_folder_name_as_title), ("showPrintDate", values.show_print_date), ("showFolderInFooter", values.show_folder_in_footer)):
        settings.setValue(f"{prefix}/{key}", value)
    order = settings.value(ORDER_KEY, [], type=list)
    if profile.profile_id not in order:
        settings.setValue(ORDER_KEY, [*order, profile.profile_id])


def load_user_profiles(settings: QSettings) -> list[MultiImagePrintProfile]:
    profiles = []
    for profile_id in settings.value(ORDER_KEY, [], type=list):
        prefix = f"{PROFILE_ROOT}/{profile_id}"
        name = settings.value(f"{prefix}/displayName", "", type=str).strip()
        if name:
            profiles.append(MultiImagePrintProfile(profile_id, name, _profile_settings(settings, prefix)))
    return profiles


def delete_user_profile(settings: QSettings, profile_id: str) -> bool:
    order = settings.value(ORDER_KEY, [], type=list)
    if profile_id not in order:
        return False
    settings.remove(f"{PROFILE_ROOT}/{profile_id}")
    settings.setValue(ORDER_KEY, [item for item in order if item != profile_id])
    settings.sync()
    return settings.status() == QSettings.Status.NoError
