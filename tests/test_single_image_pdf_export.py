from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from printing.layout import CaptionOptions, ImageSourceInfo, PageSizeMm, SingleImageLayout
from printing.pdf_export import ensure_pdf_suffix, export_page_plan_pdf
from printing.planner import plan_single_image


def test_pdf_export_adds_suffix_and_writes_page(tmp_path):
    QApplication.instance() or QApplication([])
    source = ImageSourceInfo(Path("image.jpg"), 300, 200, 300, 300, "image.jpg")
    plan = plan_single_image(source, SingleImageLayout(PageSizeMm.a4(), captions=CaptionOptions(show_filename=True)))
    image = QImage(300, 200, QImage.Format.Format_RGB32)
    target = export_page_plan_pdf(tmp_path / "printout", plan, lambda _source: image)
    assert target == ensure_pdf_suffix(tmp_path / "printout")
    assert target.is_file() and target.stat().st_size > 0
