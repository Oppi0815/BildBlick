from pathlib import Path


def test_linux_build_spec_uses_single_file_output():
    spec_path = Path(__file__).resolve().parents[1] / "bildbetrachter.spec"
    spec_text = spec_path.read_text(encoding="utf-8")

    assert 'name="BildBlick"' in spec_text
    assert 'onefile=True' in spec_text
