"""Reading of the labels and metadata returned by the Kili SDK."""

import json

from loguru import logger


def load_metadata(raw: object) -> dict:
    """Decode a `jsonMetadata` value returned by Kili.

    Args:
        raw: Value returned by the SDK (dictionary or JSON string).

    Returns:
        The decoded metadata; an empty dictionary when unreadable.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Metadata JSON illisible, ignorée.")
    return {}


def category(response: dict, job: str) -> str | None:
    """Read the category picked for a single-choice classification job.

    Args:
        response: `jsonResponse` of the label.
        job: Job name.

    Returns:
        The category code, or `None` when the job was left empty.
    """
    picked = (response.get(job) or {}).get("categories") or []
    if not picked:
        return None
    return picked[0].get("name")


def categories(response: dict, job: str) -> list[str]:
    """Read the categories ticked for a multiple-choice job.

    Args:
        response: `jsonResponse` of the label.
        job: Job name.

    Returns:
        The ticked category codes, possibly empty.
    """
    ticked = (response.get(job) or {}).get("categories") or []
    return [
        item["name"]
        for item in ticked
        if isinstance(item, dict) and item.get("name")
    ]


def transcription(response: dict, job: str) -> str | None:
    """Read the text typed for a transcription job.

    Args:
        response: `jsonResponse` of the label.
        job: Job name.

    Returns:
        The typed text, or `None` when the job is empty.
    """
    text = (response.get(job) or {}).get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return None


def human_labels(labels: list[dict]) -> list[dict]:
    """Keep the human labels of an asset, oldest first.

    Prediction and inference labels are dropped: `INFERENCE` is the type
    of the audit trail written by the scripts, which must never be read
    back as an arbitration.

    Args:
        labels: Labels returned by Kili.

    Returns:
        The human labels, sorted by ascending creation date.
    """
    humans = [
        label
        for label in labels
        if label.get("labelType") in {"DEFAULT", "REVIEW", None}
    ]
    return sorted(humans, key=lambda item: item.get("createdAt") or "")


def latest_label(labels: list[dict]) -> dict | None:
    """Keep the most recent human label of an asset.

    Args:
        labels: Labels returned by Kili.

    Returns:
        The most recent label, or `None` when the asset carries none.
    """
    candidates = human_labels(labels)
    return candidates[-1] if candidates else None


def author_of(label: dict) -> str:
    """Read the author of a label.

    Args:
        label: Label returned by Kili.

    Returns:
        The author's address, or `inconnu`.
    """
    return (label.get("author") or {}).get("email") or "inconnu"
