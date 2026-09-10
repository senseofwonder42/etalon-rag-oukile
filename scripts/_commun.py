"""Utilitaires partagés par les scripts en ligne de commande."""

import json
from pathlib import Path

from loguru import logger

from rag_referentiel.config import Parametres, charger_parametres


def lire_jsonl(chemin: Path) -> list[dict]:
    """Lit un fichier JSONL en ignorant les lignes illisibles.

    Args:
        chemin: Fichier à lire.

    Returns:
        Les enregistrements lus.

    Raises:
        FileNotFoundError: Si le fichier n'existe pas.
    """
    if not chemin.exists():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}")
    enregistrements = []
    for numero, ligne in enumerate(
        chemin.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not ligne.strip():
            continue
        try:
            enregistrements.append(json.loads(ligne))
        except json.JSONDecodeError as erreur:
            logger.warning(
                "Ligne {} de {} illisible, ignorée : {}",
                numero,
                chemin,
                erreur,
            )
    return enregistrements


def ecrire_json(chemin: Path, contenu: dict) -> None:
    """Écrit un rapport JSON lisible.

    Args:
        chemin: Fichier de destination.
        contenu: Contenu du rapport.
    """
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(contenu, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("Rapport écrit : {}", chemin)


def parametres() -> Parametres:
    """Charge les paramètres d'exécution.

    Returns:
        Les paramètres validés.
    """
    return charger_parametres()
