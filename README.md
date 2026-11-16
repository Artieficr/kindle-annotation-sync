# Kindle Annotation Sync

<p align="center">
  <a href="https://github.com/Artieficr/kindle-annotation-sync/releases/latest"><img alt="Current Version" src="https://img.shields.io/github/v/release/Artieficr/kindle-annotation-sync?style=for-the-badge&label=Current%20Version"></a>
  <a href="https://github.com/Artieficr/kindle-annotation-sync/releases"><img alt="Total Download Count" src="https://img.shields.io/github/downloads/Artieficr/kindle-annotation-sync/total?label=Downloads&style=for-the-badge"></a>
  <a href="https://ko-fi.com/artieficr"><img alt="Ko-fi" src="https://img.shields.io/badge/Ko--fi-Support-FF5E5B?style=for-the-badge&logo=ko-fi&logoColor=white"></a>
</p>

A calibre plugin that copies the highlights and notes you make on a Kindle into calibre's
own book annotations, the ones you see in calibre's viewer and in **Browse annotations**.

DISCLAIMER: This is an independent, third-party plugin and is not affiliated with, endorsed, or sponsored by Amazon or Calibre.

## Install

1. Download `kindle-annotation-sync-vX.Y.Z.zip` from the [latest release](../../releases/latest).
   Don't unzip it.
2. In calibre: **Preferences → Plugins → Load plugin from file**, pick the zip (from Downloads
   or wherever it is), confirm, restart calibre.
3. **Preferences → Toolbars & menus → The main toolbar**: add **Sync Kindle annotations**.

To update, load the newer zip the same way.

## Use

Connect your Kindle and click **Sync Kindle annotations**. `My Clippings.txt` is read from the
Kindle automatically; without a Kindle, use **Choose file…** to pick a copy of it.

Each Kindle book with highlights or notes is listed with the calibre book it was matched to:
first the match calibre itself shows for books on the Kindle, otherwise by title (author
breaking ties). Books with no match are marked **not found** — double-click a book to pick or
change its calibre book. Expand a book to see its highlights, each with its note underneath.

With the Kindle connected, **On the Kindle, no highlights or notes** lists every other book on
it with its calibre match, so you can spot books that aren't in calibre.

- **Sync all** — everything from every matched book.
- **Sync selected** — only the ticked books and items.

Pick the highlight colour next to the buttons. After syncing, each item shows **new**,
**updated**, **already there**, **not found** or **check match**.

**Check match** is a safety stop: when a book has three or more highlights and most of them
aren't in its calibre EPUB, it's probably the wrong book or another edition, so nothing is
synced for it. Double-click the book to pick the right one — or pick the same one to confirm it,
and it syncs anyway.

Syncing again is safe: what's already in calibre is skipped, a note you add or change later on
the Kindle updates the calibre highlight, and highlights you delete in calibre stay deleted.

## How the Kindle and calibre keep annotations

Neither side really deletes anything, which is why a plain one-way sync would bring deleted
highlights back:

- **The Kindle only appends to `My Clippings.txt`.** Every highlight, note and bookmark adds an
  entry. Extending or re-making a highlight adds a new entry next to the old one, editing a note
  adds the new text as another entry, and deleting a highlight in a book changes nothing in the
  file. The highlights you see while reading are stored elsewhere on the Kindle; this file is
  only a log.
- **calibre leaves a "removed" marker.** Deleting a highlight in calibre throws away its text but
  keeps a small marker: its id and when it was deleted. calibre's viewer keeps its own copy of
  each book's annotations and merges it back when it opens the book; the marker is what stops a
  deleted highlight from coming back from that copy. Editing a highlight simply overwrites it —
  there is no history.

This plugin uses both:

- A highlight you delete in calibre stays deleted on every later sync, even though the Kindle
  still lists it. If you highlight the same passage on the Kindle **after** deleting it in
  calibre, the next sync adds it back.
- Of a highlight the Kindle replaced, only the latest version is synced.

## Notes on how things are stored

- Highlights are placed by finding their exact text in the calibre book, so a highlight never
  lands on different text.
- The highlight's text is taken from the calibre book itself, not from the Kindle's copy, so
  typos you fixed in calibre show up fixed, and spacing follows the book.
- **Short or repeated highlights can still be misplaced.** `My Clippings.txt` stores only the
  highlighted text, not the words around it. When that text appears more than once in the book
  (a single word, a repeated phrase), the plugin picks the occurrence closest to the highlight's
  Kindle location, judged from the book's other highlights. That's usually right but can pick a
  neighbouring occurrence, especially in books with few highlights. If one lands in the wrong
  spot, delete it in calibre; it stays deleted on later syncs.
- A Kindle note on a highlight becomes that highlight's note in calibre.
- A Kindle note with no highlight is attached to a word near where you wrote it. Kindle only
  records a rough location for these, so the spot is approximate — more accurate the more
  highlights the book has.
- Kindle bookmarks are not synced.

## Requirements and limits

- calibre 7 or newer.
- **Kindle:**

  | Kindle | Connects as | Status |
  | ------ | ----------- | ------ |
  | Kindles that show up as a USB drive (most models before 2024) | USB drive | Tested |
  | Kindle Scribe (firmware 5.16.3+), 2024 Kindle, Paperwhite 12th gen, Colorsoft | MTP, like a phone | **Untested** |

  For MTP Kindles the plugin asks calibre to copy `documents/My Clippings.txt` off the device.
  If that fails, or the Kindle doesn't keep that file, use **Choose file…** with a copy of it.
- The calibre book needs an **EPUB** format; the highlight text is looked up in it, so it has to
  be the same edition you read on the Kindle (books sent to the Kindle from calibre always are).
- `My Clippings.txt` only holds what the Kindle has kept; very old highlights may be gone.
- The Kindle only ever adds to `My Clippings.txt`. Deleting a highlight on the Kindle leaves its
  old entry in the file, so the plugin can't tell it was deleted and will still sync it. Delete
  it in calibre instead; it then stays deleted on later syncs.

## Support

Kindle Annotation Sync is free. If it helped you, consider tipping me on
[Ko-fi](https://ko-fi.com/artieficr). **Tips are unnecessary** but much appreciated.

## License

[MIT © Artyom Tsoy](LICENSE)
