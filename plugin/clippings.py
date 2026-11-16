"""Parse Kindle's "My Clippings.txt" into highlights (with their notes) per book.

The Kindle only ever appends to this file: a highlight that is extended, re-made or deleted
on the Kindle keeps its old entries, so older versions are dropped here.
"""

import re
from dataclasses import dataclass
from datetime import datetime

from dateutil import parser as date_parser


@dataclass
class Clip:
    kind: str  # "highlight", or "note" for a note with no highlight under it
    start: int  # Kindle location range
    end: int
    added: datetime | None
    text: str
    note: str = ""  # highlights: the latest note written on them
    note_added: datetime | None = None


_TITLE = re.compile(r"^(.*)\(([^()]*)\)\s*$")
_LOCATION = re.compile(r"(\d+)(?:\s*-\s*(\d+))?\s*$")


def parse_clippings(text):
    """{(title, author): [Clip]}; highlights redone later replace older ones, notes are attached."""
    books = {}
    for entry in text.split("=========="):
        lines = [line.strip() for line in entry.replace("﻿", "").strip().splitlines()]
        clip = _parse_entry(lines) if len(lines) >= 2 else None
        if clip:
            books.setdefault(_title_author(lines[0]), []).append(clip)
    return {book: _merge(clips) for book, clips in books.items()}


def _title_author(line):
    m = _TITLE.match(line)
    return (m[1].strip(), m[2].strip()) if m else (line, "")


def _parse_entry(lines):
    # "- Your Highlight on page 5 | Location 70-72 | Added on Monday, ..." (page part optional)
    parts = [p.strip() for p in lines[1].lstrip("- ").split("|")]
    body = "\n".join(lines[2:]).strip()
    m = _LOCATION.search(parts[-2] if len(parts) > 1 else parts[0])
    if not m or not body:  # bookmarks have no text
        return None
    start, end = m[1], m[2] or m[1]
    end = start[: len(start) - len(end)] + end  # old Kindles abbreviate "1406-07"
    kind = _kind(parts[0].lower(), is_range=m[2] is not None)
    added = _date(parts[-1]) if len(parts) > 1 else None
    return Clip(kind, int(start), int(end), added, body) if kind else None


def _kind(first_part, is_range):
    for word, kind in (("highlight", "highlight"), ("note", "note"), ("bookmark", None)):
        if word in first_part:
            return kind
    # Non-English Kindle: only highlights span a location range.
    return "highlight" if is_range else "note"


def _date(part):
    _, found, rest = part.partition("Added on ")
    try:
        return date_parser.parse(rest) if found else None
    except (ValueError, OverflowError):
        return None


def _merge(clips):
    """File order is time order. The Kindle never lets highlights overlap, so a later
    highlight overlapping an earlier one of the same passage is its new version. A note
    belongs to the highlight covering its location (the Kindle writes a note *before* its
    highlight, with the same time); a later note on the same highlight replaces an earlier one."""
    highlights, notes = [], []
    for c in clips:
        if c.kind == "note":
            notes.append(c)
            continue
        for old in [h for h in highlights if _same_passage(h, c)]:
            highlights.remove(old)
        highlights.append(c)

    loose = []
    for n in notes:
        covering = [h for h in highlights if h.start <= n.end and n.start <= h.end]
        if covering:
            h = min(covering, key=lambda h: _time_apart(h, n))
            h.note, h.note_added = n.text, n.added
            continue
        # Notes at the same location may be an edit or a second note: only exact repeats merge.
        loose = [x for x in loose if not (x.start == n.start and x.text == n.text)]
        loose.append(n)
    return highlights + loose


def _time_apart(highlight, note):
    """Seconds between a highlight and a note; unknown dates sort last."""
    if highlight.added and note.added:
        return abs((highlight.added - note.added).total_seconds())
    return float("inf")


def _same_passage(a, b):
    overlap = a.start <= b.end and b.start <= a.end
    return overlap and (a.text in b.text or b.text in a.text)
