"""End to end demonstration, with fake data.

Goal: show the annotation interface to the business team in under five
minutes, with no model API key — matching and judging are offline by
default.
"""

import argparse
from pathlib import Path

from _commun import read_jsonl, settings
from loguru import logger
from monitor_run import build_judge, build_matcher, process

from rag_referentiel.client import create_client
from rag_referentiel.config import Settings
from rag_referentiel.referentiel import build_entry, import_entries
from rag_referentiel.referentiel import (
    create_project as create_reference_project,
)
from rag_referentiel.revue import compute_external_ids, create_cases
from rag_referentiel.revue import create_project as create_review_project
from rag_referentiel.schemas import SeedEntry, today


def project_url(config: Settings, project_id: str) -> str:
    """Build the URL of a project from the API endpoint.

    Args:
        config: Runtime settings.
        project_id: Identifier of the project.

    Returns:
        The URL of the project in the Kili application.
    """
    root = config.kili_api_endpoint.split("/api/")[0]
    return f"{root}/label/projects/{project_id}"


def create_demo(arguments: argparse.Namespace, config: Settings) -> None:
    """Set up the whole demonstration.

    Args:
        arguments: Command line arguments.
        config: Runtime settings.
    """
    kili = create_client(config)

    reference_id = create_reference_project(
        kili, config.reference_project_title
    )
    date = today()
    entries = [
        build_entry(
            question=seed.question,
            texts=seed.answers,
            sources=seed.sources,
            author="demo",
            date=date,
        )
        for seed in (
            SeedEntry.model_validate(line)
            for line in read_jsonl(arguments.reference_path)
        )
        if seed.question.strip()
    ]
    import_entries(kili, reference_id, entries, config)

    review_id = create_review_project(kili, config.review_project_title)
    cases, report = process(
        read_jsonl(arguments.run_path),
        entries,
        build_matcher(entries, config, offline=True),
        build_judge(config, offline=True),
    )
    create_cases(
        kili,
        review_id,
        cases,
        compute_external_ids(cases),
        {entry.question_id: entry.answers for entry in entries},
        {entry.question_id: entry.question for entry in entries},
        config,
    )

    logger.info("Décisions d'appariement : {}", report["decisions"])
    logger.info("Conformité : {}", report["conformite"])
    print("\n=== Démonstration prête ===")
    print(f"Projet A — référentiel : {reference_id}")
    print(f"  {project_url(config, reference_id)}")
    print(f"    {len(entries)} questions déjà validées.")
    print(f"Projet B — revue prod  : {review_id}")
    print(f"  {project_url(config, review_id)}")
    print(f"    {len(cases)} cas à arbitrer.")
    print(
        "\nÀ regarder : le rendu rich text des cartes, le sous-titre "
        "« Réponse 1 »\nau-dessus de chaque formulation, la liste des "
        "sources rappelée sous le\ntableau et prête à copier-coller, et le "
        "fait que le verdict du juge\nn'apparaît nulle part à l'écran."
    )


def teardown(arguments: argparse.Namespace, config: Settings) -> None:
    """Clean up a demonstration project.

    Deletes the assets, then archives the project. Permanent deletion of
    the project is asynchronous and irreversible: it stays behind
    `--supprimer-projet`.

    Args:
        arguments: Command line arguments.
        config: Runtime settings.
    """
    kili = create_client(config)
    assets = kili.assets(
        project_id=arguments.project_id, fields=["externalId"]
    )
    external_ids = [asset["externalId"] for asset in assets]
    if external_ids:
        kili.delete_many_from_dataset(
            project_id=arguments.project_id, external_ids=external_ids
        )
        logger.info("{} assets supprimés.", len(external_ids))
    if arguments.delete_project:
        kili.delete_project(arguments.project_id)
        logger.info("Projet {} supprimé.", arguments.project_id)
    else:
        kili.archive_project(arguments.project_id)
        logger.info("Projet {} archivé.", arguments.project_id)


def main() -> None:
    """Entry point of the demonstration."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--create",
        dest="create",
        action="store_true",
        help="Monte la démonstration.",
    )
    parser.add_argument(
        "--teardown",
        dest="teardown",
        action="store_true",
        help="Nettoie un projet.",
    )
    parser.add_argument(
        "--project-id",
        dest="project_id",
        default=None,
        help="Projet à nettoyer.",
    )
    parser.add_argument(
        "--supprimer-projet",
        dest="delete_project",
        action="store_true",
        help="Supprime le projet au lieu de l'archiver (irréversible).",
    )
    parser.add_argument(
        "--referentiel",
        dest="reference_path",
        type=Path,
        default=Path("data/samples/referentiel_initial.jsonl"),
        help="JSONL d'amorçage du référentiel.",
    )
    parser.add_argument(
        "--run",
        dest="run_path",
        type=Path,
        default=Path("data/samples/run_prod.jsonl"),
        help="JSONL des occurrences de production.",
    )
    arguments = parser.parse_args()
    config = settings()

    if arguments.create:
        create_demo(arguments, config)
    elif arguments.teardown:
        if not arguments.project_id:
            parser.error("--teardown exige --project-id.")
        teardown(arguments, config)
    else:
        parser.error("Choisir --create ou --teardown.")


if __name__ == "__main__":
    main()
