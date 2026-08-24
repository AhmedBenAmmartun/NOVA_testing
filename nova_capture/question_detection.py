from __future__ import annotations

import re


_STRONG_WH_STARTERS = {
    "what", "why", "how", "when", "where", "who", "whose", "which",
}
_AUX_STARTERS = {
    "is", "are", "was", "were", "do", "does", "did", "can", "could",
    "should", "would", "will", "may", "might", "has", "have", "had",
}
_QUESTION_PREFIXES = (
    "am i ", "are we ", "is there ", "are there ",
    "wait does ", "wait is ", "does that mean ", "what about ",
    "how come ", "what happens if ", "what if ", "can you explain ",
    "can you repeat ", "can you go over ", "could you explain ",
    "would this ", "should we ", "i'm confused about ",
    "im confused about ", "i don't understand ", "i dont understand ",
)
_NON_SUBSTANTIVE_QUESTION = {
    "hello", "hi", "hey", "hello there", "hi there", "hey there",
    "what", "why", "how", "huh", "ready", "okay", "ok", "right",
    "yes", "no", "yeah", "yep", "nope", "today",
}
_RHETORICAL_FILLER = {
    "any questions", "any questions so far", "questions", "everyone good",
    "everybody good", "does that make sense", "make sense", "you follow",
    "are we good", "we good", "right", "okay", "ok",
}
_SUBJECT_LIKE = {
    "i", "you", "we", "they", "he", "she", "it", "there", "this",
    "that", "these", "those", "a", "an", "the", "my", "your", "our",
}
_PRONOUN_SUBJECTS = {
    "i", "you", "we", "they", "he", "she", "it", "there", "this",
    "that", "these", "those",
}
_AUX_FRAGMENT_SECOND_WORDS = {
    "just", "only", "also", "already", "still", "really", "actually",
    "basically", "probably", "maybe", "simply", "kind", "sort",
}
_WORD_RE = re.compile(r"[a-z']+")
_LEADING_DISCOURSE_RE = re.compile(
    r"^(?:(?:okay|ok|alright|all right|well|so|like|i mean|you know|wait|um|uh|k)\b[\s,.:;-]*)+",
    re.IGNORECASE,
)


def normalize_question_text(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _strip_discourse_leadin(text: str) -> str:
    cleaned = normalize_question_text(text)
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = _LEADING_DISCOURSE_RE.sub("", cleaned).strip()
    return cleaned


def _auxiliary_inversion_looks_valid(words: list[str]) -> bool:
    if len(words) < 3:
        return False

    first, second = words[0], words[1]
    if second in _AUX_FRAGMENT_SECOND_WORDS:
        return False

    # "Have an Indian professor." is a statement/fragment, not an inverted
    # question. Have/has/had need an explicit pronoun-like subject.
    if first in {"have", "has", "had"}:
        return second in _PRONOUN_SUBJECTS

    # For the other auxiliaries, pronouns/articles/determiners are strong
    # enough evidence when punctuation is missing from streaming STT.
    if second in _SUBJECT_LIKE:
        return True

    # Technical nouns can also be subjects: "Can aggregation exist alone".
    # Reject obvious adverb/fragment starts but otherwise allow a real token.
    return len(second) >= 3


def looks_like_question(text: str) -> bool:
    cleaned = normalize_question_text(text)
    if not cleaned:
        return False

    stripped = _strip_discourse_leadin(cleaned)
    if not stripped:
        return False

    lowered = stripped.casefold().strip(" .!…")
    if not lowered:
        return False

    words = _WORD_RE.findall(lowered)
    if not words:
        return False

    # A literal question mark remains the strongest signal from the STT.
    if cleaned.rstrip().endswith("?"):
        return True

    if any(lowered.startswith(prefix) for prefix in _QUESTION_PREFIXES):
        return True

    first = words[0]
    if first in _STRONG_WH_STARTERS:
        return len(words) >= 3

    if first in _AUX_STARTERS:
        return _auxiliary_inversion_looks_valid(words)

    return False


def is_rhetorical_classroom_filler(text: str) -> bool:
    lowered = _strip_discourse_leadin(text).casefold().rstrip("?.! ")
    return lowered in _RHETORICAL_FILLER


def should_answer_question(text: str) -> bool:
    cleaned = normalize_question_text(text)
    stripped = _strip_discourse_leadin(cleaned)
    lowered = stripped.casefold().rstrip("?.! ")

    if lowered in _NON_SUBSTANTIVE_QUESTION:
        return False
    if is_rhetorical_classroom_filler(cleaned):
        return False

    words = _WORD_RE.findall(lowered)
    if len(words) < 3:
        return False

    return looks_like_question(cleaned)
