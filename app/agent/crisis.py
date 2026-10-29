"""Crisis wording detector. Pure.

A case whose student has a concern note with this kind of wording is routed to a person and
gets no drafted message. The list is English only and untuned: it deliberately over-matches,
because a false alarm only sends the case to a mentor or counsellor, while a miss would let a
template go to someone in distress. It answers yes or no and never returns the matched words,
so nothing sensitive is copied into events, audit entries or logs.
"""

import re
import unicodedata
from collections.abc import Iterable

CRISIS = re.compile(
    r"\b("
    r"suicid\w*|self[\s-]*harm\w*|hurt(?:ing)?\s+(?:him|her|them|my|our|their)?\s*(?:self|selves)"
    r"|kill(?:ing)?\s+(?:him|her|them|my|our|their)?\s*(?:self|selves)|end(?:ing)?\s+(?:his|her|their|my)\s+life"
    r"|want(?:s|ed)?\s+to\s+die|wish(?:es|ed)?\s+(?:he|she|they|i)\s+(?:was|were)\s+dead"
    r"|take\s+(?:his|her|their|my)\s+own\s+life|overdos\w*|cutting\s+(?:him|her|them|my)\s*self"
    r"|no\s+reason\s+to\s+live|not\s+want(?:s|ed)?\s+to\s+(?:live|be\s+alive)"
    r"|abus(?:e|ed|ing|ive)|assault\w*|unsafe\s+at\s+home|in\s+danger|threat(?:en\w*)?"
    r")\b",
    re.IGNORECASE,
)
# Characters that can hide a word from a pattern: zero-width and soft hyphen.
INVISIBLE = re.compile(r"[­​-‏⁠﻿]")


def normalise(text: str) -> str:
    """Fold look-alike forms (full-width letters, ligatures) and drop invisible characters."""
    return INVISIBLE.sub("", unicodedata.normalize("NFKC", text))


def is_crisis(texts: Iterable[str]) -> bool:
    """True if any text has crisis wording."""
    return any(CRISIS.search(normalise(t)) for t in texts)
