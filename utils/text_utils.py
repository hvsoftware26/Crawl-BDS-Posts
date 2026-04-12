# Text utilities
import re
from typing import Optional

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\u2600-\u26FF"
    "\u2700-\u27BF"
    "\u200d"
    "\ufe0f"
    "\u20e3"
    "]",
    flags=re.UNICODE,
)


def remove_icons_from_text(text: Optional[str]):
    """
    Remove emoji and icon-like unicode symbols while keeping normal text.
    """
    if text is None:
        return None

    if not text:
        return text

    cleaned_text = EMOJI_PATTERN.sub("", text)
    cleaned_text = re.sub(r"[^\S\r\n]{2,}", " ", cleaned_text)
    cleaned_text = re.sub(r"[ \t]+\n", "\n", cleaned_text)
    cleaned_text = re.sub(r"\n[ \t]+", "\n", cleaned_text)
    return cleaned_text.strip()
