"""Démonstration de bout en bout, avec des données factices.

Objectif : montrer l'interface d'annotation au métier en moins de cinq
minutes, sans clé d'API de modèle — l'appariement et le juge sont hors
ligne par défaut.
"""

import argparse
from pathlib import Path

from _commun import lire_jsonl, parametres
from loguru import logger
from monitor_run import construire_juge, construire_matcher, traiter

from rag_referentiel.client import creer_client
from rag_referentiel.config import Parametres
from rag_referentiel.referentiel import (
    creer_entree,
    importer_entrees,
)
from rag_referentiel.referentiel import (
    creer_projet as creer_projet_referentiel,
)
from rag_referentiel.revue import (
    calculer_identifiants,
    creer_cas,
)
from rag_referentiel.revue import (
    creer_projet as creer_projet_revue,
)
from rag_referentiel.schemas import EntreeInitiale, aujourdhui


def url_projet(config: Parametres, project_id: str) -> str:
    """Construit l'URL d'un projet à partir de l'endpoint d'API.

    Args:
        config: Paramètres d'exécution.
        project_id: Identifiant du projet.

    Returns:
        L'URL du projet dans l'application Kili.
    """
    racine = config.kili_api_endpoint.split("/api/")[0]
    return f"{racine}/label/projects/{project_id}"


def creer(arguments: argparse.Namespace, config: Parametres) -> None:
    """Monte la démonstration complète.

    Args:
        arguments: Arguments de la ligne de commande.
        config: Paramètres d'exécution.
    """
    kili = creer_client(config)

    id_referentiel = creer_projet_referentiel(
        kili, config.titre_projet_referentiel
    )
    date = aujourdhui()
    entrees = [
        creer_entree(
            question=initiale.question,
            textes=initiale.answers,
            sources=initiale.sources,
            auteur="demo",
            date=date,
        )
        for initiale in (
            EntreeInitiale.model_validate(ligne)
            for ligne in lire_jsonl(arguments.referentiel)
        )
        if initiale.question.strip()
    ]
    importer_entrees(
        kili, id_referentiel, entrees, config.taille_max_metadata
    )

    id_revue = creer_projet_revue(kili, config.titre_projet_revue)
    cas, rapport = traiter(
        lire_jsonl(arguments.run),
        entrees,
        construire_matcher(entrees, config, hors_ligne=True),
        construire_juge(config, hors_ligne=True),
    )
    creer_cas(
        kili,
        id_revue,
        cas,
        calculer_identifiants(cas),
        {entree.question_id: entree.answers for entree in entrees},
        {entree.question_id: entree.question for entree in entrees},
        config.taille_max_metadata,
    )

    logger.info("Décisions d'appariement : {}", rapport["decisions"])
    logger.info("Conformité : {}", rapport["conformite"])
    print("\n=== Démonstration prête ===")
    print(f"Projet A — référentiel : {id_referentiel}")
    print(f"  {url_projet(config, id_referentiel)}")
    print(f"    {len(entrees)} questions déjà validées.")
    print(f"Projet B — revue prod  : {id_revue}")
    print(f"  {url_projet(config, id_revue)}")
    print(f"    {len(cas)} cas à arbitrer.")
    print(
        "\nÀ regarder : le rendu rich text des cartes, les libellés des "
        "jobs,\net le fait que le verdict du juge n'apparaît nulle part "
        "à l'écran."
    )


def nettoyer(arguments: argparse.Namespace, config: Parametres) -> None:
    """Nettoie un projet de démonstration.

    Supprime les assets, puis archive le projet. La suppression définitive
    du projet est asynchrone et irréversible : elle reste derrière
    `--supprimer-projet`.

    Args:
        arguments: Arguments de la ligne de commande.
        config: Paramètres d'exécution.
    """
    kili = creer_client(config)
    assets = kili.assets(
        project_id=arguments.project_id, fields=["externalId"]
    )
    external_ids = [asset["externalId"] for asset in assets]
    if external_ids:
        kili.delete_many_from_dataset(
            project_id=arguments.project_id, external_ids=external_ids
        )
        logger.info("{} assets supprimés.", len(external_ids))
    if arguments.supprimer_projet:
        kili.delete_project(arguments.project_id)
        logger.info("Projet {} supprimé.", arguments.project_id)
    else:
        kili.archive_project(arguments.project_id)
        logger.info("Projet {} archivé.", arguments.project_id)


def main() -> None:
    """Point d'entrée de la démonstration."""
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--create", action="store_true", help="Monte la démonstration."
    )
    analyseur.add_argument(
        "--teardown", action="store_true", help="Nettoie un projet."
    )
    analyseur.add_argument(
        "--project-id", default=None, help="Projet à nettoyer."
    )
    analyseur.add_argument(
        "--supprimer-projet",
        action="store_true",
        help="Supprime le projet au lieu de l'archiver (irréversible).",
    )
    analyseur.add_argument(
        "--referentiel",
        type=Path,
        default=Path("data/samples/referentiel_initial.jsonl"),
        help="JSONL d'amorçage du référentiel.",
    )
    analyseur.add_argument(
        "--run",
        type=Path,
        default=Path("data/samples/run_prod.jsonl"),
        help="JSONL des occurrences de production.",
    )
    arguments = analyseur.parse_args()
    config = parametres()

    if arguments.create:
        creer(arguments, config)
    elif arguments.teardown:
        if not arguments.project_id:
            analyseur.error("--teardown exige --project-id.")
        nettoyer(arguments, config)
    else:
        analyseur.error("Choisir --create ou --teardown.")


if __name__ == "__main__":
    main()
