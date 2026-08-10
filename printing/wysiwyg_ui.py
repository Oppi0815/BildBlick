"""Shared, palette-friendly widget setup for the WYSIWYG print dialogs."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QGuiApplication, QPalette
from PySide6.QtWidgets import QDialog, QFormLayout, QScrollArea, QWidget


SETTINGS_PANEL_WIDTH = 450
PREFERRED_DIALOG_SIZE = QSize(1400, 900)
MINIMUM_DIALOG_SIZE = QSize(900, 620)


def _screen_geometry(dialog: QDialog) -> QRect:
    parent = dialog.parentWidget()
    screen = parent.screen() if parent is not None else None
    screen = screen or QGuiApplication.primaryScreen()
    return screen.availableGeometry() if screen is not None else QRect(0, 0, 1400, 900)


def initial_wysiwyg_dialog_size(dialog: QDialog) -> tuple[QSize, QSize, QRect]:
    """Return a screen-bounded initial size and its practical minimum."""
    available = _screen_geometry(dialog)
    available_size = available.size()
    minimum = QSize(
        min(MINIMUM_DIALOG_SIZE.width(), available_size.width()),
        min(MINIMUM_DIALOG_SIZE.height(), available_size.height()),
    )
    preferred = QSize(
        min(PREFERRED_DIALOG_SIZE.width(), int(available_size.width() * 0.90)),
        min(PREFERRED_DIALOG_SIZE.height(), int(available_size.height() * 0.86)),
    )
    size = QSize(max(minimum.width(), preferred.width()), max(minimum.height(), preferred.height()))
    return size.boundedTo(available_size), minimum, available


def restore_wysiwyg_dialog_geometry(dialog: QDialog, settings, key: str) -> None:
    """Restore a usable size, never reviving an old tiny or off-screen dialog."""
    initial, minimum, available = initial_wysiwyg_dialog_size(dialog)
    saved = settings.value(key)
    saved_size = saved if isinstance(saved, QSize) else QSize()
    if saved_size.isValid():
        size = QSize(
            min(available.width(), max(minimum.width(), saved_size.width())),
            min(available.height(), max(minimum.height(), saved_size.height())),
        )
    else:
        size = initial
    dialog.setMinimumSize(minimum)
    dialog.resize(size)
    dialog.move(available.center() - dialog.rect().center())


def save_wysiwyg_dialog_geometry(dialog: QDialog, settings, key: str) -> None:
    settings.setValue(key, dialog.size())


def configure_wysiwyg_scroll_area(scroll: QScrollArea, panel: QWidget) -> None:
    """Keep settings panels fluid in width and scroll vertically only if needed."""
    scroll.setWidget(panel)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setMinimumWidth(SETTINGS_PANEL_WIDTH)
    panel.setMinimumWidth(SETTINGS_PANEL_WIDTH - 20)


def configure_wysiwyg_form(form: QFormLayout) -> None:
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)


def apply_wysiwyg_dialog_palette(widget: QWidget, colors: dict[str, str] | None = None) -> None:
    """Apply native roles, optionally using BildBlick's active theme colors."""
    palette = QPalette(widget.palette())
    if colors is not None:
        roles = {
            QPalette.ColorRole.Window: colors["window"],
            QPalette.ColorRole.WindowText: colors["text"],
            QPalette.ColorRole.Base: colors["panel"],
            QPalette.ColorRole.AlternateBase: colors["preview"],
            QPalette.ColorRole.Text: colors["text"],
            QPalette.ColorRole.Button: colors["button"],
            QPalette.ColorRole.ButtonText: colors["text"],
            QPalette.ColorRole.Highlight: colors["selection"],
            QPalette.ColorRole.HighlightedText: colors["selection_text"],
        }
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            for role, color in roles.items():
                palette.setColor(group, role, color)
        for role, color in roles.items():
            palette.setColor(QPalette.ColorGroup.Disabled, role, color)
        disabled_text = colors.get("muted", colors["text"])
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled_text)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_text)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_text)
    widget.setPalette(palette)


def apply_wysiwyg_theme(dialog: QDialog, theme_colors: dict[str, str] | None = None) -> None:
    """Bind a WYSIWYG dialog to BildBlick's effective appearance.

    ``None`` deliberately preserves the system palette, while a BildBlick
    scheme supplies its established colors through Qt palette roles.
    """
    apply_wysiwyg_dialog_palette(dialog, theme_colors)


def wysiwyg_dialog_stylesheet(object_name: str) -> str:
    """Use palette roles so dialog text follows the current system appearance."""
    return f"""
QDialog#{object_name} QCheckBox {{ spacing: 8px; }}
QDialog#{object_name} QCheckBox::indicator {{ margin-right: 0; }}
QDialog#{object_name} {{ background-color: palette(window); color: palette(window-text); }}
QDialog#{object_name} QScrollArea, QDialog#{object_name} QWidget#wysiwygPrintSettingsPanel {{ background-color: palette(window); }}
QDialog#{object_name} QLabel {{ background-color: transparent; color: palette(window-text); }}
QDialog#{object_name} QComboBox, QDialog#{object_name} QSpinBox,
QDialog#{object_name} QDoubleSpinBox, QDialog#{object_name} QLineEdit {{ background-color: palette(base); color: palette(text); }}
QDialog#{object_name} QPushButton {{ background-color: palette(button); color: palette(button-text); }}
QDialog#{object_name} QListWidget {{
    background-color: palette(base); color: palette(text);
    selection-background-color: palette(highlight);
    selection-color: palette(highlighted-text);
}}
"""
