"""Lecture des labels et des metadata renvoyés par le SDK Kili."""

import json

from loguru import logger


def charger_metadata(brut: object) -> dict:
    """Décode une `jsonMetadata` renvoyée par Kili.

    Args:
        brut: Valeur renvoyée par le SDK (dictionnaire ou chaîne JSON).

    Returns:
        La metadata décodée ; un dictionnaire vide si elle est illisible.
    """
    if isinstance(brut, dict):
        return brut
    if isinstance(brut, str) and brut.strip():
        try:
            return json.loads(brut)
        except json.JSONDecodeError:
            logger.warning("Metadata JSON illisible, ignorée.")
    return {}


def categorie(reponse: dict, job: str) -> str | None:
    """Lit la catégorie choisie pour un job de classification.

    Args:
        reponse: `jsonResponse` du label.
        job: Nom du job.

    Returns:
        Le code de la catégorie, ou `None` si le job n'a pas été rempli.
    """
    categories = (reponse.get(job) or {}).get("categories") or []
    if not categories:
        return None
    return categories[0].get("name")


def categories(reponse: dict, job: str) -> list[str]:
    """Lit les catégories cochées pour un job à choix multiple.

    Args:
        reponse: `jsonResponse` du label.
        job: Nom du job.

    Returns:
        Les codes des catégories cochées, éventuellement vide.
    """
    cochees = (reponse.get(job) or {}).get("categories") or []
    return [
        item["name"]
        for item in cochees
        if isinstance(item, dict) and item.get("name")
    ]


def transcription(reponse: dict, job: str) -> str | None:
    """Lit le texte saisi pour un job de transcription.

    Args:
        reponse: `jsonResponse` du label.
        job: Nom du job.

    Returns:
        Le texte saisi, ou `None` si le job est vide.
    """
    texte = (reponse.get(job) or {}).get("text")
    if isinstance(texte, str) and texte.strip():
        return texte.strip()
    return None


def labels_humains(labels: list[dict]) -> list[dict]:
    """Retient les labels humains d'un asset, du plus ancien au plus récent.

    Les labels de prédiction et d'inférence sont écartés : le type
    `INFERENCE` est celui de la piste d'audit écrite par les scripts, qui
    ne doit jamais être relue comme un arbitrage.

    Args:
        labels: Labels renvoyés par Kili.

    Returns:
        Les labels humains, triés par date de création croissante.
    """
    humains = [
        label
        for label in labels
        if label.get("labelType") in {"DEFAULT", "REVIEW", None}
    ]
    return sorted(humains, key=lambda item: item.get("createdAt") or "")


def dernier_label(labels: list[dict]) -> dict | None:
    """Retient le label humain le plus récent d'un asset.

    Les labels de prédiction et d'inférence sont écartés : seuls les
    arbitrages humains comptent.

    Args:
        labels: Labels renvoyés par Kili.

    Returns:
        Le label le plus récent, ou `None` si l'asset n'en porte pas.
    """
    candidats = labels_humains(labels)
    return candidats[-1] if candidats else None


def auteur_de(label: dict) -> str:
    """Lit l'auteur d'un label.

    Args:
        label: Label renvoyé par Kili.

    Returns:
        L'adresse de l'auteur, ou `inconnu`.
    """
    return (label.get("author") or {}).get("email") or "inconnu"
