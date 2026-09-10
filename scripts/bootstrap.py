"""Amorce le référentiel (projet A) depuis un JSONL de questions validées.

Crée le projet Kili si aucun identifiant n'est fourni, puis importe une
entrée par question. Les entrées déjà présentes ne sont pas réimportées.
"""

import argparse
from pathlib import Path

from _commun import lire_jsonl, parametres
from loguru import logger

from rag_referentiel.client import creer_client
from rag_referentiel.referentiel import (
    charger_entrees,
    creer_entree,
    creer_projet,
    importer_entrees,
)
from rag_referentiel.schemas import EntreeInitiale, aujourdhui


def main() -> None:
    """Point d'entrée du script d'amorçage."""
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--entree",
        type=Path,
        default=Path("data/samples/referentiel_initial.jsonl"),
        help="JSONL des questions déjà validées par le métier.",
    )
    analyseur.add_argument(
        "--project-id",
        default=None,
        help="Projet A existant ; créé si absent.",
    )
    analyseur.add_argument(
        "--auteur",
        default="amorcage",
        help="Auteur enregistré sur les formulations importées.",
    )
    arguments = analyseur.parse_args()

    config = parametres()
    kili = creer_client(config)
    project_id = arguments.project_id or creer_projet(
        kili, config.titre_projet_referentiel
    )

    existantes = {
        entree.question_id for entree in charger_entrees(kili, project_id)
    }
    date = aujourdhui()
    entrees = []
    for ligne in lire_jsonl(arguments.entree):
        initiale = EntreeInitiale.model_validate(ligne)
        if not initiale.question.strip():
            logger.warning("Question vide ignorée.")
            continue
        entree = creer_entree(
            question=initiale.question,
            textes=initiale.answers,
            sources=initiale.sources,
            auteur=arguments.auteur,
            date=date,
        )
        if entree.question_id in existantes:
            logger.info("Entrée déjà présente : {}", entree.question_id)
            continue
        existantes.add(entree.question_id)
        entrees.append(entree)

    importer_entrees(kili, project_id, entrees, config.taille_max_metadata)
    logger.info(
        "Référentiel amorcé — projet {} · {} entrées ajoutées.",
        project_id,
        len(entrees),
    )


if __name__ == "__main__":
    main()
