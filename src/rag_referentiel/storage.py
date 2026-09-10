"""Asset writing, with a fallback when the metadata is too large.

The maximum size of a `json_metadata` is not documented by Kili. Every
write therefore goes through this layer: when the payload exceeds the
configured threshold, or when the server refuses it because of its size,
we fall back on a documented shrink — texts stay readable in the
`json_content`, the metadata keeps only what is needed to find and drive
the entry.

Accepted consequence: a shrunk entry no longer carries its answer texts
in metadata. `referentiel.py` reports it and refuses to complete such an
entry rather than deduplicating blindly.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from loguru import logger

#: Clés dont le contenu peut atteindre une taille arbitraire.
LONG_TEXT_KEYS = ("candidate_answer",)

_SIZE_ERROR_PATTERNS = (
    "too large",
    "too long",
    "payload",
    "entity too large",
    "exceeds",
    "size limit",
    "413",
)

T = TypeVar("T")


@dataclass
class AssetPayload:
    """Metadata and content pair, ready to be sent to Kili."""

    json_metadata: dict
    json_content: list[dict]
    fallback: bool = False


def metadata_size(metadata: dict) -> int:
    """Measure the serialized size of a metadata dictionary.

    Args:
        metadata: Metadata to measure.

    Returns:
        The number of bytes of its JSON serialization.
    """
    return len(json.dumps(metadata, ensure_ascii=False).encode("utf-8"))


def shrink_metadata(metadata: dict) -> dict:
    """Reduce a metadata dictionary to its identifiers and driving fields.

    Long texts are dropped: the candidate answer, and the text of every
    validated wording. The question itself is kept — it is the functional
    key of the entry, and its size is bounded.

    Args:
        metadata: Complete metadata.

    Returns:
        A new, shrunk metadata dictionary, flagged with `repli_texte`.
    """
    shrunk = {
        key: value
        for key, value in metadata.items()
        if key not in LONG_TEXT_KEYS
    }
    answers = shrunk.get("answers")
    if isinstance(answers, list):
        shrunk["answers"] = [
            {key: value for key, value in answer.items() if key != "text"}
            for answer in answers
            if isinstance(answer, dict)
        ]
    shrunk["repli_texte"] = True
    return shrunk


def prepare_payload(
    metadata: dict, json_content: list[dict], max_size: int
) -> AssetPayload:
    """Prepare an asset payload, shrinking the metadata when needed.

    Args:
        metadata: Complete metadata.
        json_content: Rich text rendering of the asset.
        max_size: Maximum tolerated metadata size, in bytes.

    Returns:
        The payload to send to Kili.
    """
    if metadata_size(metadata) <= max_size:
        return AssetPayload(metadata, json_content)
    logger.warning(
        "Metadata de {} octets au-dessus du seuil de {} : repli sur une "
        "metadata allégée, les textes restent dans le rendu.",
        metadata_size(metadata),
        max_size,
    )
    return AssetPayload(
        shrink_metadata(metadata), json_content, fallback=True
    )


def is_size_error(error: Exception) -> bool:
    """Guess whether a write error is caused by the payload size.

    Args:
        error: Exception raised by the Kili SDK.

    Returns:
        `True` when the message hints at a size overflow.
    """
    message = str(error).lower()
    return any(pattern in message for pattern in _SIZE_ERROR_PATTERNS)


def write_with_fallback(
    write: Callable[[AssetPayload], T],
    metadata: dict,
    json_content: list[dict],
    max_size: int,
) -> T:
    """Write an asset, shrinking the metadata if the server refuses it.

    Args:
        write: Function performing the Kili write for a given payload.
        metadata: Complete metadata.
        json_content: Rich text rendering of the asset.
        max_size: Maximum tolerated metadata size, in bytes.

    Returns:
        The result of the write function.

    Raises:
        Exception: Any write error that is not a size problem is
            propagated as is.
    """
    payload = prepare_payload(metadata, json_content, max_size)
    try:
        return write(payload)
    except Exception as error:
        if payload.fallback or not is_size_error(error):
            raise
        logger.warning(
            "Écriture refusée pour cause de volume ({}) : nouvelle "
            "tentative avec une metadata allégée.",
            error,
        )
        return write(
            AssetPayload(
                shrink_metadata(metadata), json_content, fallback=True
            )
        )
