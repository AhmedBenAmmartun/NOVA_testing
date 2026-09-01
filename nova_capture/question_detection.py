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
    # "Was gonna head back to the lab." -- a synthetic statement with the
    # subject dropped, which streaming STT produces constantly.
    "gonna", "going", "gone", "getting", "trying",
}
#: Words a finished question never ends on. Deliberately determiners and
#: conjunctions only -- NOT prepositions, because real spoken questions do end
#: on them ("where are you getting theta from?").
_TRAILING_FRAGMENT_WORDS = {
    "a", "an", "the", "and", "or", "but", "so", "my", "your", "our",
    "their", "its", "his", "her", "this", "that", "these", "those",
}

#: Commands, not questions. "Do not do it." parsed as an inverted question on
#: 2026-08-28 and spent a model call.
_IMPERATIVE_STARTERS = {
    "do", "don't", "dont", "stop", "look", "give", "take", "let", "put",
    "go", "come", "make", "keep", "write", "open", "close", "turn", "hold",
}

#: Function words that cannot carry the subject of a real class question.
_FUNCTION_WORDS = {
    "a", "an", "the", "and", "or", "but", "so", "if", "then", "than",
    "that", "this", "these", "those", "there", "here", "what", "why",
    "how", "when", "where", "who", "whose", "which", "is", "are", "was",
    "were", "be", "been", "being", "do", "does", "did", "can", "could",
    "should", "would", "will", "shall", "may", "might", "must", "has",
    "have", "had", "i", "you", "we", "they", "he", "she", "it", "me",
    "him", "her", "them", "us", "my", "your", "our", "their", "its",
    "his", "of", "in", "on", "at", "to", "for", "with", "from", "by",
    "about", "into", "over", "just", "only", "also", "still", "really",
    "very", "much", "many", "some", "any", "all", "not", "no", "yes",
    "like", "well", "okay", "now", "one", "two", "get", "got", "going",
    "gonna", "want", "know", "think", "mean", "say", "said", "thing",
    "things", "stuff", "yeah", "sir", "guys", "them",
}

#: Rhetorical openers that are class management, not a question to answer.
_RHETORICAL_PREFIXES = (
    "any questions", "any question", "does that make sense",
    "does this make sense", "everyone good", "everybody good",
    "are we good", "any thoughts",
)

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
    if lowered in _RHETORICAL_FILLER:
        return True
    # "Any questions on that one?" is the same move as "Any questions?".
    return any(lowered.startswith(prefix) for prefix in _RHETORICAL_PREFIXES)


def _is_imperative(words: list[str], *, ends_with_question_mark: bool) -> bool:
    """True for commands. "Do not do it." is not a question."""
    if not words:
        return False
    first = words[0]
    if first not in _IMPERATIVE_STARTERS:
        return False
    if len(words) > 1 and words[1] in {"not", "n't"}:
        return True
    # "Do you know X?" is a question; a bare command is not.
    return not ends_with_question_mark and (
        len(words) < 2 or words[1] not in _PRONOUN_SUBJECTS
    )


#: Two or more consecutive capitals: UML, SQL, VR, API. No word boundary
#: needed -- "Mom" and "What" carry only one capital and never match.
_ACRONYM_RE = re.compile("[A-Z][A-Z]+")


def _has_substantive_subject(words: list[str], original: str) -> bool:
    """Reject questions made only of pointing words.

    Synthetic fragments such as "What is this?", "What that is?",
    "Is there now?" and "What are the?" name nothing a model could answer
    about. A substantive technical question such as "What is cohesion." does.

    Acronyms are checked against the original casing, because the subject of a
    real class question is often three letters: "What is UML?", "What is SQL?".
    """
    if _ACRONYM_RE.search(original or ""):
        return True
    return any(len(word) >= 4 and word not in _FUNCTION_WORDS for word in words)


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

    ends_with_question_mark = cleaned.rstrip().endswith("?")

    # An unfinished fragment: "What are the?"
    if words[-1] in _TRAILING_FRAGMENT_WORDS:
        return False

    if _is_imperative(words, ends_with_question_mark=ends_with_question_mark):
        return False

    if not _has_substantive_subject(words, stripped):
        return False

    # "The chart, sir?" -- a synthetic short fragment opening on a determiner,
    # with no interrogative word anywhere. A trailing "?" alone is not enough.
    if (
        words[0] in {"a", "an", "the"}
        and len(words) < 5
        and not (set(words) & (_STRONG_WH_STARTERS | _AUX_STARTERS))
    ):
        return False

    return looks_like_question(cleaned)
