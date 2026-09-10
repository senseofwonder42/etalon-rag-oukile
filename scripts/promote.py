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
        "--rapport",
        dest="report_path",
        type=Path,
        default=None,
        help="Fichier du rapport JSON.",
    )
    arguments = parser.parse_args()

    config = settings()
    kili = create_client(config)
    report = promote_batch(
        kili,
        arguments.reference_project,
        arguments.review_project,
        config,
    )
    logger.info(
        "{} cas lus · {} promus · {} rejetés · {} laissés en attente.",
        report.cases_read,
        report.promoted,
        report.rejected,
        report.skipped,
    )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    write_json(
        arguments.report_path or Path(f"reports/promotion_{stamp}.json"),
        {"horodatage": stamp, **report.model_dump()},
    )


if __name__ == "__main__":
    main()
