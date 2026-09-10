"""Export the repository as JSONL: one line per ACTIF entry."""

import argparse
import json
from pathlib import Path

from _commun import settings
from loguru import logger

from rag_referentiel.client import create_client
from rag_referentiel.referentiel import load_entries


def main() -> None:
    """Entry point of the export script."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--projet-referentiel",
        dest="reference_project",
        required=True,
        help="Projet A.",
    )
    parser.add_argument(
        "--sortie",
        dest="output_path",
        type=Path,
        default=Path("reports/referentiel_export.jsonl"),
        help="Fichier JSONL de destination.",
    )
    parser.add_argument(
        "--tous-statuts",
        dest="all_statuses",
        action="store_true",
        help="Exporte aussi les entrées A_REVERIFIER et ARCHIVE.",
    )
    arguments = parser.parse_args()

    config = settings()
    kili = create_client(config)
    entries = load_entries(
        kili,
        arguments.reference_project,
        statuses=None if arguments.all_statuses else ("ACTIF",),
    )
    arguments.output_path.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output_path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(
                json.dumps(entry.model_dump(), ensure_ascii=False) + "\n"
            )
    logger.info(
        "{} entrées exportées dans {}",
        len(entries),
        arguments.output_path,
    )


if __name__ == "__main__":
    main()
