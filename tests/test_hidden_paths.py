from pathlib import Path

from bildbetrachter import is_hidden_path, should_show_path, show_hidden_files_value


def test_normal_path_is_visible_when_hidden_files_are_disabled():
    assert should_show_path(Path("bild.jpg"), False)


def test_dotfiles_and_appledouble_files_are_hidden_by_default():
    assert is_hidden_path(Path(".versteckt.jpg"))
    assert is_hidden_path(Path("._Bild.jpg"))
    assert is_hidden_path(Path(".DS_Store"))
    assert not should_show_path(Path(".versteckt.jpg"), False)
    assert not should_show_path(Path("._Bild.jpg"), False)


def test_hidden_paths_are_visible_when_requested_but_dot_entries_never_are():
    assert should_show_path(Path(".versteckt.jpg"), True)
    assert not should_show_path(Path("."), True)
    assert not should_show_path(Path(".."), True)


def test_hidden_setting_defaults_to_false_and_parses_saved_true_values():
    assert not show_hidden_files_value(False)
    assert not show_hidden_files_value("false")
    assert show_hidden_files_value(True)
    assert show_hidden_files_value("true")
