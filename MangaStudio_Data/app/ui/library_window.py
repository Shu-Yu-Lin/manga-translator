"""Library, create/edit dialogs and page reader for local manga readers.

Each book lives in ``<root>/<id>/``: ``reader.json``, ``source/``, ``translated/``
and ``dict.txt`` (the per-book pre-translation dictionary).
"""

import json
import re
import shutil
import sys
import time
import uuid
from pathlib import Path

from omegaconf import OmegaConf
from PySide6.QtCore import QProcess, QProcessEnvironment, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

REPO = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = Path.home() / "Library" / "Application Support" / "MangaStudio"
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
LANGUAGES = {"CHT": "Traditional Chinese", "ENG": "English"}
COVER_SIZE = QSize(160, 240)
PDF_LONG_EDGE = 2048


# ---------------------------------------------------------------- storage


def validate_files(files):
    """Return an error message, or None if `files` is one PDF or only images."""
    if not files:
        return "Choose one PDF or some images."
    exts = {Path(f).suffix.lower() for f in files}
    if ".pdf" in exts:
        return None if len(files) == 1 else "Choose one PDF, or images only (not both)."
    if not exts <= IMAGE_EXTS:
        return "Only PDF, JPG, JPEG and PNG files are supported."
    return None


def natural_key(path):
    return [
        int(t) if t.isdigit() else t.lower()
        for t in re.split(r"(\d+)", Path(path).name)
    ]


def import_files(dest, files):
    """Copy images (natural order) or render a PDF into `dest` as 001.png, 002.jpg, ..."""
    dest.mkdir(parents=True)
    if files[0].lower().endswith(".pdf"):
        doc = QPdfDocument(None)
        doc.load(files[0])
        if doc.pageCount() == 0:
            raise ValueError(f"Could not read any pages from {Path(files[0]).name}.")
        names = []
        for i in range(doc.pageCount()):
            name = f"{i + 1:03d}.png"
            size = doc.pagePointSize(i)
            # 2048 px long edge: the detector and OCR need big pages; a 144 dpi render was ~600x850
            doc.render(
                i, (size * (PDF_LONG_EDGE / max(size.width(), size.height()))).toSize()
            ).save(str(dest / name))
            names.append(name)
        return names
    paths = sorted(files, key=natural_key)
    names = [f"{i:03d}{Path(p).suffix.lower()}" for i, p in enumerate(paths, 1)]
    for path, name in zip(paths, names):
        shutil.copy(path, dest / name)
    return names


def save_book(root, book):
    folder = root / book["id"]
    (folder / "reader.json").write_text(
        json.dumps(book, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Terms are escaped so users type plain words; see load_dictionary for the format.
    lines = [f"{re.escape(jp)} {tr}".rstrip() for jp, tr in book["dictionary"]]
    (folder / "dict.txt").write_text(
        "".join(line + "\n" for line in lines), encoding="utf-8"
    )


def create_book(root, title, description, target_lang, files):
    book_id = uuid.uuid4().hex[:8]
    folder = root / book_id
    try:
        pages = import_files(folder / "source", files)
        (folder / "translated").mkdir()
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    book = {
        "id": book_id,
        "title": title,
        "description": description,
        "target_lang": target_lang,
        "status": "processing",
        "created": time.time(),
        "cover": None,
        "dictionary": [],
        "prompt": "",
        "pages": [{"file": name, "status": "pending"} for name in pages],
    }
    save_book(root, book)
    return book


def load_books(root):
    """Newest first. A book still 'processing' was cut off by an app exit, so it becomes 'failed'."""
    books = []
    for path in root.glob("*/reader.json"):
        book = json.loads(path.read_text(encoding="utf-8"))
        if book["status"] == "processing":
            book["status"] = "failed"
            save_book(root, book)
        books.append(book)
    return sorted(books, key=lambda b: b["created"], reverse=True)


def cover_path(root, book):
    folder = root / book["id"]
    return (
        folder / book["cover"]
        if book["cover"]
        else folder / "source" / book["pages"][0]["file"]
    )


def page_path(root, book, index):
    """The translated page, or the original if that page has no translation."""
    page = book["pages"][index]
    translated = root / book["id"] / "translated" / page["file"]
    if page["status"] == "done" and translated.exists():
        return translated, True
    return root / book["id"] / "source" / page["file"], False


def failed_count(book):
    return sum(p["status"] == "failed" for p in book["pages"])


def readable(book):
    return book["status"] != "processing" and any(
        p["status"] == "done" for p in book["pages"]
    )


def no_spaces(text):
    # load_dictionary splits each line on whitespace, so terms can't contain any.
    return "".join(text.split())


def card_color(widget):
    """The book-card background (also used by the dialog inputs), semi-transparent."""
    c = widget.palette().alternateBase().color()
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, 50%)"


# ---------------------------------------------------------------- dialogs


class NewBookDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New manga")
        self.files = []

        self.title = QLineEdit(placeholderText="e.g. One Piece vol. 1")
        self.description = QPlainTextEdit()
        self.description.setFixedHeight(70)
        self.lang_buttons = {
            code: QRadioButton(name) for code, name in LANGUAGES.items()
        }
        self.lang_buttons["CHT"].setChecked(True)
        langs = QHBoxLayout()
        for button in self.lang_buttons.values():
            langs.addWidget(button)
        langs.addStretch()

        pick = QPushButton("Choose PDF or images…")
        pick.clicked.connect(self.pick_files)
        self.files_label = QLabel("No files chosen")
        self.error = QLabel()
        self.error.hide()
        files_row = QHBoxLayout()
        files_row.addWidget(pick)
        files_row.addWidget(self.files_label, 1)

        form = QFormLayout(labelAlignment=Qt.AlignLeft)
        form.addRow("Title", self.title)
        form.addRow("Description (optional)", self.description)
        form.addRow("Translate to", langs)
        form.setRowVisible(langs, False)  # ponytail: only CHT supported for now, show the row when ENG is ready
        form.addRow("Pages", files_row)
        form.addRow("", self.error)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.submit = self.buttons.addButton("Translate", QDialogButtonBox.AcceptRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(
            QLabel("One PDF, or several JPG/PNG images (sorted by file name).")
        )
        layout.addWidget(self.buttons)
        self.title.textChanged.connect(self.update_submit)
        self.update_submit()
        self.setMinimumWidth(480)

    def pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Choose pages", "", "PDF or images (*.pdf *.jpg *.jpeg *.png)"
        )
        if not files:
            return
        self.files = files
        error = validate_files(files)
        self.error.setText(error or "")
        self.error.setVisible(bool(error))
        self.files_label.setText(
            Path(files[0]).name if len(files) == 1 else f"{len(files)} images"
        )
        self.update_submit()

    def update_submit(self):
        self.submit.setEnabled(
            bool(self.title.text().strip()) and validate_files(self.files) is None
        )

    def values(self):
        lang = next(code for code, b in self.lang_buttons.items() if b.isChecked())
        return (
            self.title.text().strip(),
            self.description.toPlainText().strip(),
            lang,
            self.files,
        )


class EditBookDialog(QDialog):
    def __init__(self, root, book, job_running, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit “{book['title']}”")
        self.setStyleSheet(
            "QLineEdit, QPlainTextEdit, QTableWidget { border: 1px solid palette(mid);"
            f" border-radius: 4px; background: {card_color(self)}; }}"
        )
        self.retranslate = False
        self.retranslate_page = None  # index of the single page to redo

        # Basic
        self.title = QLineEdit(book["title"])
        self.description = QPlainTextEdit(book["description"])
        self.description.setFixedHeight(70)
        basic = QWidget()
        form = QFormLayout(
            basic,
            labelAlignment=Qt.AlignLeft | Qt.AlignTop,
            formAlignment=Qt.AlignLeft | Qt.AlignTop,
            rowWrapPolicy=QFormLayout.WrapAllRows,  # labels above full-width fields
            fieldGrowthPolicy=QFormLayout.AllNonFixedFieldsGrow,  # macOS style defaults to "stay at size hint"
        )
        form.addRow("Title", self.title)
        form.addRow("Description", self.description)

        # Translation Rules
        self.prompt = QPlainTextEdit(book.get("prompt", ""))
        self.prompt.setFixedHeight(70)
        self.prompt.setPlaceholderText(
            "Added to the translator's system prompt, e.g. who the characters are"
        )
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Japanese", "Use instead"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.verticalHeader().hide()
        for row in book["dictionary"] + [["", ""]]:  # trailing empty row for new terms
            self.add_row(*row)
        self.table.itemChanged.connect(self.grow_table)
        rules = QWidget()
        rules_layout = QVBoxLayout(rules)
        rules_layout.addWidget(QLabel("Translator notes"))
        rules_layout.addWidget(self.prompt)
        rules_layout.addWidget(QLabel("<b>Dictionary</b>"))
        rules_layout.addWidget(
            QLabel(
                "Terms replaced in the Japanese text before translation, e.g. character names.\n"
                "Spaces are removed. Clear a Japanese cell to remove a term."
            )
        )
        rules_layout.addWidget(self.table, 1)
        rules_layout.addWidget(QLabel("Notes and dictionary take effect when you retranslate."))

        # Single Page Translate
        self.page_spin = QSpinBox(minimum=1, maximum=len(book["pages"]))
        preview = QLabel()
        preview.setFixedSize(160, 240)
        preview.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        def show_page(number):
            path, _ = page_path(root, book, number - 1)
            preview.setPixmap(
                QPixmap(str(path)).scaled(preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

        self.page_spin.valueChanged.connect(show_page)
        show_page(1)
        self.page_note = QPlainTextEdit()
        self.page_note.setFixedHeight(70)
        page_row = QHBoxLayout()
        page_row.addWidget(QLabel("Page"))
        page_row.addWidget(self.page_spin)
        page_row.addWidget(QLabel(f"of {len(book['pages'])}"))
        page_row.addStretch()
        single = QWidget()
        single_layout = QVBoxLayout(single)
        single_layout.addLayout(page_row)
        single_layout.addWidget(preview)
        single_layout.addWidget(QLabel("Instructions for this run only (optional)"))
        single_layout.addWidget(self.page_note)
        single_layout.addStretch()

        tabs = QTabWidget()
        tabs.addTab(basic, "Basic")
        tabs.addTab(rules, "Translation Rules")
        tabs.addTab(single, "Single Page Translate")

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Save)
        rerun = buttons.addButton("Save && retranslate", QDialogButtonBox.AcceptRole)
        redo_page = buttons.addButton("Retranslate this page", QDialogButtonBox.ActionRole)
        for button in (rerun, redo_page):
            button.setEnabled(not job_running)
            if job_running:
                button.setToolTip("A translation is already running")
        rerun.clicked.connect(lambda: setattr(self, "retranslate", True))
        redo_page.clicked.connect(self.pick_page)
        # the last tab has its own single action; the others share Save / Save & retranslate / Cancel
        general = (rerun, *(buttons.button(b) for b in (QDialogButtonBox.Save, QDialogButtonBox.Cancel)))

        def show_buttons(tab):
            for button in general:
                button.setVisible(tab != 2)
            redo_page.setVisible(tab == 2)

        tabs.currentChanged.connect(show_buttons)
        show_buttons(0)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.title.textChanged.connect(
            lambda t: buttons.button(QDialogButtonBox.Save).setEnabled(bool(t.strip()))
        )

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)
        self.resize(520, 560)

    def pick_page(self):
        self.retranslate_page = self.page_spin.value() - 1
        self.accept()

    def add_row(self, jp, tr):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(jp))
        self.table.setItem(row, 1, QTableWidgetItem(tr))

    def grow_table(self, item):
        if item.row() == self.table.rowCount() - 1 and item.text().strip():
            self.table.blockSignals(True)
            self.add_row("", "")
            self.table.blockSignals(False)

    def apply(self, book):
        book["title"] = self.title.text().strip() or book["title"]
        book["description"] = self.description.toPlainText().strip()
        book["prompt"] = self.prompt.toPlainText().strip()
        rows = (
            (self.table.item(r, 0).text(), self.table.item(r, 1).text())
            for r in range(self.table.rowCount())
        )
        book["dictionary"] = [
            [no_spaces(jp), no_spaces(tr)] for jp, tr in rows if no_spaces(jp)
        ]


# ---------------------------------------------------------------- home


class BookCard(QFrame):
    def __init__(self, root, book, menu):
        super().__init__()
        self.setObjectName("card")
        self.setStyleSheet(
            "#card { border: 1px solid palette(mid); border-radius: 8px;"
            f" background: {card_color(self)}; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        cover = QLabel()
        cover.setFixedSize(COVER_SIZE)
        cover.setAlignment(Qt.AlignCenter)
        cover.setPixmap(
            QPixmap(str(cover_path(root, book))).scaled(
                COVER_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )
        layout.addWidget(cover)

        self.bar = None
        if book["status"] == "processing":
            effect = QGraphicsOpacityEffect(cover)
            effect.setOpacity(0.7)
            cover.setGraphicsEffect(effect)
            self.bar = QProgressBar(
                maximum=len(book["pages"]), format="Translating %p%"
            )
            self.bar.setValue(sum(p["status"] != "pending" for p in book["pages"]))
            layout.addWidget(self.bar)
        elif book["status"] == "failed":
            layout.addWidget(QLabel("Failed. Use ⋯ to retry"))
        elif failed_count(book):
            layout.addWidget(QLabel(f"{failed_count(book)} pages failed"))

        if menu:
            more = QToolButton(cover, text="⋯", popupMode=QToolButton.InstantPopup)
            more.setAccessibleName(f"More actions for {book['title']}")
            more.setFixedSize(26, 26)
            more.move(COVER_SIZE.width() - 32, 6)
            # dark disc keeps the button visible on any cover
            more.setStyleSheet(
                "QToolButton { background: rgba(0,0,0,150); color: white; border: none;"
                " border-radius: 13px; } QToolButton::menu-indicator { image: none; }"
            )
            more.setMenu(menu)
            self.menu = menu  # QToolButton does not own its menu

        title = QLabel()
        title.setStyleSheet("font-weight: bold;")
        title.setText(
            title.fontMetrics().elidedText(
                book["title"], Qt.ElideRight, COVER_SIZE.width()
            )
        )
        layout.addWidget(title)
        # always present (even if empty) so every card has the same height
        description = QLabel()
        description.setStyleSheet("color: gray;")
        first_line = book["description"].split("\n")[0]
        description.setText(
            description.fontMetrics().elidedText(
                first_line, Qt.ElideRight, COVER_SIZE.width()
            )
        )
        layout.addWidget(description)
        layout.addStretch()
        self.setToolTip(f"{book['title']}\n\n{book['description']}".strip())


class HomeView(QWidget):
    def __init__(self):
        super().__init__()
        self.new_button = QPushButton("+ New manga")
        header = QHBoxLayout()
        heading = QLabel("<h2>Library</h2>")
        header.addWidget(heading)
        header.addStretch()
        header.addWidget(self.new_button)

        self.empty = QLabel(
            "No manga yet. Click “+ New manga” to translate your first book."
        )
        self.empty.setAlignment(Qt.AlignCenter)
        self.list = QListWidget(
            viewMode=QListWidget.IconMode,
            resizeMode=QListWidget.Adjust,
            movement=QListWidget.Static,
            gridSize=QSize(200, 360),
        )
        self.list.setSelectionMode(QAbstractItemView.NoSelection)
        self.list.setViewportMargins(12, 12, 12, 12)
        self.list.setStyleSheet("QListWidget { background: transparent; }")

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self.empty, 1)
        layout.addWidget(self.list, 1)


# ---------------------------------------------------------------- reader


class ReaderView(QWidget):
    back = Signal()

    def __init__(self):
        super().__init__()
        self.root = self.book = self.pixmap = None
        self.index = 0

        back = QPushButton("‹ Library")
        back.clicked.connect(self.back)
        self.title = QLabel()
        self.counter = QLabel()
        top = QHBoxLayout()
        top.addWidget(back)
        top.addWidget(self.title, 1, Qt.AlignCenter)
        top.addWidget(self.counter)

        self.image = QLabel(alignment=Qt.AlignCenter)
        self.image.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.failed_note = QLabel(
            "Translation failed for this page. Showing the original."
        )
        self.failed_note.setAlignment(Qt.AlignCenter)

        self.prev_button = QPushButton("‹ Previous")
        self.next_button = QPushButton("Next ›")
        self.prev_button.clicked.connect(lambda: self.go(-1))
        self.next_button.clicked.connect(lambda: self.go(1))
        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(self.prev_button)
        bottom.addWidget(self.next_button)
        bottom.addStretch()

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.image, 1)
        layout.addWidget(self.failed_note)
        layout.addLayout(bottom)

        for key, step in ((Qt.Key_Left, -1), (Qt.Key_Right, 1)):
            QShortcut(
                QKeySequence(key),
                self,
                lambda s=step: self.go(s),
                context=Qt.WidgetWithChildrenShortcut,
            )
        QShortcut(
            QKeySequence(Qt.Key_Escape),
            self,
            self.back.emit,
            context=Qt.WidgetWithChildrenShortcut,
        )

    def open(self, root, book):
        self.root, self.book, self.index = root, book, 0
        self.title.setText(f"<b>{book['title']}</b>")
        self.go(0)

    def go(self, step):
        self.index = max(0, min(len(self.book["pages"]) - 1, self.index + step))
        path, translated = page_path(self.root, self.book, self.index)
        self.pixmap = QPixmap(str(path))
        self.failed_note.setVisible(not translated)
        self.counter.setText(f"{self.index + 1} / {len(self.book['pages'])}")
        self.prev_button.setEnabled(self.index > 0)
        self.next_button.setEnabled(self.index < len(self.book["pages"]) - 1)
        self.fit()

    def fit(self):
        if self.pixmap:
            self.image.setPixmap(
                self.pixmap.scaled(
                    self.image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()


# ---------------------------------------------------------------- window


class LibraryWindow(QMainWindow):
    def __init__(self, root=DEFAULT_ROOT):
        super().__init__()
        self.setWindowTitle("Manga Translator")
        self.resize(1000, 760)
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.books = load_books(self.root)
        self.cards = {}
        self.job = None  # the one book being translated
        self.proc = None
        self.timer = QTimer(self, interval=1000, timeout=self.update_progress)

        self.home = HomeView()
        self.home.new_button.clicked.connect(self.new_book)
        self.home.list.itemClicked.connect(self.open_item)
        self.home.list.itemActivated.connect(self.open_item)
        self.reader = ReaderView()
        self.reader.back.connect(lambda: self.stack.setCurrentWidget(self.home))
        self.stack = QStackedWidget()
        self.stack.addWidget(self.home)
        self.stack.addWidget(self.reader)
        self.setCentralWidget(self.stack)
        self.refresh()

    def refresh(self):
        running = self.job is not None
        self.home.new_button.setEnabled(not running)
        self.home.new_button.setToolTip(
            "A translation is already running" if running else ""
        )
        self.home.list.clear()
        self.cards = {}
        for book in self.books:
            card = BookCard(
                self.root,
                book,
                None if book["status"] == "processing" else self.menu_for(book),
            )
            item = QListWidgetItem(self.home.list)
            item.setData(Qt.UserRole, book["id"])
            item.setSizeHint(card.sizeHint())
            if not readable(book):
                item.setFlags(Qt.NoItemFlags)
            self.home.list.setItemWidget(item, card)
            self.cards[book["id"]] = card
        self.home.empty.setVisible(not self.books)
        self.home.list.setVisible(bool(self.books))

    def menu_for(self, book):
        menu = QMenu()
        menu.addAction("Edit…", lambda: self.edit_book(book))
        menu.addAction("Change cover…", lambda: self.change_cover(book))
        if book["status"] == "failed":
            menu.addAction("Retry", lambda: self.start_job(book)).setEnabled(
                self.job is None
            )
        menu.addSeparator()
        menu.addAction("Delete…", lambda: self.delete_book(book))
        return menu

    def open_item(self, item):
        book = next(b for b in self.books if b["id"] == item.data(Qt.UserRole))
        if readable(book):
            self.reader.open(self.root, book)
            self.stack.setCurrentWidget(self.reader)
            self.reader.setFocus()

    def new_book(self):
        dialog = NewBookDialog(self)
        if not dialog.exec():
            return
        QApplication.setOverrideCursor(
            Qt.WaitCursor
        )  # ponytail: PDF render blocks the UI; thread it if big books freeze
        try:
            book = create_book(self.root, *dialog.values())
        except Exception as e:
            QMessageBox.warning(
                self, "Could not add manga", f"{e}\n\nCheck the files and try again."
            )
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.books.insert(0, book)
        self.start_job(book)

    def change_cover(self, book):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose cover", "", "Images (*.jpg *.jpeg *.png)"
        )
        if path:
            name = "cover" + Path(path).suffix.lower()
            shutil.copy(path, self.root / book["id"] / name)
            book["cover"] = name
            save_book(self.root, book)
            self.refresh()

    def edit_book(self, book):
        dialog = EditBookDialog(self.root, book, self.job is not None, self)
        if not dialog.exec():
            return
        dialog.apply(book)
        save_book(self.root, book)
        if dialog.retranslate_page is not None:
            self.start_job(book, dialog.retranslate_page, dialog.page_note.toPlainText().strip())
        elif dialog.retranslate:
            self.start_job(book)
        else:
            self.refresh()

    def confirm_delete(self, book):
        box = QMessageBox(
            QMessageBox.Warning,
            "Delete manga",
            f"Delete “{book['title']}”? Its pages are removed from disk.",
            QMessageBox.Cancel,
            self,
        )
        delete = box.addButton("Delete", QMessageBox.DestructiveRole)
        box.setDefaultButton(QMessageBox.Cancel)
        box.exec()
        return box.clickedButton() is delete

    def delete_book(self, book):
        if self.confirm_delete(book):
            shutil.rmtree(self.root / book["id"])
            self.books.remove(book)
            self.refresh()

    def start_job(self, book, page=None, note=""):
        """Translate the whole book, or only pages[page] (with a one-shot note)."""
        folder = self.root / book["id"]
        pages = book["pages"] if page is None else [book["pages"][page]]
        for p in pages:
            (folder / "translated" / p["file"]).unlink(missing_ok=True)
            p["status"] = "pending"
        book["status"] = "processing"
        save_book(self.root, book)
        self.job = book
        self.refresh()
        try:
            self.run_pipeline(book, page, note)
        except Exception as e:
            QMessageBox.warning(self, "Could not start translation", str(e))
            self.finish_job()

    def run_pipeline(self, book, page=None, note=""):
        folder = self.root / book["id"]
        source, output = folder / "source", folder / "translated"
        if page is not None:  # a file path for -o makes the CLI write exactly that file
            name = book["pages"][page]["file"]
            source, output = source / name, output / name
        base = REPO / "configs" / f"{book['target_lang'].lower()}.json"
        if not base.exists():
            raise FileNotFoundError(
                f"No translation config for {LANGUAGES[book['target_lang']]} yet."
            )
        config = json.loads(base.read_text(encoding="utf-8"))
        gpt = OmegaConf.load(REPO / "configs" / "gpt_config.yaml")
        # the template goes through str.format, so literal braces must be doubled
        extras = [t.replace("{", "{{").replace("}", "}}") for t in (book.get("prompt", ""), note) if t]
        gpt.chat_system_template += "".join(f"\n\n{t}" for t in extras)
        OmegaConf.save(gpt, folder / "gpt_config.yaml")
        config["translator"]["gpt_config"] = str(folder / "gpt_config.yaml")
        (folder / "config.json").write_text(
            json.dumps(config, indent=2), encoding="utf-8"
        )
        env = QProcessEnvironment.systemEnvironment()
        if not env.contains("CUSTOM_OPENAI_MODEL"):
            env.insert("CUSTOM_OPENAI_MODEL", "gemma4:e4b")
        self.proc = QProcess(self)
        self.proc.setProcessEnvironment(env)
        self.proc.setWorkingDirectory(str(REPO))
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.setStandardOutputFile(str(folder / "job.log"))
        self.proc.finished.connect(self.finish_job)
        self.proc.start(
            sys.executable,
            [
                "-m",
                "manga_translator",
                "local",
                "-i",
                str(source),
                "-o",
                str(output),
                "--config-file",
                str(folder / "config.json"),
                "--use-gpu",
                "--attempts",
                "3",
                "--ignore-errors",
                "--pre-dict",
                str(folder / "dict.txt"),
                "--post-dict",
                str(REPO / "configs" / "dict" / "tw.post.txt"),
            ],
        )
        if self.proc.state() == QProcess.NotRunning:
            raise RuntimeError(self.proc.errorString())
        self.timer.start()

    def update_progress(self):
        book = self.job
        for page in book["pages"]:
            if (self.root / book["id"] / "translated" / page["file"]).exists():
                page["status"] = "done"
        self.cards[book["id"]].bar.setValue(
            sum(p["status"] != "pending" for p in book["pages"])
        )

    def finish_job(self, *_):
        """Pages with no file in translated/ failed; a book with no page translated at all is failed."""
        self.timer.stop()
        book = self.job
        for page in book["pages"]:
            done = (self.root / book["id"] / "translated" / page["file"]).exists()
            page["status"] = "done" if done else "failed"
        book["status"] = (
            "done" if any(p["status"] == "done" for p in book["pages"]) else "failed"
        )
        save_book(self.root, book)
        self.job = self.proc = None
        self.refresh()

    def closeEvent(self, event):
        if self.proc:
            self.proc.kill()  # the book stays 'processing' on disk and loads as failed next time
            self.proc.waitForFinished(2000)
        super().closeEvent(event)
