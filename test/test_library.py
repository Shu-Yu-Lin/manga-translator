import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent.parent / "MangaStudio_Data"))

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.ui.library_window import LibraryWindow, create_book, load_books, validate_files

app = QApplication.instance() or QApplication([])


def test_validate_files():
    assert validate_files(["a.pdf"]) is None
    assert validate_files(["1.png", "2.JPG", "3.jpeg"]) is None
    assert validate_files([]) and validate_files(["a.pdf", "b.png"]) and validate_files(["a.gif"])


def test_book_lifecycle(tmp_path):
    images = []
    for width, name in enumerate(["p10.png", "p2.png", "p1.png"], 20):
        QImage(width, 30, QImage.Format_RGB32).save(str(tmp_path / name))
        images.append(str(tmp_path / name))
    root = tmp_path / "readers"
    root.mkdir()

    book = create_book(root, "Book", "", "ENG", images)
    assert [p["file"] for p in book["pages"]] == ["001.png", "002.png", "003.png"]
    # natural order: p1, p2, p10
    assert QImage(str(root / book["id"] / "source" / "001.png")).size() == QImage(images[2]).size()

    window = LibraryWindow(root)  # book was left 'processing', so it loads as 'failed'
    assert window.books[0]["status"] == "failed"
    window.start_job(window.books[0])
    assert not window.home.new_button.isEnabled()
    for _ in book["pages"]:
        window.tick()
    assert window.home.new_button.isEnabled()
    assert load_books(root)[0]["status"] == "done"
    assert (root / book["id"] / "translated" / "003.png").exists()

    window.books[0]["dictionary"] = [["ルフィ", "Luffy"], ["a.b", ""]]
    window.start_job(window.books[0])
    assert (root / book["id"] / "dict.txt").read_text(encoding="utf-8") == "ルフィ Luffy\na\\.b\n"
