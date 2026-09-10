"""Question normalization and stable identifier computation.

Normalization is deliberately a pure, dependency-free function: it is what
guarantees that the same question asked twice maps to the same
`question_id`, and therefore to the same Kili asset.
"""

import hashlib
import re
import unicodedata

_PUNCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+")

HASH_LENGTH = 12


def normalize_question(question: str) -> str:
    """Normalize a question for comparison and hashing.

    Steps applied, in order: accent removal, lowercasing, punctuation
    removal, whitespace collapsing and trimming.

    Args:
        question: Raw question, as asked to the RAG.

    Returns:
        The normalized question. Empty string when the question holds no
        significant character.
    """
    stripped = unicodedata.normalize("NFKD", question)
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    lowered = stripped.lower()
    without_punctuation = _PUNCTUATION.sub(" ", lowered)
    return _WHITESPACE.sub(" ", without_punctuation).strip()


def compute_question_id(question: str) -> str:
    """Compute the identifier of a reference entry.

    Args:
        question: Raw or already normalized question.

    Returns:
        An identifier shaped as `q_<12 hexadecimal characters>`.

    Raises:
        ValueError: If the question is empty once normalized.
    """
    normalized = normalize_question(question)
    if not normalized:
        raise ValueError("Question vide après normalisation.")
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
    return f"q_{digest[:HASH_LENGTH]}"


def compute_review_external_id(question_id: str, run_id: str) -> str:
    """Compute the external id of a review case in project B.

    Args:
        question_id: Question identifier (reference or candidate).
        run_id: Identifier of the production occurrence.

    Returns:
        An identifier shaped as `<question_id>__<run_id>`.
    """
    return f"{question_id}__{run_id}"


def tokenize(text: str) -> list[str]:
    """Split a text into normalized tokens.

    Args:
        text: Raw or normalized text.

    Returns:
        The tokens of the normalized text.
    """
    normalized = normalize_question(text)
    return normalized.split() if normalized else []
