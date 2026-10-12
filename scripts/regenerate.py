"""Draft the answers judged non compliant, for business proofreading.

Reads the project B cases in `A_REGENERER` (set by `promote.py`), has a
vision model draft each answer from the ground truth pages of the local
PDF files, and imports the draft as a proofreading asset. Idempotent:
running it again creates no duplicate.
"""

import argparse
from datetime import UTC, datetime
from pathlib import Path

from _commun import settings, write_json
from loguru import logger

from rag_referentiel.client import create_client
from rag_referentiel.config import Settings
from rag_referentiel.documents import DocumentStore
from rag_referentiel.regeneration import (
    AnswerDrafter,
    ClaudeDrafter,
    OfflineDrafter,
    regenerate_batch,
)


def build_drafter(config: Settings, offline: bool) -> AnswerDrafter:
    """Pick the drafter according to the mode.

    Args:
        config: Runtime settings.
        offline: When true, use the placeholder drafter.

    Returns:
        The drafter to use.

    Raises:
        RuntimeError: If the Anthropic key is missing in online mode.
    """
    if offline:
        return OfflineDrafter()
    if not config.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY absente : utiliser --hors-ligne ou "
            "renseigner la clé."
        )
    import anthropic

    style = None
    if config.regeneration_style_file:
        style = config.regeneration_style_file.read_text(encoding="utf-8")
    return ClaudeDrafter(
        client=anthropic.Anthropic(api_key=config.anthropic_api_key),
        model=config.regeneration_model,
        effort=config.regeneration_effort,
        style=style,
        fallbacks=config.regeneration_fallbacks,
    )


def main() -> None:
    """Entry point of the regeneration script."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--projet-referentiel",
        dest="reference_project",
        required=True,
        help="Projet A.",
    )
    parser.add_argument(
        "--projet-revue",
        dest="review_project",
        required=True,
        help="Projet B.",
    )
    parser.add_argument(
        "--documents",
        dest="documents_dir",
        type=Path,
        default=None,
        help="Répertoire des PDF sources (sinon DOCUMENTS_DIR).",
    )
    parser.add_argument(
        "--hors-ligne",
        dest="offline",
        action="store_true",
        help="Brouillon factice, sans appel au modèle.",
    )
    parser.add_argument(
        "--rapport",
        dest="report_path",
        type=Path,
        default=None,
        help="Fichier du rapport JSON.",
    )
    arguments = parser.parse_args()

    config = settings()
    documents_dir = arguments.documents_dir or config.documents_dir
    if documents_dir is None:
        parser.error("renseigner --documents ou DOCUMENTS_DIR.")
    store = DocumentStore(documents_dir)
    logger.info(
        "{} documents indexés dans {}.",
        len(store.page_counts()),
        documents_dir,
    )
    drafter = build_drafter(config, arguments.offline)
    kili = create_client(config)
    report = regenerate_batch(
        kili,
        arguments.reference_project,
        arguments.review_project,
        store,
        drafter,
        config,
    )
    logger.info(
        "{} cas à régénérer · {} brouillons · {} sans brouillon · "
        "{} à retenter.",
        report.cases_read,
        report.drafts_created,
        report.failures,
        report.retries_pending,
    )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    write_json(
        arguments.report_path or Path(f"reports/regeneration_{stamp}.json"),
        {
            "horodatage": stamp,
            "hors_ligne": arguments.offline,
            **report.model_dump(),
        },
    )


if __name__ == "__main__":
    main()
