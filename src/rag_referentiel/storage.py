"""Écriture des assets Kili, avec repli si la metadata est trop volumineuse.

La taille maximale d'un `json_metadata` n'est pas documentée par Kili.
Toute écriture passe donc par cette couche : si la charge dépasse le seuil
configuré, ou si le serveur la refuse pour cause de volume, on bascule sur
un repli documenté — les textes restent lisibles dans le `json_content`,
la metadata est réduite à ce qui sert à retrouver et à piloter l'entrée.

Conséquence assumée : une entrée repliée ne porte plus ses textes de
réponse en metadata. `referentiel.py` la signale et refuse de la
compléter à l'aveugle plutôt que de dédoublonner sur des textes absents.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from loguru import logger

#: Clés dont le contenu peut atteindre une taille arbitraire.
CLES_TEXTE_LONG = ("candidate_answer",)

_MOTIFS_VOLUME = (
    "too large",
    "too long",
    "payload",
    "entity too large",
    "exceeds",
    "size limit",
    "413",
)

T = TypeVar("T")


@dataclass
class ChargeAsset:
    """Couple metadata / contenu prêt à être envoyé à Kili."""

    json_metadata: dict
    json_content: list[dict]
    repli: bool = False


def taille_metadata(metadata: dict) -> int:
    """Mesure la taille sérialisée d'une metadata.

    Args:
        metadata: Metadata à mesurer.

    Returns:
        Le nombre d'octets de sa sérialisation JSON.
    """
    return len(json.dumps(metadata, ensure_ascii=False).encode("utf-8"))


def alleger_metadata(metadata: dict) -> dict:
    """Réduit une metadata à ses identifiants et à ses champs de pilotage.

    Les textes longs sont retirés : réponse candidate, et texte de chaque
    formulation validée. La question, elle, est conservée — c'est la clé
    fonctionnelle de l'entrée, et elle est bornée.

    Args:
        metadata: Metadata complète.

    Returns:
        Une nouvelle metadata allégée, marquée `repli_texte`.
    """
    allegee = {
        cle: valeur
        for cle, valeur in metadata.items()
        if cle not in CLES_TEXTE_LONG
    }
    reponses = allegee.get("answers")
    if isinstance(reponses, list):
        allegee["answers"] = [
            {cle: val for cle, val in reponse.items() if cle != "text"}
            for reponse in reponses
            if isinstance(reponse, dict)
        ]
    allegee["repli_texte"] = True
    return allegee


def preparer_charge(
    metadata: dict, json_content: list[dict], taille_max: int
) -> ChargeAsset:
    """Prépare la charge d'un asset, en allégeant la metadata si besoin.

    Args:
        metadata: Metadata complète.
        json_content: Rendu rich text de l'asset.
        taille_max: Taille maximale tolérée pour la metadata, en octets.

    Returns:
        La charge à envoyer à Kili.
    """
    if taille_metadata(metadata) <= taille_max:
        return ChargeAsset(metadata, json_content)
    logger.warning(
        "Metadata de {} octets au-dessus du seuil de {} : repli sur une "
        "metadata allégée, les textes restent dans le rendu.",
        taille_metadata(metadata),
        taille_max,
    )
    return ChargeAsset(alleger_metadata(metadata), json_content, repli=True)


def est_erreur_de_volume(erreur: Exception) -> bool:
    """Devine si une erreur d'écriture est due au volume de la charge.

    Args:
        erreur: Exception levée par le SDK Kili.

    Returns:
        `True` si le message évoque un dépassement de taille.
    """
    message = str(erreur).lower()
    return any(motif in message for motif in _MOTIFS_VOLUME)


def ecrire_avec_repli(
    ecriture: Callable[[ChargeAsset], T],
    metadata: dict,
    json_content: list[dict],
    taille_max: int,
) -> T:
    """Écrit un asset, en repliant la metadata si le serveur la refuse.

    Args:
        ecriture: Fonction qui réalise l'écriture Kili pour une charge.
        metadata: Metadata complète.
        json_content: Rendu rich text de l'asset.
        taille_max: Taille maximale tolérée pour la metadata, en octets.

    Returns:
        Le résultat de la fonction d'écriture.

    Raises:
        Exception: Toute erreur d'écriture qui n'est pas un problème de
            volume est propagée telle quelle.
    """
    charge = preparer_charge(metadata, json_content, taille_max)
    try:
        return ecriture(charge)
    except Exception as erreur:
        if charge.repli or not est_erreur_de_volume(erreur):
            raise
        logger.warning(
            "Écriture refusée pour cause de volume ({}) : nouvelle "
            "tentative avec une metadata allégée.",
            erreur,
        )
        return ecriture(
            ChargeAsset(
                alleger_metadata(metadata), json_content, repli=True
            )
        )
