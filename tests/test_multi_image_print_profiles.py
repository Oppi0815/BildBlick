from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from PySide6.QtCore import QSettings

from printing.multi_image_print import MultiImagePrintSettings, folder_title_from_path
from printing.print_profiles import (
    MultiImagePrintProfile,
    create_user_profile,
    delete_user_profile,
    find_matching_profile,
    is_reserved_profile_name,
    load_user_profiles,
    normalize_profile_name,
    overwrite_user_profile,
    profile_settings_equal,
    save_user_profile,
    user_profile_name_exists,
)


def test_normalize_profile_name() -> None:
    assert normalize_profile_name("Familie") == "Familie"
    assert normalize_profile_name("  Familie 4×3  ") == "Familie 4×3"
    assert normalize_profile_name("") == ""
    assert normalize_profile_name("   ") == ""
    assert normalize_profile_name("x" * 60) == "x" * 60
    assert normalize_profile_name("x" * 70) == "x" * 60
    assert normalize_profile_name("Urlaub & Familie × 3") == "Urlaub & Familie × 3"
    assert normalize_profile_name("Ärger mit Öl") == "Ärger mit Öl"
    assert normalize_profile_name(None) == ""


def test_reserved_profile_names() -> None:
    assert is_reserved_profile_name("Standard")
    assert is_reserved_profile_name(" standard ")
    assert is_reserved_profile_name("STANDARD")
    assert is_reserved_profile_name("Benutzerdefiniert")
    assert not is_reserved_profile_name("Familie")


def test_user_profile_name_exists() -> None:
    profiles = [
        MultiImagePrintProfile(
            "profile-id",
            "Familie 4×3",
            MultiImagePrintSettings(),
        )
    ]
    assert user_profile_name_exists(profiles, "Familie 4×3")
    assert user_profile_name_exists(profiles, "familie 4×3")
    assert user_profile_name_exists(profiles, " Familie 4×3 ")
    assert not user_profile_name_exists(profiles, "Urlaub")


def test_user_profile_round_trip_does_not_persist_source() -> None:
    source_settings = MultiImagePrintSettings(
        source="all",
        orientation="landscape",
        images_per_page=9,
        contact_sheet=True,
    )
    profile = create_user_profile("Familie 4×3", source_settings)
    assert str(UUID(profile.profile_id)) == profile.profile_id
    with TemporaryDirectory() as directory:
        settings = QSettings(
            str(Path(directory) / "profiles.ini"),
            QSettings.Format.IniFormat,
        )
        save_user_profile(settings, profile)
        settings.sync()
        loaded = load_user_profiles(settings)
    assert len(loaded) == 1
    assert loaded[0].display_name == "Familie 4×3"
    assert loaded[0].settings.orientation == "landscape"
    assert loaded[0].settings.images_per_page == 9
    assert loaded[0].settings.contact_sheet
    assert loaded[0].settings.source == "current"


def test_user_profile_order_and_uuid_lookup() -> None:
    with TemporaryDirectory() as directory:
        settings = QSettings(
            str(Path(directory) / "profiles.ini"),
            QSettings.Format.IniFormat,
        )
        first = create_user_profile("Familie 4×3", MultiImagePrintSettings())
        second = create_user_profile("Urlaub & Freunde", MultiImagePrintSettings())
        save_user_profile(settings, first)
        save_user_profile(settings, second)
        settings.sync()
        loaded = load_user_profiles(settings)
    assert [profile.profile_id for profile in loaded] == [
        first.profile_id,
        second.profile_id,
    ]
    selected = next(
        profile for profile in loaded if profile.profile_id == second.profile_id
    )
    assert selected.display_name == "Urlaub & Freunde"


def test_overwrite_keeps_uuid_and_delete_updates_order() -> None:
    with TemporaryDirectory() as directory:
        settings = QSettings(
            str(Path(directory) / "profiles.ini"),
            QSettings.Format.IniFormat,
        )
        first = create_user_profile("Familie", MultiImagePrintSettings())
        second = create_user_profile("Urlaub", MultiImagePrintSettings())
        save_user_profile(settings, first)
        save_user_profile(settings, second)
        updated = overwrite_user_profile(
            first,
            "FAMILIE",
            MultiImagePrintSettings(images_per_page=16),
        )
        save_user_profile(settings, updated)
        loaded = load_user_profiles(settings)
        assert loaded[0].profile_id == first.profile_id
        assert loaded[0].display_name == "FAMILIE"
        assert loaded[0].settings.images_per_page == 16
        assert settings.value("printing/profiles/userOrder", [], type=list) == [
            first.profile_id,
            second.profile_id,
        ]
        assert delete_user_profile(settings, first.profile_id)
        assert settings.value("printing/profiles/userOrder", [], type=list) == [
            second.profile_id
        ]
        assert not settings.contains(
            f"printing/profiles/user/{first.profile_id}/displayName"
        )
        assert not delete_user_profile(settings, "unknown-id")
        remaining = load_user_profiles(settings)
    assert [profile.profile_id for profile in remaining] == [second.profile_id]


def test_delete_handles_damaged_user_order() -> None:
    with TemporaryDirectory() as directory:
        settings = QSettings(
            str(Path(directory) / "profiles.ini"),
            QSettings.Format.IniFormat,
        )
        settings.setValue("printing/profiles/userOrder", "damaged-id")
        assert delete_user_profile(settings, "damaged-id")
        assert settings.value(
            "printing/profiles/userOrder", [], type=list
        ) == []


def test_profile_settings_comparison() -> None:
    original = MultiImagePrintSettings(source="current")
    assert profile_settings_equal(
        original,
        MultiImagePrintSettings(source="all"),
    )
    assert profile_settings_equal(
        original,
        MultiImagePrintSettings(page_margin_mm=5.04, cell_spacing_mm=4.04),
    )
    assert not profile_settings_equal(
        original,
        MultiImagePrintSettings(page_margin_mm=5.1),
    )
    assert not profile_settings_equal(
        original,
        MultiImagePrintSettings(cell_spacing_mm=4.1),
    )
    assert not profile_settings_equal(
        original,
        MultiImagePrintSettings(custom_rows=5),
    )


def test_profile_settings_comparison_includes_contact_sheet_options() -> None:
    original = MultiImagePrintSettings(contact_sheet=True)
    assert not profile_settings_equal(
        original,
        MultiImagePrintSettings(contact_sheet=False),
    )
    assert not profile_settings_equal(
        original,
        MultiImagePrintSettings(contact_sheet=True, show_filename=False),
    )
    assert not profile_settings_equal(
        original,
        MultiImagePrintSettings(contact_sheet=True, show_capture_date=True),
    )
    assert not profile_settings_equal(
        original,
        MultiImagePrintSettings(contact_sheet=True, show_page_number=False),
    )


def test_find_matching_fixed_and_user_profiles() -> None:
    standard = MultiImagePrintProfile(
        "standard",
        "Standard",
        MultiImagePrintSettings(images_per_page=9),
        built_in=True,
    )
    fixed = MultiImagePrintProfile(
        "fixed-9",
        "9 Bilder",
        MultiImagePrintSettings(images_per_page=9),
        built_in=True,
    )
    user = MultiImagePrintProfile(
        "user-9",
        "Familie",
        MultiImagePrintSettings(images_per_page=9),
    )
    current = MultiImagePrintSettings(images_per_page=9, source="all")
    assert find_matching_profile(
        current, [standard, fixed], []
    ).profile_id == "fixed-9"
    assert find_matching_profile(
        current, [standard, fixed], [], "standard"
    ).profile_id == "standard"
    assert find_matching_profile(current, [fixed], [user]).profile_id == "user-9"
    assert find_matching_profile(
        current, [fixed], [user], "fixed-9"
    ).profile_id == "fixed-9"
    assert find_matching_profile(
        MultiImagePrintSettings(images_per_page=16), [fixed], [user]
    ) is None


def test_matching_profile_is_found_again_after_restoring_values() -> None:
    first = MultiImagePrintProfile(
        "first-user",
        "Erstes Profil",
        MultiImagePrintSettings(images_per_page=4, page_margin_mm=8.0),
    )
    second = MultiImagePrintProfile(
        "second-user",
        "Zweites Profil",
        MultiImagePrintSettings(images_per_page=4, page_margin_mm=8.0),
    )
    changed = MultiImagePrintSettings(images_per_page=4, page_margin_mm=9.0)
    restored = MultiImagePrintSettings(images_per_page=4, page_margin_mm=8.0)
    assert find_matching_profile(changed, [], [first, second]) is None
    assert find_matching_profile(
        restored, [], [first, second]
    ).profile_id == first.profile_id
    assert find_matching_profile(
        restored, [], [first, second], second.profile_id
    ).profile_id == second.profile_id


def test_profile_header_values_are_persisted_and_overwritten() -> None:
    with TemporaryDirectory() as directory:
        settings = QSettings(
            str(Path(directory) / "profiles.ini"), QSettings.Format.IniFormat
        )
        profile = create_user_profile(
            "Familie",
            MultiImagePrintSettings(
                show_header=True, header_text="Ärger & Öl — Sommer"
            ),
        )
        save_user_profile(settings, profile)
        loaded = load_user_profiles(settings)[0]
        assert loaded.settings.show_header
        assert loaded.settings.header_text == "Ärger & Öl — Sommer"
        updated = overwrite_user_profile(
            loaded,
            "Familie",
            MultiImagePrintSettings(show_header=False, header_text="Neu"),
        )
        save_user_profile(settings, updated)
        loaded = load_user_profiles(settings)[0]
    assert not loaded.settings.show_header
    assert loaded.settings.header_text == "Neu"


def test_old_profile_uses_default_header_values() -> None:
    with TemporaryDirectory() as directory:
        settings = QSettings(
            str(Path(directory) / "profiles.ini"), QSettings.Format.IniFormat
        )
        profile_id = "legacy-profile"
        settings.setValue("printing/profiles/userOrder", [profile_id])
        settings.setValue(
            f"printing/profiles/user/{profile_id}/displayName", "Alt"
        )
        loaded = load_user_profiles(settings)[0]
    assert not loaded.settings.show_header
    assert loaded.settings.header_text == ""


def test_profile_comparison_includes_header_values() -> None:
    base = MultiImagePrintSettings(show_header=True, header_text="Familie")
    assert profile_settings_equal(
        base, MultiImagePrintSettings(show_header=True, header_text=" Familie ")
    )
    assert not profile_settings_equal(
        base, MultiImagePrintSettings(show_header=False, header_text="Familie")
    )
    assert not profile_settings_equal(
        base, MultiImagePrintSettings(show_header=True, header_text="Urlaub")
    )
    assert profile_settings_equal(
        base,
        MultiImagePrintSettings(
            source="all", show_header=True, header_text="Familie"
        ),
    )


def test_profile_folder_title_mode_is_persisted_and_compared() -> None:
    with TemporaryDirectory() as directory:
        settings = QSettings(
            str(Path(directory) / "profiles.ini"), QSettings.Format.IniFormat
        )
        profile = create_user_profile(
            "Automatisch",
            MultiImagePrintSettings(
                show_header=True,
                header_text="Urlaub Südafrika",
                use_folder_name_as_title=True,
            ),
        )
        save_user_profile(settings, profile)
        loaded = load_user_profiles(settings)[0]
    assert loaded.settings.use_folder_name_as_title
    assert not profile_settings_equal(
        loaded.settings,
        MultiImagePrintSettings(
            show_header=True, header_text="Urlaub Südafrika"
        ),
    )


def test_legacy_profile_and_folder_title_extraction() -> None:
    with TemporaryDirectory() as directory:
        settings = QSettings(
            str(Path(directory) / "profiles.ini"), QSettings.Format.IniFormat
        )
        profile_id = "legacy-folder-title"
        settings.setValue("printing/profiles/userOrder", [profile_id])
        settings.setValue(
            f"printing/profiles/user/{profile_id}/displayName", "Alt"
        )
        loaded = load_user_profiles(settings)[0]
    assert not loaded.settings.use_folder_name_as_title
    assert not loaded.settings.show_print_date
    assert not loaded.settings.show_folder_in_footer
    assert folder_title_from_path(Path("/home/horst/Bilder/Urlaub Südafrika")) == (
        "Urlaub Südafrika"
    )
    assert folder_title_from_path(Path("/")) == ""
    assert folder_title_from_path(None) == ""


def test_profile_footer_options_are_persisted_and_compared() -> None:
    with TemporaryDirectory() as directory:
        settings = QSettings(
            str(Path(directory) / "profiles.ini"), QSettings.Format.IniFormat
        )
        profile = create_user_profile(
            "Fußzeile",
            MultiImagePrintSettings(
                show_print_date=True,
                show_folder_in_footer=True,
                footer_folder_name="Urlaub Südafrika",
            ),
        )
        save_user_profile(settings, profile)
        loaded = load_user_profiles(settings)[0]
    assert loaded.settings.show_print_date
    assert loaded.settings.show_folder_in_footer
    assert loaded.settings.footer_folder_name == ""
    assert profile_settings_equal(
        loaded.settings,
        MultiImagePrintSettings(
            show_print_date=True,
            show_folder_in_footer=True,
            footer_folder_name="Ein anderer Ordner",
        ),
    )
    assert not profile_settings_equal(
        loaded.settings,
        MultiImagePrintSettings(show_folder_in_footer=True),
    )


def test_folder_name_changes_do_not_change_profile_match() -> None:
    profile = MultiImagePrintProfile(
        "footer-profile",
        "Fußzeile",
        MultiImagePrintSettings(show_folder_in_footer=True),
    )
    current = MultiImagePrintSettings(
        show_folder_in_footer=True,
        footer_folder_name="Urlaub Südafrika",
    )
    assert find_matching_profile(current, [], [profile]).profile_id == (
        profile.profile_id
    )
