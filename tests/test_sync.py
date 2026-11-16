import zipfile
from datetime import datetime

import pytest
from lxml import etree

from calibre_plugins.kindle_annotation_sync.clippings import Clip, parse_clippings
from calibre_plugins.kindle_annotation_sync.locate import Chapter
from calibre_plugins.kindle_annotation_sync.sync import (
    CHECK_MATCH, fetch_mtp_clippings, kindle_books, match_book, sync_book,
)

CHAPTER = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>One</title></head>
<body>
<p id="p1">It was a <i>dark</i> and<!-- c --> stormy night.</p>
<p>Second para&#173;graph here.</p>
</body></html>"""

CLIPPINGS = """﻿Dune (Herbert, Frank)
- Your Highlight on page 5 | Location 70-72 | Added on Monday, January 15, 2025 10:30:45 AM

It was a dark
==========
﻿Dune (Herbert, Frank)
- Your Highlight on page 5 | Location 70-74 | Added on Monday, January 15, 2025 10:31:00 AM

It was a dark and stormy
==========
Dune (Herbert, Frank)
- Your Note on page 5 | Location 74 | Added on Monday, January 15, 2025 10:31:10 AM

ominous
==========
Dune (Herbert, Frank)
- Your Bookmark on page 6 | Location 80 | Added on Monday, January 15, 2025 10:32:00 AM


==========
Dune (Herbert, Frank)
- Your Note on page 9 | Location 130 | Added on Monday, January 15, 2025 10:40:00 AM

loose thought
==========
Dune (Herbert, Frank)
- Highlight Loc. 1406-07 | Added on Saturday, March 1, 2011, 10:00 PM

Second paragraph
==========
Fremde (Autor, Ein)
- Ihre Markierung auf Seite 3 | Position 40-42 | Hinzugefügt am Montag, 15. Januar 2025 10:30:45

Etwas
==========
"""


def test_parse_clippings():
    books = parse_clippings(CLIPPINGS)
    assert set(books) == {("Dune", "Herbert, Frank"), ("Fremde", "Autor, Ein")}
    redone, old_style, loose = books["Dune", "Herbert, Frank"]  # first highlight replaced, bookmark dropped
    assert (redone.text, redone.note, redone.start, redone.end) == ("It was a dark and stormy", "ominous", 70, 74)
    assert redone.note_added == datetime(2025, 1, 15, 10, 31, 10)
    assert (old_style.kind, old_style.start, old_style.end) == ("highlight", 1406, 1407)
    assert (loose.kind, loose.text, loose.start) == ("note", "loose thought", 130)
    (german,) = books["Fremde", "Autor, Ein"]
    assert (german.kind, german.added) == ("highlight", None)


def test_cfis_follow_calibre_viewer_rules():
    ch = Chapter(etree.fromstring(CHAPTER.encode()))
    cases = {
        "dark": ("/2/4/2[p1]/2/1:0", "/2/4/2[p1]/2/1:4"),  # inside <i>
        "and stormy": ("/2/4/2[p1]/3:1", "/2/4/2[p1]/3:11"),  # text run continues past the comment
        "night. Second": ("/2/4/2[p1]/3:12", "/2/4/4/1:6"),  # across paragraphs
        "paragraph": ("/2/4/4/1:7", "/2/4/4/1:17"),  # soft hyphen in the book, not on the Kindle
    }
    for needle, expected in cases.items():
        assert ch.cfis(*ch.find(needle)) == expected, needle
    assert ch.find("not in the book") is None
    assert ch.text[slice(*ch.word_at(ch.find("and")[0]))] == "and"


BOOKS = [
    (1, "Dune", "Frank Herbert"),
    (2, "Dune Messiah", "Frank Herbert"),
    (3, "Foundation", "Isaac Asimov"),
    (4, "Foundation", "Some Imitator"),
    (5, "Thinking, Fast and Slow", "Daniel Kahneman"),
    (6, "Sapiens", "Yuval Noah Harari"),
]


def test_match_book():
    assert match_book("Dune", "Herbert, Frank", BOOKS) == 1
    assert match_book("Dune Messiah", "Herbert, Frank", BOOKS) == 2
    assert match_book("thinking fast and slow", "", BOOKS) == 5
    assert match_book("Sapiens: A Brief History of Humankind", "Harari, Yuval Noah", BOOKS) == 6
    assert match_book("Foundation", "Asimov, Isaac", BOOKS) == 3
    assert match_book("Foundation", "", BOOKS) is None
    assert match_book("Neuromancer", "Gibson, William", BOOKS) is None


@pytest.fixture
def epub(tmp_path):
    return make_epub(tmp_path / "book.epub", CHAPTER)


def make_epub(path, chapter):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>""")
        z.writestr("OEBPS/content.opf", """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">x</dc:identifier>
<dc:title>Dune</dc:title><dc:language>en</dc:language></metadata>
<manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/></manifest>
<spine><itemref idref="c1"/></spine></package>""")
        z.writestr("OEBPS/nav.xhtml", """<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>n</title></head>
<body><nav epub:type="toc"><ol><li><a href="c1.xhtml">Chapter One</a></li></ol></nav></body></html>""")
        z.writestr("OEBPS/c1.xhtml", chapter)
    return str(path)


class FakeDB:
    """calibre's highlight merge: same uuid -> newest timestamp wins."""

    def __init__(self, epub):
        self.epub, self.annots = epub, {}

    def format_abspath(self, book_id, fmt):
        return self.epub

    def annotations_map_for_book(self, book_id, fmt, user_type, user):
        return {"highlight": [dict(a) for a in self.annots.values()]}

    def merge_annotations_for_book(self, book_id, fmt, annots):
        for a in annots:
            old = self.annots.get(a["uuid"])
            if not old or a["timestamp"] > old["timestamp"]:
                self.annots[a["uuid"]] = a


def _clips(note="ominous", note_day=15):
    t = datetime(2025, 1, 15, 10)
    return [
        Clip("highlight", 70, 74, t, "and stormy night", note=note, note_added=datetime(2025, 1, note_day, 11)),
        Clip("note", 75, 75, t, "loose thought"),
        Clip("highlight", 90, 91, t, "not in this book"),
    ]


def test_sync_book(epub):
    db = FakeDB(epub)
    green = {"kind": "color", "type": "builtin", "which": "green"}
    clips = _clips()
    status = sync_book(db, 1, clips, green)
    assert [status[id(c)] for c in clips] == ["new", "new", "not found"]
    note, hl = sorted(db.annots.values(), key=lambda a: a["highlighted_text"])
    assert (hl["highlighted_text"], hl["notes"], hl["start_cfi"], hl["end_cfi"]) == \
        ("and stormy night", "ominous", "/2/4/2[p1]/3:1", "/2/4/2[p1]/3:17")
    assert (hl["spine_index"], hl["spine_name"], hl["toc_family_titles"], hl["style"]) == \
        (0, "OEBPS/c1.xhtml", ["Chapter One"], green)
    assert (note["highlighted_text"], note["notes"]) == ("and", "loose thought")  # nearest word

    clips = _clips()  # re-sync: nothing new
    assert set(sync_book(db, 1, clips).values()) == {"already there", "not found"}

    clips = _clips(note="ominous indeed", note_day=16)  # note edited later on the Kindle
    assert sync_book(db, 1, clips)[id(clips[0])] == "updated"
    assert db.annots[hl["uuid"]]["notes"] == "ominous indeed"
    assert db.annots[hl["uuid"]]["style"] == green  # keeps its colour

    db.annots[hl["uuid"]] = {"type": "highlight", "uuid": hl["uuid"], "removed": True,
                             "timestamp": "2026-01-01T00:00:00+00:00"}  # deleted in calibre
    clips = _clips(note="newer still", note_day=17)
    assert sync_book(db, 1, clips)[id(clips[0])] == "already there"
    assert db.annots[hl["uuid"]].get("removed")

    clips = _clips()  # highlighted again on the Kindle after the deletion: comes back
    clips[0].added = clips[0].note_added = datetime(2026, 2, 1)
    assert sync_book(db, 1, clips)[id(clips[0])] == "new"
    assert not db.annots[hl["uuid"]].get("removed")


def test_fetch_mtp_clippings_searches_storages(tmp_path):
    class Device:  # internal storage without the file, then one with it
        def __init__(self, storages):
            self.filesystem_cache = type("Cache", (), {"entries": storages})()

        def get_file_by_name(self, f, storage, *names):
            assert names == ("documents", "My Clippings.txt")
            if storage != "has-it":
                raise FileNotFoundError(storage)
            f.write(b"clippings")

    out = tmp_path / "clips.txt"
    assert fetch_mtp_clippings(Device(["empty", "has-it"]), str(out)) == str(out)
    assert out.read_bytes() == b"clippings"
    assert fetch_mtp_clippings(Device(["empty"]), str(out)) is None


def test_kindle_books_skips_clippings_file():
    from types import SimpleNamespace as NS
    books = [
        NS(title="Dune", authors=["Frank Herbert"], lpath="documents/Dune.azw3", in_library="UUID", application_id=1),
        NS(title="Mystery", authors=None, lpath="documents/Mystery.azw3", in_library=None, application_id=None),
        NS(title="My Clippings", authors=["Unknown"], lpath="documents/My Clippings.txt", in_library=None),
    ]
    gui = NS(device_manager=NS(connected_device=object()), booklists=lambda: [books, [], []])
    assert kindle_books(gui) == [(1, "Dune", "Frank Herbert"), (None, "Mystery", "")]
    assert kindle_books(NS(device_manager=NS(connected_device=None))) == []


REPEATS = CHAPTER.replace(
    """<p id="p1">It was a <i>dark</i> and<!-- c --> stormy night.</p>
<p>Second para&#173;graph here.</p>""",
    """<p>Alpha opening line. Repeat me.</p>
<p>Plenty of filler text in the middle of the book.</p>
<p>Repeat me. Omega closing line.</p>""",
)


def test_find_all():
    ch = Chapter(etree.fromstring(REPEATS.encode()))
    assert len(ch.find_all("Repeat me")) == 2 and ch.find_all("absent") == []


def test_repeated_text_placed_by_kindle_location(tmp_path):
    db = FakeDB(make_epub(tmp_path / "r.epub", REPEATS))
    t = datetime(2025, 1, 15)
    clips = [
        Clip("highlight", 10, 11, t, "Alpha opening line"),  # unique: certain anchors
        Clip("highlight", 100, 101, t, "Omega closing line"),
        Clip("highlight", 12, 12, t, "Repeat me"),  # near the start
        Clip("highlight", 98, 99, t, "Repeat me"),  # near the end
    ]
    assert set(sync_book(db, 1, clips).values()) == {"new"}
    repeats = sorted((a["start_cfi"] for a in db.annots.values() if a["highlighted_text"] == "Repeat me"))
    assert repeats == ["/2/4/2/1:20", "/2/4/6/1:0"]  # first paragraph, then third; distinct uuids


def test_mostly_missing_text_means_check_match(epub):
    t = datetime(2025, 1, 15)
    clips = [Clip("highlight", 1, 2, t, "and stormy night"),
             Clip("highlight", 3, 4, t, "nowhere in this book"),
             Clip("highlight", 5, 6, t, "nor this one")]
    db = FakeDB(epub)
    assert set(sync_book(db, 1, clips).values()) == {CHECK_MATCH}
    assert db.annots == {}  # nothing written
    status = sync_book(db, 1, clips, trust_match=True)  # the user confirmed the match
    assert [status[id(c)] for c in clips] == ["new", "not found", "not found"]


def test_note_written_before_its_highlight_is_paired():
    text = """War (P, S)
- Your Note on Page 31 | Location 474 | Added on Monday, April 6, 2015 10:04:06 PM

my note
==========
War (P, S)
- Your Highlight on Page 31 | Location 474-474 | Added on Monday, April 6, 2015 10:04:06 PM

a short highlight
==========
"""
    (clip,) = parse_clippings(text)["War", "P, S"]
    assert (clip.kind, clip.text, clip.note) == ("highlight", "a short highlight", "my note")


DASHES = CHAPTER.replace("Second para&#173;graph here.", "nothing was taken—and nothing given.")


def test_book_text_replaces_kindle_spacing_and_repairs_earlier_sync(tmp_path):
    db = FakeDB(make_epub(tmp_path / "d.epub", DASHES))
    t = datetime(2015, 4, 6, 22, 4, 6)
    green = {"kind": "color", "type": "builtin", "which": "green"}
    plain = Clip("highlight", 474, 474, t, "taken— and nothing")  # the Kindle's spacing
    assert sync_book(db, 1, [plain], green)[id(plain)] == "new"
    (a,) = db.annots.values()
    assert a["highlighted_text"] == "taken—and nothing"  # the book's own text

    # An earlier sync stored a highlight with the Kindle's text and no note, at the same time.
    a.update(highlighted_text="taken— and nothing")
    noted = Clip("highlight", 474, 474, t, "taken— and nothing", note="my note", note_added=t)
    assert sync_book(db, 1, [noted])[id(noted)] == "updated"
    (b,) = db.annots.values()
    assert (b["highlighted_text"], b["notes"], b["style"]) == ("taken—and nothing", "my note", green)
    assert b["timestamp"] > a["timestamp"]  # strictly newer, or calibre would keep the old one
    assert sync_book(db, 1, [noted])[id(noted)] == "already there"
