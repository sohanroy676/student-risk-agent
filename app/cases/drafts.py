"""Draft messages for a case: the templates and the rules any message must meet. Pure.

A draft is what a mentor may approve to send to a student. It never mentions scores, bands,
risk or predictions, and it carries no reasons: those are for the mentor only. The same check
applies to a mentor's own wording, so approval cannot send a banned term by editing it in.
"""

import re

MAX_LENGTH = 1000

# Words a student-facing message may not contain (matched whole-word, any case).
BANNED = re.compile(
    r"\b(risk\w*|scor(?:e|es|ed|ing)|bands?|probabilit\w*|predict\w*|flag\w*|amber|dropout"
    r"|red\s+(?:band|zone|flag))\b",
    re.IGNORECASE,
)
CONTROL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")  # everything but newline

FIRST_CONTACT = (
    "Hi, this is your mentor checking in. I wanted to see how your studies are going and "
    "whether there is anything I can help with. If you would like to talk, reply to this "
    "message or drop by and we can find a time that suits you."
)
FOLLOW_UP = (
    "Hi, this is your mentor again. I wanted to follow up on my last message and see how "
    "things have been going since. If there is anything that would make the coming weeks "
    "easier, I am glad to talk it through."
)


class InvalidMessage(ValueError):
    """The message cannot be saved as a draft; the text says why."""


def template_message(cycle: int) -> str:
    """The first-contact text for cycle 1, the follow-up wording for later cycles."""
    return FIRST_CONTACT if cycle <= 1 else FOLLOW_UP


def check_message(message: str) -> str:
    """The trimmed message, or `InvalidMessage` if it is empty, too long or has a banned term."""
    clean = message.strip()
    if not clean:
        raise InvalidMessage("the message is empty")
    if len(clean) > MAX_LENGTH:
        raise InvalidMessage(f"the message is longer than {MAX_LENGTH} characters")
    if CONTROL.search(clean):
        raise InvalidMessage("the message contains control characters")
    found = BANNED.search(clean)
    if found:
        raise InvalidMessage(f"the word '{found.group(0)}' may not appear in a message")
    return clean
