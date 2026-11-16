"""Find Kindle text in a book chapter and express positions as calibre viewer CFIs.

The CFI rules mirror the encoder in calibre's viewer (read_book/cfi.pyj): steps start at
the document, so <html> is /2; elements take even indices and the text between them odd
ones; a text offset counts across neighbouring text nodes, comments adding nothing.
"""

import re
from collections import Counter

from lxml import etree

_INVISIBLE = "\xad​‌‍﻿"
_HIDDEN_TAGS = {"script", "style"}
_CFI_ESCAPE = re.compile(r"([\[\],^();~@!])")


def squash(text):
    """Text minus whitespace and invisible characters: matching then ignores line breaks,
    paragraph joins and soft hyphens."""
    return "".join(ch for ch in text if not (ch.isspace() or ch in _INVISIBLE))


class Chapter:
    def __init__(self, root):
        self._chars, self._raw, self._raw_len = [], [], 0
        self.pos = []  # per kept character: (parent element, odd CFI step, offset in text run)
        self.raw_at = []  # per kept character: its index in the chapter's raw visible text
        body = next(root.iterchildren("{*}body"), root)
        self._walk(body)
        self.text = "".join(self._chars)
        self._raw = "".join(self._raw)
        counts = Counter(root.xpath("//@id"))
        self._unique_ids = {i for i, n in counts.items() if n == 1}

    def _walk(self, el):
        hidden = etree.QName(el).localname in _HIDDEN_TAGS
        elements, offset = 0, self._add(el.text, el, 1, 0, hidden)
        for child in el:
            if isinstance(child.tag, str):  # element; comments and PIs keep the text run going
                elements += 1
                self._walk(child)
                offset = 0
            offset = self._add(child.tail, el, 2 * elements + 1, offset, hidden)

    def _add(self, text, parent, step, offset, hidden):
        if not text:
            return offset
        if not hidden:
            for i, ch in enumerate(text):
                if not (ch.isspace() or ch in _INVISIBLE):
                    self._chars.append(ch)
                    self.pos.append((parent, step, offset + i))
                    self.raw_at.append(self._raw_len + i)
            self._raw.append(text)
            self._raw_len += len(text)
        return offset + len(text)

    def find_all(self, needle):
        """Index spans (start, end) of every occurrence of needle in self.text."""
        needle, spans = squash(needle), []
        i = self.text.find(needle) if needle else -1
        while i >= 0:
            spans.append((i, i + len(needle)))
            i = self.text.find(needle, i + 1)
        return spans

    def find(self, needle):
        """Index span of needle's first occurrence, or None."""
        return next(iter(self.find_all(needle)), None)

    def text_of(self, start, end):
        """The book's own text for characters [start, end), whitespace tidied. The Kindle's copy
        can differ, e.g. when a typo was fixed in calibre after the book was sent to the Kindle."""
        raw = self._raw[self.raw_at[start]:self.raw_at[end - 1] + 1]
        return " ".join("".join(ch for ch in raw if ch not in _INVISIBLE).split())

    def word_at(self, i):
        """Index span of the word containing character i."""
        def joined(j):  # chars j and j+1 touch in the same text run
            (p1, s1, o1), (p2, s2, o2) = self.pos[j], self.pos[j + 1]
            return p1 is p2 and s1 == s2 and o2 == o1 + 1

        a, b = i, i
        while a > 0 and joined(a - 1):
            a -= 1
        while b + 1 < len(self.pos) and joined(b):
            b += 1
        return a, b + 1

    def cfis(self, start, end):
        """CFIs bounding characters [start, end)."""
        return self._cfi(*self.pos[start]), self._cfi(*self.pos[end - 1], extra=1)

    def _cfi(self, parent, step, offset, extra=0):
        steps = [f"/{step}:{offset + extra}"]
        el = parent
        while el is not None:
            index = 2 * (1 + sum(1 for _ in el.itersiblings(etree.Element, preceding=True)))
            eid = el.get("id")
            spec = "[" + _CFI_ESCAPE.sub(r"^\1", eid) + "]" if eid in self._unique_ids else ""
            steps.append(f"/{index}{spec}")
            el = el.getparent()
        return "".join(reversed(steps))
