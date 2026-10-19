"""Text normalisation applied to every extracted page."""

from __future__ import annotations

import re
import unicodedata

# Characters that PDFs commonly emit and that hurt tokenisation/search.
_REPLACEMENTS = {
    "­": "",  # soft hyphen
    "​": "",  # zero-width space
    "‌": "",
    "‍": "",
    "﻿": "",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
    "•": "-",  # bullet
    "": "-",  # private-use bullet emitted by Word exports
}
_REPLACE_RE = re.compile("|".join(map(re.escape, _REPLACEMENTS)))
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HYPHEN_BREAK_RE = re.compile(r"(\w)-\n(\w)")
_INLINE_WS_RE = re.compile(r"[ \t\f\v ]+")
_MANY_NEWLINES_RE = re.compile(r"\n{3,}")
# A single line break between a line that does not end a sentence/clause and a line
# that starts in lower case is a soft wrap from PDF layout, not a structural break.
_SOFT_WRAP_RE = re.compile(r"(?<=[A-Za-z0-9,)\]])\n(?=[a-z(])")


def clean_text(text: str) -> str:
    """Normalise Unicode, strip control characters, re-join hyphenated line breaks,
    reflow soft line wraps and collapse whitespace while keeping paragraph breaks
    (blank lines) and lines that start with capitals, digits or bullets."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = _REPLACE_RE.sub(lambda m: _REPLACEMENTS[m.group(0)], text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_RE.sub("", text)
    text = _HYPHEN_BREAK_RE.sub(r"\1\2", text)
    text = _INLINE_WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _SOFT_WRAP_RE.sub(" ", text)
    text = _MANY_NEWLINES_RE.sub("\n\n", text)
    return text.strip()
