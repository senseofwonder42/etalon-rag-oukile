"""Helpers shared by the command line scripts."""

import json
from pathlib import Path

from loguru import logger

from rag_referentiel.config import Settings, load_settings


def read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file, skipping unreadable lines.

    Args:
        path: File to read.

    Returns:
        The parsed records.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {path}")
    records = []
    for number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as error:
            logger.warning(
                "Ligne {} de {} illisible, ignorée : {}", number, path, error
            )
    return records


def write_json(path: Path, content: dict) -> None:
    """Write a readable JSON report.

    Args:
        path: Destination file.
        content: Content of the report.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(content, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("Rapport écrit : {}", path)


def settings() -> Settings:
    """Load the runtime settings.

    Returns:
        The validated settings.
    """
    return load_settings()
