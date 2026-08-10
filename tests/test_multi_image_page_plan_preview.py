from pathlib import Path

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from bildbetrachter import MultiImagePrintPreview
from printing.multi_image_print import MultiImagePrintSettings


def image_paths(tmp_path: Path, count: int) -> list[Path]:
    paths = []
    for index in range(count):
        image = QImage(640, 360, QImage.Format.Format_ARGB32)
        image.fill(QColor("red" if index % 2 else "blue"))
        path = tmp_path / f"{index}.png"
        assert image.save(str(path))
        paths.append(path)
    return paths


def test_preview_uses_page_plans_for_navigation_and_real_paper_proportions(tmp_path):
    QApplication.instance() or QApplication([])
    preview = MultiImagePrintPreview()
    settings = MultiImagePrintSettings(images_per_page=4, orientation="landscape")
    preview.set_options(image_paths(tmp_path, 5), settings, True, 8, "10.08.2026")
    assert preview.page_count == 2
    assert preview.page_index == 1
    assert preview.page_plans[0].page_size.width_mm > preview.page_plans[0].page_size.height_mm
    assert [len(plan.image_elements) for plan in preview.page_plans] == [4, 1]


def test_preview_regenerates_contact_sheet_text_from_current_settings(tmp_path):
    QApplication.instance() or QApplication([])
    preview = MultiImagePrintPreview()
    settings = MultiImagePrintSettings(
        images_per_page=4, contact_sheet=True, show_filename=True,
        show_header=True, header_text="Titel", show_page_number=True,
    )
    preview.set_options(image_paths(tmp_path, 1), settings, False, 0, "10.08.2026")
    roles = {text.semantic_role for text in preview.page_plans[0].text_elements}
    assert {"filename", "header", "page_number"} <= roles
