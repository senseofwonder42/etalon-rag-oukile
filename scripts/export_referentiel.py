"""Exporte le référentiel au format JSONL : une ligne par entrée ACTIF."""

import argparse
import json
from pathlib import Path

from _commun import parametres
from loguru import logger

from rag_referentiel.client import creer_client
from rag_referentiel.referentiel import charger_entrees


def main() -> None:
    """Point d'entrée du script d'export."""
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--projet-referentiel", required=True, help="Projet A."
    )
    analyseur.add_argument(
        "--sortie",
        type=Path,
        default=Path("reports/referentiel_export.jsonl"),
        help="Fichier JSONL de destination.",
    )
    analyseur.add_argument(
        "--tous-statuts",
        action="store_true",
        help="Exporte aussi les entrées A_REVERIFIER et ARCHIVE.",
    )
    arguments = analyseur.parse_args()

    config = parametres()
    kili = creer_client(config)
    entrees = charger_entrees(
        kili,
        arguments.projet_referentiel,
        statuts=None if arguments.tous_statuts else ("ACTIF",),
    )
    arguments.sortie.parent.mkdir(parents=True, exist_ok=True)
    with arguments.sortie.open("w", encoding="utf-8") as fichier:
        for entree in entrees:
            fichier.write(
                json.dumps(entree.model_dump(), ensure_ascii=False) + "\n"
            )
    logger.info(
        "{} entrées exportées dans {}", len(entrees), arguments.sortie
    )


if __name__ == "__main__":
    main()
