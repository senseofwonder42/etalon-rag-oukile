"""Seed the repository (project A) from a JSONL of validated questions.

Creates the Kili project when no identifier is given, then imports one
entry per question. Entries already present are not imported again.
"""

import argparse
from pathlib import Path

from _commun import read_jsonl, settings
from loguru import logger

from rag_referentiel.client import create_client
from rag_referentiel.referentiel import (
    build_entry,
    create_project,
    import_entries,
    load_entries,
)
from rag_referentiel.schemas import SeedEntry, today


def main() -> None:
    """Entry point of the seeding script."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--entree",
        dest="input_path",
        type=Path,
        default=Path("data/samples/referentiel_initial.jsonl"),
        help="JSONL des questions déjà validées par le métier.",
    )
    parser.add_argument(
        "--project-id",
        dest="project_id",
        default=None,
        help="Projet A existant ; créé si absent.",
    )
    parser.add_argument(
        "--auteur",
        dest="author",
        default="amorcage",
        help="Auteur enregistré sur les formulations importées.",
    )
    arguments = parser.parse_args()

    config = settings()
    kili = create_client(config)
    project_id = arguments.project_id or create_project(
        kili, config.reference_project_title
    )

    existing = {
        entry.question_id for entry in load_entries(kili, project_id)
    }
    date = today()
    entries = []
    for line in read_jsonl(arguments.input_path):
        seed = SeedEntry.model_validate(line)
        if not seed.question.strip():
            logger.warning("Question vide ignorée.")
            continue
        entry = build_entry(
            question=seed.question,
            texts=seed.answers,
            sources=seed.sources,
            author=arguments.author,
            date=date,
        )
        if entry.question_id in existing:
            logger.info("Entrée déjà présente : {}", entry.question_id)
            continue
        existing.add(entry.question_id)
        entries.append(entry)

    import_entries(kili, project_id, entries, config.max_metadata_size)
    logger.info(
        "Référentiel amorcé — projet {} · {} entrées ajoutées.",
        project_id,
        len(entries),
    )


if __name__ == "__main__":
    main()
