"""Match Kindle books to library EPUBs and merge their clippings into calibre annotations."""

import hashlib
import os
import re
from bisect import bisect_right
from collections import Counter
from datetime import datetime, timedelta, timezone
from itertools import accumulate

from calibre_plugins.kindle_annotation_sync.locate import Chapter, squash

# Used when the Kindle date can't be parsed: older than anything, so edits made in calibre win.
UNKNOWN_TIME = datetime(2000, 1, 1, tzinfo=timezone.utc)
CHECK_MATCH = "check match"
STYLE = {"kind": "color", "type": "builtin", "which": "yellow"}


def find_clippings_file(gui):
    """Path to My Clippings.txt on the Kindle calibre has connected, else None."""
    device = getattr(gui.device_manager, "connected_device", None)
    prefix = getattr(device, "_main_prefix", None)
    path = prefix and os.path.join(prefix, "documents", "My Clippings.txt")
    return path if path and os.path.isfile(path) else None


def mtp_kindle(gui):
    """The connected Kindle if it talks MTP (Scribe since 5.16.3, 2024 models), else None."""
    device = getattr(gui.device_manager, "connected_device", None)
    return device if getattr(device, "is_kindle", False) and hasattr(device, "get_file_by_name") else None


def fetch_mtp_clippings(device, out_path):
    """Copy documents/My Clippings.txt off an MTP Kindle; runs on calibre's device thread.
    Returns out_path, or None if no storage has the file."""
    # ponytail: untested on a real MTP Kindle; the file may not exist on these models
    for storage in device.filesystem_cache.entries:
        try:
            with open(out_path, "wb") as f:
                device.get_file_by_name(f, storage, "documents", "My Clippings.txt")
            return out_path
        except Exception:
            continue
    return None


def kindle_books(gui):
    """[(library book_id or None, title, authors)] for every book on the connected Kindle, using
    the match calibre itself made for its device view. Empty when no Kindle is connected."""
    if getattr(gui.device_manager, "connected_device", None) is None:
        return []
    return [
        (getattr(b, "application_id", None) if getattr(b, "in_library", None) else None,
         b.title, " & ".join(b.authors or ()))
        for booklist in gui.booklists()
        for b in booklist
        if os.path.basename(getattr(b, "lpath", "") or "") != "My Clippings.txt"  # calibre lists it as a book
    ]


def library_epubs(db):
    """[(book_id, title, authors)] for every library book with an EPUB."""
    return [
        (i, db.field_for("title", i), " & ".join(db.field_for("authors", i)))
        for i in db.all_book_ids()
        if "EPUB" in (db.formats(i) or ())
    ]


def _norm(s):
    return re.sub(r"[\W_]+", " ", s).casefold().strip()


def match_book(title, author, books):
    """book_id of the library book for a Kindle title/author; None if none or ambiguous."""
    t = _norm(title)
    hits = [b for b in books if _norm(b[1]) == t]
    if not hits:  # one side often carries a subtitle the other dropped
        hits = [b for b in books if (n := _norm(b[1])) and (t.startswith(n + " ") or n.startswith(t + " "))]
    if len(hits) > 1 and author:
        # Kindle writes "Last, First", calibre "First Last": compare as word sets.
        words = set(_norm(author).split())
        hits = [b for b in hits if words & set(_norm(b[2]).split())]
    return hits[0][0] if len(hits) == 1 else None


def annotation_uuid(clip, with_location=False):
    """Stable id of the calibre annotation made from a clip. with_location: the same text is
    highlighted in more than one place in the book, so the text alone isn't unique."""
    if clip.kind == "highlight":
        key = f"hl|{clip.start}|" if with_location else "hl|"
    else:  # two different notes can share a Kindle location
        key = f"note|{clip.start}|"
    return hashlib.sha1((key + squash(clip.text)).encode()).hexdigest()[:22]


def last_activity(clip):
    """When the Kindle last touched the clip (highlight or its note), in UTC; None if unknown."""
    stamps = [t for t in (clip.added, clip.note_added) if t]
    return max(stamps).astimezone(timezone.utc) if stamps else None


def _time(iso):
    """calibre writes "...Z" and "...+00:00" timestamps; compare them as datetimes, not text."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _existing(db, book_id):
    annots = db.annotations_map_for_book(book_id, "EPUB", user_type="local", user="viewer")
    return {a["uuid"]: a for a in annots.get("highlight", [])}


def sync_book(db, book_id, clips, style=STYLE, trust_match=False):
    """Merge clips into the book's annotations. Returns {id(clip): status}, status being
    "new", "updated", "already there", "not found" or CHECK_MATCH.

    Safety: with 3+ highlights of which most aren't in the EPUB, the book is probably the wrong
    one (or another edition), so nothing is written and every clip gets CHECK_MATCH, unless
    trust_match (the user picked this book by hand).

    Annotation uuids derive from the Kindle passage, so re-syncing finds its earlier work:
    unchanged ones are skipped, a highlight deleted in calibre stays deleted unless it was
    highlighted again on the Kindle afterwards, and a note changed on the Kindle replaces the
    old one unless it was edited in calibre since.
    """
    from calibre.ebooks.oeb.polish.container import get_container
    from calibre.ptempfile import TemporaryDirectory

    with TemporaryDirectory() as tdir:
        container = get_container(db.format_abspath(book_id, "EPUB"), tdir=tdir, tweak_mode=True)
        found, missed = build_annotations(container, clips, style)

    highlights = sum(c.kind == "highlight" for c in clips)
    found_highlights = sum(c.kind == "highlight" for c, _ in found)
    if not trust_match and highlights >= 3 and 2 * found_highlights < highlights:
        return {id(c): CHECK_MATCH for c in clips}

    existing = _existing(db, book_id)
    status = {id(c): "not found" for c in missed}
    send = []
    for clip, a in found:
        old = existing.get(a["uuid"])
        if old is None or (old.get("removed") and _time(a["timestamp"]) > _time(old["timestamp"])):
            status[id(clip)] = "new"
            send.append(a)
            continue
        update = None if old.get("removed") else _update(old, a)
        status[id(clip)] = "already there" if update is None else "updated"
        if update is not None:
            send.append(update)
    if send:
        db.merge_annotations_for_book(book_id, "EPUB", send)
    return status


def _update(old, a):
    """The existing annotation with the Kindle's newer note and/or the book's own text, or
    None if nothing changed. Colour and position stay as they are in calibre. A note edited in
    calibre after the Kindle wrote its note is kept; an equal time is this plugin's own earlier
    sync, so the Kindle note goes in."""
    kindle, calibre = _time(a["timestamp"]), _time(old["timestamp"])
    take_note = bool(a.get("notes")) and a["notes"] != old.get("notes") and kindle >= calibre
    take_text = a["highlighted_text"] != old.get("highlighted_text")
    if not (take_note or take_text):
        return None
    new = dict(old, highlighted_text=a["highlighted_text"])
    if take_note:
        new["notes"] = a["notes"]
    # calibre keeps the newest timestamp per uuid, so the update must be strictly newer.
    when = max(kindle, calibre + timedelta(milliseconds=1))
    new["timestamp"] = when.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return new


def build_annotations(container, clips, style=STYLE):
    """[(clip, calibre viewer highlight dict)] for clips found in the book, and the clips that weren't.

    My Clippings.txt holds only the highlighted text, no surrounding words, so text found more
    than once is told apart by its Kindle location: highlights whose text occurs exactly once
    are certain, and give the scale for placing the rest.
    """
    spine = [name for name, _ in container.spine_names]
    chapters = [Chapter(container.parsed(name)) for name in spine]
    toc = _toc_titles(container, spine)
    base = list(accumulate((len(ch.text) for ch in chapters), initial=0))  # chapter -> book offset
    out, missed = [], []

    def annot(clip, s, span, text, note, uuid):
        start_cfi, end_cfi = chapters[s].cfis(*span)
        when = last_activity(clip) or UNKNOWN_TIME
        a = {
            "type": "highlight",
            "uuid": uuid,
            "highlighted_text": text,
            "start_cfi": start_cfi,
            "end_cfi": end_cfi,
            "spine_index": s,
            "spine_name": spine[s],
            "style": style,
            "timestamp": when.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "toc_family_titles": toc(s),
        }
        if note:
            a["notes"] = note
        out.append((clip, a))

    highlights = [c for c in clips if c.kind == "highlight"]
    hits = {
        id(c): [(s, span) for s, ch in enumerate(chapters) for span in ch.find_all(c.text)]
        for c in highlights
    }
    unique = [(c.start, base[s] + span[0]) for c in highlights if len(hits[id(c)]) == 1 for s, span in hits[id(c)]]
    repeated_texts = Counter(squash(c.text) for c in highlights)
    placed = []
    for c in highlights:
        candidates = hits[id(c)]
        if not candidates:
            missed.append(c)
            continue
        expected = _estimate(unique, c.start)
        # ponytail: without any unique highlight in the book, the first occurrence wins
        s, span = candidates[0] if expected is None else min(
            candidates, key=lambda hit: abs(base[hit[0]] + hit[1][0] - expected)
        )
        placed.append((c.start, base[s] + span[0]))
        uuid = annotation_uuid(c, with_location=repeated_texts[squash(c.text)] > 1)
        annot(c, s, span, chapters[s].text_of(*span), c.note, uuid)

    for c in clips:
        if c.kind != "note":
            continue
        # ponytail: approximate, accuracy grows with highlight density; Kindle locations can't map exactly
        g = _estimate(placed, c.start)
        if g is None:
            missed.append(c)
            continue
        s = min(bisect_right(base, g) - 1, len(chapters) - 1)
        while s > 0 and not chapters[s].text:  # landed on an empty chapter: step back
            s -= 1
        span = chapters[s].word_at(min(g - base[s], len(chapters[s].text) - 1))
        annot(c, s, span, chapters[s].text_of(*span), c.text, annotation_uuid(c))
    return out, missed


def _estimate(points, location):
    """Book offset expected for a Kindle location, interpolated between the known
    (location, offset) points around it; None without points."""
    if not points:
        return None
    points = sorted(points)
    before = [p for p in points if p[0] <= location][-1:]
    after = [p for p in points if p[0] > location][:1]
    (l0, g0), (l1, g1) = (before or after)[0], (after or before)[0]
    return g0 if l1 == l0 else round(g0 + (g1 - g0) * (location - l0) / (l1 - l0))


def _toc_titles(container, spine):
    """chapter index -> TOC breadcrumb titles, the way the viewer groups highlights."""
    from calibre.ebooks.oeb.polish.toc import get_toc

    index = {name: i for i, name in enumerate(spine)}
    nodes = [
        (index[n.dest], k, n)
        for k, n in enumerate(get_toc(container, verify_destinations=False).iterdescendants())
        if n.dest in index
    ]

    def titles(s):
        candidates = [t for t in nodes if t[0] <= s]
        node, out = (max(candidates)[2] if candidates else None), []
        while node is not None and node.title:
            out.append(node.title)
            node = node.parent
        return out[::-1]

    return titles
