from bildbetrachter import (
    THUMBNAIL_DEFAULT,
    THUMBNAIL_MAXIMUM,
    THUMBNAIL_MINIMUM,
    THUMBNAIL_STEP,
    normalized_thumbnail_pixels,
    thumbnail_pixels_from_slider_value,
    thumbnail_size_slider_maximum,
    thumbnail_size_slider_value,
)


def test_thumbnail_size_defaults_to_the_existing_standard_value():
    assert normalized_thumbnail_pixels(THUMBNAIL_DEFAULT) == THUMBNAIL_DEFAULT


def test_thumbnail_size_is_bounded_to_minimum_and_maximum():
    assert normalized_thumbnail_pixels(-1) == THUMBNAIL_MINIMUM
    assert normalized_thumbnail_pixels(THUMBNAIL_MAXIMUM + THUMBNAIL_STEP) == THUMBNAIL_MAXIMUM


def test_thumbnail_size_rounds_to_the_nearest_slider_step():
    assert normalized_thumbnail_pixels(THUMBNAIL_MINIMUM + THUMBNAIL_STEP // 2) == THUMBNAIL_MINIMUM
    assert normalized_thumbnail_pixels(THUMBNAIL_MINIMUM + THUMBNAIL_STEP) == THUMBNAIL_MINIMUM + THUMBNAIL_STEP


def test_thumbnail_slider_conversion_is_clamped_and_round_trips():
    maximum = thumbnail_size_slider_maximum()

    assert thumbnail_pixels_from_slider_value(-1) == THUMBNAIL_MINIMUM
    assert thumbnail_pixels_from_slider_value(maximum + 1) == THUMBNAIL_MAXIMUM
    assert thumbnail_size_slider_value(THUMBNAIL_DEFAULT) == (
        THUMBNAIL_DEFAULT - THUMBNAIL_MINIMUM
    ) // THUMBNAIL_STEP
    assert thumbnail_pixels_from_slider_value(
        thumbnail_size_slider_value(THUMBNAIL_DEFAULT)
    ) == THUMBNAIL_DEFAULT
