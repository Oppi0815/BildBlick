"""Shared, palette-friendly widget setup for the WYSIWYG print dialogs."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QGuiApplication, QPalette, QPolygon
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
    panel.setAutoFillBackground(True)
    scroll.viewport().setAutoFillBackground(True)
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
            QPalette.ColorRole.Mid: colors.get("border", colors["panel"]),
        }
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            for role, color in roles.items():
                palette.setColor(group, role, color)
        for role, color in roles.items():
            palette.setColor(QPalette.ColorGroup.Disabled, role, color)
        disabled_text = colors.get("muted", colors["text"])
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, colors["preview"])
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, colors["preview"])
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
    # QAbstractScrollArea viewports and native macOS controls often retain
    # their creation-time application palette. Apply the same roles to the
    # already-created central children as well.
    for widget in dialog.findChildren(QWidget):
        apply_wysiwyg_dialog_palette(widget, theme_colors)
    dialog.setStyleSheet(wysiwyg_dialog_stylesheet(dialog.objectName(), theme_colors))
    if theme_colors is not None:
        _install_control_arrows(dialog)


def wysiwyg_dialog_stylesheet(object_name: str, colors: dict[str, str] | None = None) -> str:
    """Return a stylesheet scoped to one dialog and its native macOS controls."""
    values = {
        "window": "palette(window)", "text": "palette(window-text)",
        "base": "palette(base)", "button": "palette(button)",
        "button_text": "palette(button-text)", "highlight": "palette(highlight)",
        "highlighted_text": "palette(highlighted-text)", "border": "palette(mid)",
        "disabled_text": "palette(disabled, text)", "disabled_base": "palette(alternate-base)",
    }
    if colors is not None:
        values.update({
            "window": colors["window"], "text": colors["text"],
            "base": colors["panel"], "button": colors["button"],
            "button_text": colors["text"], "highlight": colors["selection"],
            "highlighted_text": colors["selection_text"], "border": colors.get("border", colors["panel"]),
            "disabled_text": colors.get("muted", colors["text"]), "disabled_base": colors["preview"],
        })
    dark_controls = ""
    light_controls = ""
    if colors is not None and _is_dark_color(colors["window"]):
        dark_controls = f"""
QDialog#{object_name} QComboBox, QDialog#{object_name} QSpinBox,
QDialog#{object_name} QDoubleSpinBox, QDialog#{object_name} QLineEdit {{
    border: 1px solid {values['border']}; border-radius: 4px; padding: 2px 6px;
}}
QDialog#{object_name} QComboBox {{ padding-right: 28px; }}
QDialog#{object_name} QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: top right; width: 24px;
    background-color: {values['button']}; border-left: 1px solid {values['border']};
    border-top-right-radius: 3px; border-bottom-right-radius: 3px;
}}
QDialog#{object_name} QComboBox QAbstractItemView {{
    background-color: {values['base']}; color: {values['text']};
    selection-background-color: {values['highlight']}; selection-color: {values['highlighted_text']};
}}
QDialog#{object_name} QSpinBox, QDialog#{object_name} QDoubleSpinBox {{ padding-right: 40px; }}
QDialog#{object_name} QSpinBox::up-button, QDialog#{object_name} QSpinBox::down-button,
QDialog#{object_name} QDoubleSpinBox::up-button, QDialog#{object_name} QDoubleSpinBox::down-button {{
    width: 20px; background-color: {values['button']}; border-left: 1px solid {values['border']};
}}
QDialog#{object_name} QSpinBox::up-button, QDialog#{object_name} QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; border-bottom: 1px solid {values['border']}; }}
QDialog#{object_name} QSpinBox::down-button, QDialog#{object_name} QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; }}
QDialog#{object_name} QComboBox:focus, QDialog#{object_name} QSpinBox:focus,
QDialog#{object_name} QDoubleSpinBox:focus, QDialog#{object_name} QLineEdit:focus {{ border: 2px solid {values['highlight']}; }}
QDialog#{object_name} QPushButton:hover {{ border-color: {values['highlight']}; }}
QDialog#{object_name} QPushButton:pressed {{ background-color: {values['highlight']}; color: {values['highlighted_text']}; }}
QDialog#{object_name} QPushButton:focus {{ border: 2px solid {values['highlight']}; }}
"""
    elif colors is not None:
        light_controls = f"""
QDialog#{object_name} QComboBox, QDialog#{object_name} QSpinBox,
QDialog#{object_name} QDoubleSpinBox, QDialog#{object_name} QLineEdit {{
    border: 1px solid {values['border']}; border-radius: 4px; padding: 2px 6px;
}}
QDialog#{object_name} QComboBox {{ padding-right: 28px; }}
QDialog#{object_name} QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: top right; width: 24px;
    background-color: {values['button']}; border-left: 1px solid {values['border']};
    border-top-right-radius: 3px; border-bottom-right-radius: 3px;
}}
QDialog#{object_name} QComboBox QAbstractItemView {{
    background-color: {values['base']}; color: {values['text']};
    selection-background-color: {values['highlight']}; selection-color: {values['highlighted_text']};
}}
QDialog#{object_name} QSpinBox, QDialog#{object_name} QDoubleSpinBox {{ padding-right: 40px; }}
QDialog#{object_name} QSpinBox::up-button, QDialog#{object_name} QSpinBox::down-button,
QDialog#{object_name} QDoubleSpinBox::up-button, QDialog#{object_name} QDoubleSpinBox::down-button {{
    width: 20px; background-color: {values['button']}; border-left: 1px solid {values['border']};
}}
QDialog#{object_name} QSpinBox::up-button, QDialog#{object_name} QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; border-bottom: 1px solid {values['border']}; }}
QDialog#{object_name} QSpinBox::down-button, QDialog#{object_name} QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; }}
QDialog#{object_name} QComboBox:focus, QDialog#{object_name} QSpinBox:focus,
QDialog#{object_name} QDoubleSpinBox:focus, QDialog#{object_name} QLineEdit:focus {{ border: 2px solid {values['highlight']}; }}
"""
    return f"""
QDialog#{object_name} QCheckBox {{ spacing: 8px; }}
QDialog#{object_name} QCheckBox::indicator {{ margin-right: 0; }}
QDialog#{object_name}, QDialog#{object_name} QWidget#wysiwygPrintSettingsPanel,
QDialog#{object_name} QWidget#wysiwygPreviewPanel {{ background-color: {values['window']}; color: {values['text']}; }}
QDialog#{object_name} QScrollArea, QDialog#{object_name} QScrollArea > QWidget,
QDialog#{object_name} QScrollArea > QWidget > QWidget {{ background-color: {values['window']}; color: {values['text']}; }}
QDialog#{object_name} QLabel {{ background-color: transparent; color: {values['text']}; }}
QDialog#{object_name} QCheckBox, QDialog#{object_name} QRadioButton,
QDialog#{object_name} QGroupBox, QDialog#{object_name} QGroupBox::title {{ color: {values['text']}; }}
QDialog#{object_name} QComboBox, QDialog#{object_name} QSpinBox,
QDialog#{object_name} QDoubleSpinBox, QDialog#{object_name} QLineEdit {{ background-color: {values['base']}; color: {values['text']}; border-color: {values['border']}; }}
QDialog#{object_name} QPushButton {{ background-color: {values['button']}; color: {values['button_text']}; border-color: {values['border']}; }}
QDialog#{object_name} QListWidget {{
    background-color: {values['base']}; color: {values['text']}; border-color: {values['border']};
    selection-background-color: {values['highlight']};
    selection-color: {values['highlighted_text']};
}}
QDialog#{object_name} QCheckBox:disabled, QDialog#{object_name} QRadioButton:disabled,
QDialog#{object_name} QGroupBox:disabled, QDialog#{object_name} QLabel:disabled {{ color: {values['disabled_text']}; }}
QDialog#{object_name} QComboBox:disabled, QDialog#{object_name} QSpinBox:disabled,
QDialog#{object_name} QDoubleSpinBox:disabled, QDialog#{object_name} QLineEdit:disabled,
QDialog#{object_name} QLineEdit[readOnly="true"] {{ background-color: {values['disabled_base']}; color: {values['disabled_text']}; border-color: {values['border']}; }}
QDialog#{object_name} QListWidget:disabled {{ background-color: {values['disabled_base']}; color: {values['disabled_text']}; }}
{dark_controls}
{light_controls}
"""


def _is_dark_color(value: str) -> bool:
    """Return whether a hex theme color is dark enough to need dark controls."""
    color = value.lstrip("#")
    if len(color) != 6:
        return False
    red, green, blue = (int(color[index:index + 2], 16) for index in (0, 2, 4))
    return (red * 299 + green * 587 + blue * 114) / 1000 < 128


def _install_control_arrows(dialog: QDialog) -> None:
    """Add visible, non-intercepting arrow overlays to existing controls."""
    for widget in dialog.findChildren(QWidget):
        if not (widget.inherits("QComboBox") or widget.inherits("QAbstractSpinBox")):
            continue
        if widget.property("wysiwygDarkArrowStyle"):
            continue
        if widget.inherits("QComboBox"):
            _WysiwygControlArrowIndicator(widget, "down", "wysiwygComboDownArrow")
        else:
            _WysiwygControlArrowIndicator(widget, "up", "wysiwygSpinUpArrow")
            _WysiwygControlArrowIndicator(widget, "down", "wysiwygSpinDownArrow")
        widget.setProperty("wysiwygDarkArrowStyle", True)


class _WysiwygControlArrowIndicator(QWidget):
    """A small painted indicator that follows a combo or spin box subcontrol."""

    def __init__(self, control: QWidget, direction: str, object_name: str) -> None:
        super().__init__(control)
        self._control, self._direction = control, direction
        self.setObjectName(object_name)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        control.installEventFilter(self)
        self._place()
        self.show()

    def eventFilter(self, watched, event) -> bool:
        if watched is self._control and event.type() in (QEvent.Type.Resize, QEvent.Type.EnabledChange, QEvent.Type.StyleChange):
            self._place()
            self.update()
        return False

    def _place(self) -> None:
        width = 24 if self._control.inherits("QComboBox") else 20
        if self._control.inherits("QComboBox"):
            self.setGeometry(self._control.width() - width, 0, width, self._control.height())
        else:
            half_height = self._control.height() // 2
            top = 0 if self._direction == "up" else half_height
            self.setGeometry(self._control.width() - width, top, width, self._control.height() - top if self._direction == "down" else half_height)

    def paintEvent(self, _event) -> None:
        group = QPalette.ColorGroup.Active if self._control.isEnabled() else QPalette.ColorGroup.Disabled
        color = self._control.palette().color(group, QPalette.ColorRole.Text)
        side = max(6, min(10, self.width() - 8, self.height() - 4))
        center = self.rect().center()
        half = side // 2
        if self._direction == "down":
            points = (QPoint(center.x() - half, center.y() - 2), QPoint(center.x() + half, center.y() - 2), QPoint(center.x(), center.y() + half))
        else:
            points = (QPoint(center.x() - half, center.y() + 2), QPoint(center.x() + half, center.y() + 2), QPoint(center.x(), center.y() - half))
        from PySide6.QtGui import QPainter
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QPolygon(points))
