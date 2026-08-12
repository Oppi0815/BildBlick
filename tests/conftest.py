"""Keep the process-global UI language isolated between tests."""

import pytest
from PySide6.QtCore import QSettings

import i18n


@pytest.fixture(autouse=True)
def reset_interface_language():
    i18n._language = "de"
    QSettings("BildBlick", "BildBlick").setValue(i18n.LANGUAGE_KEY, "de")
    yield
    i18n._language = "de"
    QSettings("BildBlick", "BildBlick").setValue(i18n.LANGUAGE_KEY, "de")
