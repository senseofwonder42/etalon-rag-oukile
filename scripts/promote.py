"""From review to repository: apply the business arbitrations.

The script is idempotent: running it again duplicates no wording and does
not bump `version` without a state change.
"""

import argparse
from datetime import UTC, datetime
from pathlib import Path

from _commun import settings, write_json
from loguru import logger

from rag_referentiel.client import create_client
from rag_referentiel.documents import DocumentStore
from rag_referentiel.referentiel import promote_batch


def main() -> None:
    """Entry point of the promotion script."""
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
        help=(
            "Répertoire des PDF sources (sinon DOCUMENTS_DIR) : active la "
            "vérification d'existence des sources corrigées."
        ),
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
    page_counts = None
    if documents_dir is not None:
        page_counts = DocumentStore(documents_dir).page_counts()
        logger.info(
            "Sources vérifiées contre {} documents de {}.",
            len(page_counts),
            documents_dir,
        )
    else:
        logger.warning(
            "DOCUMENTS_DIR non renseigné : l'existence des sources "
            "corrigées n'est pas vérifiée."
        )
    kili = create_client(config)
    report = promote_batch(
        kili,
        arguments.reference_project,
        arguments.review_project,
        config,
        page_counts,
    )
    logger.info(
        "{} cas lus · {} promus · {} rejetés · {} à régénérer · "
        "{} sources à corriger · {} laissés en attente.",
        report.cases_read,
        report.promoted,
        report.rejected,
        report.sent_to_regeneration,
        report.sources_to_fix,
        report.skipped,
    )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    write_json(
        arguments.report_path or Path(f"reports/promotion_{stamp}.json"),
        {"horodatage": stamp, **report.model_dump()},
    )


if __name__ == "__main__":
    main()
