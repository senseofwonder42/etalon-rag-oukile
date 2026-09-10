"""Revérification déclenchée à la main après évolution des documents.

Les documents bougent souvent de façon mineure : **aucune invalidation
automatique**. Ce script se contente de constater la dérive
(`--rapport`), ou de mettre en revérification les entrées citant les
documents désignés (`--declencher`). Le retour à `ACTIF` — ou le passage
à `ARCHIVE` — se fait par le job `ENTREE_TOUJOURS_VALIDE` du projet A,
récupéré par `promote.py`.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from _commun import ecrire_json, parametres
from loguru import logger

from rag_referentiel.client import creer_client
from rag_referentiel.referentiel import charger_entrees, ecrire_entree
from rag_referentiel.schemas import EntreeReferentiel

PRIORITE_REVERIFICATION = 10


def lire_versions(chemin: Path) -> dict[str, str]:
    """Lit les versions courantes des documents.

    Args:
        chemin: Fichier JSON associant un `doc_id` à sa `doc_version`.

    Returns:
        Les versions courantes.

    Raises:
        FileNotFoundError: Si le fichier n'existe pas.
    """
    if not chemin.exists():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}")
    return json.loads(chemin.read_text(encoding="utf-8"))


def analyser_pages(texte: str | None) -> tuple[int, int] | None:
    """Analyse un intervalle de pages `10-20`.

    Args:
        texte: Intervalle saisi, ou `None`.

    Returns:
        Le couple (première page, dernière page), ou `None`.

    Raises:
        ValueError: Si l'intervalle est mal formé.
    """
    if not texte:
        return None
    morceaux = texte.split("-")
    if len(morceaux) != 2 or not all(m.strip().isdigit() for m in morceaux):
        raise ValueError(
            f"Intervalle de pages illisible : {texte} (attendu « 10-20 »)."
        )
    debut, fin = (int(m) for m in morceaux)
    if debut > fin:
        raise ValueError(f"Intervalle de pages inversé : {texte}.")
    return debut, fin


def entrees_derivantes(
    entrees: list[EntreeReferentiel], versions: dict[str, str]
) -> list[dict]:
    """Liste les entrées dont une source a changé de version.

    Args:
        entrees: Entrées du référentiel.
        versions: Versions courantes des documents.

    Returns:
        Un enregistrement par entrée concernée, avec le détail des
        sources ayant dérivé.
    """
    rapport = []
    for entree in entrees:
        derives = [
            {
                "doc_id": source.doc_id,
                "page": source.page,
                "version_stockee": source.doc_version,
                "version_courante": versions[source.doc_id],
            }
            for source in entree.sources
            if source.doc_id in versions
            and source.doc_version != versions[source.doc_id]
        ]
        if derives:
            rapport.append(
                {
                    "question_id": entree.question_id,
                    "question": entree.question,
                    "statut": entree.statut,
                    "sources_derivantes": derives,
                }
            )
    return rapport


def entrees_impactees(
    entrees: list[EntreeReferentiel],
    docs: list[str],
    pages: tuple[int, int] | None,
) -> list[EntreeReferentiel]:
    """Sélectionne les entrées citant les documents désignés.

    Une source sans page est retenue dès que son document est désigné :
    l'intervalle de pages ne peut pas l'écarter.

    Args:
        entrees: Entrées du référentiel.
        docs: Documents désignés.
        pages: Intervalle de pages, ou `None` pour tout le document.

    Returns:
        Les entrées impactées.
    """
    designes = set(docs)
    retenues = []
    for entree in entrees:
        for source in entree.sources:
            if source.doc_id not in designes:
                continue
            if (
                pages is not None
                and source.page is not None
                and not pages[0] <= source.page <= pages[1]
            ):
                continue
            retenues.append(entree)
            break
    return retenues


def declencher(
    kili: object,
    project_id: str,
    entrees: list[EntreeReferentiel],
    taille_max_metadata: int,
) -> None:
    """Passe des entrées en revérification et les remet dans la file.

    Args:
        kili: Client Kili.
        project_id: Identifiant du projet A.
        entrees: Entrées à mettre en revérification.
        taille_max_metadata: Seuil de repli de la metadata, en octets.
    """
    external_ids = [entree.question_id for entree in entrees]
    for entree in entrees:
        entree.statut = "A_REVERIFIER"
        entree.version += 1
        ecrire_entree(kili, project_id, entree, taille_max_metadata)
    kili.update_properties_in_assets(
        project_id=project_id,
        external_ids=external_ids,
        priorities=[PRIORITE_REVERIFICATION] * len(external_ids),
    )
    kili.send_back_to_queue(
        project_id=project_id, external_ids=external_ids
    )
    logger.info("{} entrées remises en file.", len(external_ids))


def main() -> None:
    """Point d'entrée du script de revérification."""
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--projet-referentiel", required=True, help="Projet A."
    )
    analyseur.add_argument(
        "--rapport",
        action="store_true",
        help="Compare les versions stockées aux versions courantes.",
    )
    analyseur.add_argument(
        "--versions",
        type=Path,
        default=None,
        help="JSON { doc_id: doc_version } des versions courantes.",
    )
    analyseur.add_argument(
        "--declencher",
        action="store_true",
        help="Passe les entrées visées en A_REVERIFIER.",
    )
    analyseur.add_argument(
        "--doc",
        action="append",
        default=[],
        help="Document concerné (répétable).",
    )
    analyseur.add_argument(
        "--pages", default=None, help="Intervalle de pages, ex. « 10-20 »."
    )
    analyseur.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche ce qui serait fait, sans rien modifier.",
    )
    analyseur.add_argument(
        "--sortie",
        type=Path,
        default=None,
        help="Fichier du rapport de dérive.",
    )
    arguments = analyseur.parse_args()

    if not arguments.rapport and not arguments.declencher:
        analyseur.error("Choisir --rapport ou --declencher.")

    config = parametres()
    kili = creer_client(config)
    entrees = charger_entrees(kili, arguments.projet_referentiel)
    horodatage = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    if arguments.rapport:
        if arguments.versions is None:
            analyseur.error("--rapport exige --versions.")
        derives = entrees_derivantes(
            entrees, lire_versions(arguments.versions)
        )
        for element in derives:
            logger.info(
                "Dérive : {} — {}",
                element["question_id"],
                element["question"],
            )
        ecrire_json(
            arguments.sortie
            or Path(f"reports/derive_documentaire_{horodatage}.json"),
            {
                "horodatage": horodatage,
                "entrees_examinees": len(entrees),
                "entrees_derivantes": derives,
            },
        )

    if arguments.declencher:
        if not arguments.doc:
            analyseur.error("--declencher exige au moins un --doc.")
        impactees = entrees_impactees(
            entrees, arguments.doc, analyser_pages(arguments.pages)
        )
        for entree in impactees:
            logger.info(
                "{} : {} — {}",
                "à revérifier" if not arguments.dry_run else "serait "
                "mise en revérification",
                entree.question_id,
                entree.question,
            )
        if arguments.dry_run:
            logger.info(
                "--dry-run : {} entrées seraient modifiées, rien n'a été "
                "écrit.",
                len(impactees),
            )
            return
        declencher(
            kili,
            arguments.projet_referentiel,
            impactees,
            config.taille_max_metadata,
        )


if __name__ == "__main__":
    main()
