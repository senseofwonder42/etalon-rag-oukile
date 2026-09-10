"""De la revue vers le référentiel : applique les arbitrages métier.

Le script est idempotent : le relancer ne duplique pas de variante et
n'incrémente pas `version` sans changement d'état.
"""

import argparse
from datetime import UTC, datetime
from pathlib import Path

from _commun import ecrire_json, parametres
from loguru import logger

from rag_referentiel.client import creer_client
from rag_referentiel.referentiel import promouvoir_lot


def main() -> None:
    """Point d'entrée du script de promotion."""
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--projet-referentiel", required=True, help="Projet A."
    )
    analyseur.add_argument("--projet-revue", required=True, help="Projet B.")
    analyseur.add_argument(
        "--rapport",
        type=Path,
        default=None,
        help="Fichier du rapport JSON.",
    )
    arguments = analyseur.parse_args()

    config = parametres()
    kili = creer_client(config)
    rapport = promouvoir_lot(
        kili,
        arguments.projet_referentiel,
        arguments.projet_revue,
        config,
    )
    logger.info(
        "{} cas lus · {} promus · {} rejetés · {} laissés en attente.",
        rapport.cas_lus,
        rapport.promus,
        rapport.rejetes,
        rapport.ignores,
    )
    horodatage = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    ecrire_json(
        arguments.rapport or Path(f"reports/promotion_{horodatage}.json"),
        {"horodatage": horodatage, **rapport.model_dump()},
    )


if __name__ == "__main__":
    main()
