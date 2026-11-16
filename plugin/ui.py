"""Toolbar action and the sync dialog: Kindle books as a tree, ticked items get synced."""

from qt.core import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    Qt,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from calibre.gui2 import Dispatcher, choose_files, error_dialog
from calibre.gui2.actions import InterfaceAction

from calibre_plugins.kindle_annotation_sync.clippings import parse_clippings
from calibre_plugins.kindle_annotation_sync.sync import (
    CHECK_MATCH,
    STYLE,
    fetch_mtp_clippings,
    find_clippings_file,
    kindle_books,
    library_epubs,
    match_book,
    mtp_kindle,
    sync_book,
)

try:  # calibre's highlight style picker; older calibre gets plain yellow
    from calibre.gui2.viewer.highlights import HighlightColorCombo, style_definition_for_name
except ImportError:
    HighlightColorCombo = None

KINDLE, CALIBRE, ANNOTATIONS, RESULT = range(4)  # tree columns
CLIP, BOOK_ID, SECTION, MANUAL = (Qt.ItemDataRole.UserRole + i for i in range(4))
CHECKED, UNCHECKED = Qt.CheckState.Checked, Qt.CheckState.Unchecked


class SyncAction(InterfaceAction):
    name = "Kindle Annotation Sync"
    action_spec = (
        "Sync Kindle annotations",
        "highlight.png",
        "Copy highlights and notes from the Kindle's My Clippings.txt into book annotations",
        None,
    )

    def genesis(self):
        self.qaction.triggered.connect(lambda: SyncDialog(self.gui).exec())


def _short(text, n=90):
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


class SyncDialog(QDialog):
    def __init__(self, gui):
        super().__init__(gui)
        self.gui = gui
        self.db = gui.current_db.new_api
        self.library = library_epubs(self.db)
        self.titles = {book_id: f"{title} — {authors}" for book_id, title, authors in self.library}
        self.setWindowTitle("Kindle Annotation Sync")
        self.resize(1100, 700)

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.source = QLabel()
        choose = QPushButton("Choose file…")
        choose.clicked.connect(self.choose_file)
        top.addWidget(self.source, 1)
        top.addWidget(choose)
        layout.addLayout(top)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Kindle", "Calibre book", "Highlights • Notes", "Sync result"])
        self.tree.setColumnWidth(KINDLE, 480)
        self.tree.setColumnWidth(CALIBRE, 300)
        self.tree.setColumnWidth(ANNOTATIONS, 150)
        self.tree.itemDoubleClicked.connect(self.pick_match)
        layout.addWidget(self.tree, 1)

        self.output = QTextEdit(readOnly=True)
        self.output.setMaximumHeight(140)
        layout.addWidget(self.output)

        bottom = QHBoxLayout()
        self.colour = HighlightColorCombo(self) if HighlightColorCombo else None
        if self.colour:
            bottom.addWidget(QLabel("Highlight colour:"))
            bottom.addWidget(self.colour)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        for label, everything in (("Sync &selected", False), ("Sync &all", True)):
            b = buttons.addButton(label, QDialogButtonBox.ButtonRole.ActionRole)
            b.clicked.connect(lambda _=False, e=everything: self.sync(e))
        bottom.addWidget(buttons, 1)
        layout.addLayout(bottom)

        path, device = find_clippings_file(gui), mtp_kindle(gui)
        if path:
            self.load(path, "Kindle")
        elif device:
            self.source.setText("Reading My Clippings.txt from the Kindle (MTP, untested)…")
            from calibre.ptempfile import PersistentTemporaryFile
            out = PersistentTemporaryFile("_My Clippings.txt").name
            gui.device_manager.create_job(
                fetch_mtp_clippings, Dispatcher(self.mtp_fetched),
                "Read Kindle My Clippings.txt", args=[device, out],
            )
        else:
            self.source.setText("No Kindle connected — choose a My Clippings.txt file.")

    def mtp_fetched(self, job):
        if not job.failed and job.result:
            self.load(job.result, "Kindle (MTP, untested)")
        else:
            self.source.setText("Couldn't find My Clippings.txt on the Kindle — choose the file.")

    def choose_file(self):
        paths = choose_files(
            self, "kindle-annotation-sync", "Choose My Clippings.txt",
            [("Kindle clippings", ["txt"])], select_only_single_file=True,
        )
        if paths:
            self.load(paths[0], paths[0])

    def books(self):
        """Top-level rows that are Kindle books from My Clippings.txt (not the section)."""
        items = (self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount()))
        return [it for it in items if not it.data(KINDLE, SECTION)]

    def load(self, path, label):
        try:
            with open(path, encoding="utf-8-sig") as f:
                books = parse_clippings(f.read())
        except Exception as e:
            error_dialog(self, "Can't read clippings", str(e), show=True)
            return
        self.source.setText(f"My Clippings.txt: {label}")
        self.tree.clear()
        on_kindle = kindle_books(self.gui)
        # calibre's own match for books on the Kindle comes first; titles are the fallback.
        on_kindle_with_epub = [b for b in on_kindle if b[0] in self.titles]

        for (title, author), clips in sorted(books.items(), key=lambda kv: kv[0][0].casefold()):
            book = QTreeWidgetItem(self.tree, [title])
            book.setToolTip(KINDLE, f"{title} ({author})" if author else title)
            book.setFlags(book.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
            highlights = sum(c.kind == "highlight" for c in clips)
            notes = sum(1 for c in clips if c.note or c.kind == "note")
            book.setText(ANNOTATIONS, f"{highlights} • {notes}")
            for clip in clips:
                text = "✎ " + _short(clip.text) if clip.kind == "note" else _short(clip.text)
                if clip.note:
                    text += "\n      ✎ " + _short(clip.note)
                item = QTreeWidgetItem(book, [text])
                item.setToolTip(KINDLE, clip.text + (f"\n\nNote: {clip.note}" if clip.note else ""))
                item.setData(KINDLE, CLIP, clip)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(KINDLE, CHECKED)
            via_kindle = match_book(title, author, on_kindle_with_epub)
            self.set_match(book, via_kindle if via_kindle is not None else match_book(title, author, self.library))

        annotated = [(i, title, author) for i, (title, author) in enumerate(books)]
        quiet = [b for b in on_kindle if match_book(b[1], b[2], annotated) is None]
        if quiet:
            section = QTreeWidgetItem(self.tree, [f"On the Kindle, no highlights or notes ({len(quiet)})"])
            section.setData(KINDLE, SECTION, True)
            section.setFirstColumnSpanned(True)
            font = section.font(KINDLE)
            font.setBold(True)
            section.setFont(KINDLE, font)
            for book_id, title, authors in sorted(quiet, key=lambda b: b[1].casefold()):
                match = "✓ " + self.db.field_for("title", book_id) if book_id else "✗ not in calibre"
                row = QTreeWidgetItem(section, [title, match, "0 • 0"])
                row.setToolTip(KINDLE, f"{title} — {authors}")
                if not book_id:
                    row.setForeground(CALIBRE, self.palette().placeholderText())

        self.output.setPlainText(
            f"{len(books)} books with highlights or notes. Untick what you don't want and "
            "Sync selected, or Sync all. Double-click a book to pick or change its calibre match."
        )

    def set_match(self, book, book_id, manual=False):
        book.setData(KINDLE, BOOK_ID, book_id)
        book.setData(KINDLE, MANUAL, manual)  # picked by hand: trusted even if most text isn't found
        if book_id is None:
            book.setText(CALIBRE, "✗ not found — double-click to pick")
            book.setForeground(CALIBRE, self.palette().placeholderText())
            book.setCheckState(KINDLE, UNCHECKED)
        else:
            book.setText(CALIBRE, "✓ " + self.titles[book_id])
            book.setForeground(CALIBRE, self.palette().text())
            book.setCheckState(KINDLE, CHECKED)

    def pick_match(self, item, _column):
        if item.parent() is not None or item.data(KINDLE, SECTION):
            return
        choices = sorted(self.titles.values(), key=str.casefold)
        by_label = {label: book_id for book_id, label in self.titles.items()}
        current = self.titles.get(item.data(KINDLE, BOOK_ID))
        label, ok = QInputDialog.getItem(
            self, "Match book", f"Calibre book for “{item.text(KINDLE)}”:", choices,
            choices.index(current) if current in choices else 0, True,
        )
        if ok and label in by_label:
            self.set_match(item, by_label[label], manual=True)

    def sync(self, everything):
        style = STYLE
        if self.colour:
            style = style_definition_for_name(self.colour.highlight_style_name)
        self.output.clear()
        totals = {}
        for book in self.books():
            book_id = book.data(KINDLE, BOOK_ID)
            items = [book.child(j) for j in range(book.childCount())]
            if not everything:
                items = [it for it in items if it.checkState(KINDLE) == CHECKED]
            if book_id is None or not items:
                continue
            self.output.append(f"Syncing {book.text(KINDLE)}…")
            QApplication.processEvents()
            try:
                status = sync_book(
                    self.db, book_id, [it.data(KINDLE, CLIP) for it in items], style,
                    trust_match=bool(book.data(KINDLE, MANUAL)),
                )
            except Exception as e:
                self.output.append(f"✗ {book.text(KINDLE)}: {e}")
                continue
            if set(status.values()) == {CHECK_MATCH}:
                for it in items:
                    it.setText(RESULT, CHECK_MATCH)
                book.setText(RESULT, "⚠ most highlights aren't in this EPUB")
                self.output.append(
                    f"⚠ {book.text(KINDLE)}: most highlights aren't in “{self.titles[book_id]}”, so "
                    "nothing was synced. Wrong book or a different edition? Double-click the book "
                    "to pick the right one, or pick the same one to confirm it and sync anyway."
                )
                continue
            counts = {}
            for it in items:
                s = status[id(it.data(KINDLE, CLIP))]
                it.setText(RESULT, s)
                counts[s] = counts.get(s, 0) + 1
                totals[s] = totals.get(s, 0) + 1
            summary = ", ".join(f"{n} {s}" for s, n in counts.items())
            book.setText(RESULT, summary)
            self.output.append(f"✓ {book.text(KINDLE)}: {summary}")
        unmatched = sum(1 for b in self.books() if b.data(KINDLE, BOOK_ID) is None)
        summary = ", ".join(f"{n} {s}" for s, n in totals.items()) or "nothing synced"
        self.output.append(f"\nDone: {summary}. {_plural(unmatched, 'book')} without a calibre match.")
