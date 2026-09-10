"""Projet B — Revue prod RAG : création et lecture des cas à arbitrer.

Ce projet est la file de travail du métier : un asset = une occurrence de
production à trancher. Il ne pollue jamais le référentiel ; seul
`promote.py` transfère les arbitrages vers le projet A.
"""

from loguru import logger
from pydantic import BaseModel

from .interfaces import INTERFACE_REVUE
from .labels import (
    auteur_de,
    categorie,
    charger_metadata,
    dernier_label,
    transcription,
)
from .normalisation import calculer_external_id_revue
from .rendering import rendu_asset_revue
from .schemas import Answer, CasRevue, StatutRevue
from .storage import preparer_charge

CHAMPS_CAS = [
    "externalId",
    "id",
    "jsonMetadata",
    "status",
    "labels.author.email",
    "labels.createdAt",
    "labels.jsonResponse",
    "labels.labelType",
]


class LabelRevue(BaseModel):
    """Arbitrage métier lu sur un asset du projet B."""

    auteur: str
    date: str
    meme_question: str | None = None
    candidate_correcte: str | None = None
    version_corrigee: str | None = None
    sources_pertinentes: str | None = None
    sources_corrigees: str | None = None


class CasArbitre(BaseModel):
    """Cas de revue accompagné de son arbitrage."""

    external_id: str
    cas: CasRevue
    label: LabelRevue


def creer_projet(kili: object, titre: str) -> str:
    """Crée le projet Kili de revue.

    Args:
        kili: Client Kili.
        titre: Titre du projet.

    Returns:
        L'identifiant du projet créé.
    """
    projet = kili.create_project(
        title=titre,
        input_type="TEXT",
        json_interface=INTERFACE_REVUE,
        description=(
            "File de revue métier des occurrences de production du RAG."
        ),
    )
    logger.info("Projet de revue créé : {}", projet["id"])
    return projet["id"]


def calculer_identifiants(cas: list[CasRevue]) -> list[str]:
    """Attribue un `external_id` unique à chaque cas d'un lot.

    Deux occurrences d'un même run appariées à la même question
    produiraient le même identifiant : un suffixe les distingue, sans quoi
    le SDK écarterait silencieusement le doublon à l'import.

    Args:
        cas: Cas de revue du lot.

    Returns:
        Les `external_id`, dans l'ordre des cas.
    """
    pris: set[str] = set()
    identifiants: list[str] = []
    for element in cas:
        base = calculer_external_id_revue(element.question_id, element.run_id)
        identifiant = base
        suffixe = 2
        while identifiant in pris:
            identifiant = f"{base}_{suffixe}"
            suffixe += 1
        pris.add(identifiant)
        identifiants.append(identifiant)
    return identifiants


def creer_cas(
    kili: object,
    project_id: str,
    cas: list[CasRevue],
    external_ids: list[str],
    reponses_par_question: dict[str, list[Answer]],
    questions_candidates: dict[str, str],
    taille_max_metadata: int,
) -> list[str]:
    """Importe des cas de revue dans le projet B.

    Args:
        kili: Client Kili.
        project_id: Identifiant du projet de revue.
        cas: Cas à créer.
        external_ids: Identifiants externes des assets, dans l'ordre des
            cas (voir `calculer_identifiants`).
        reponses_par_question: Formulations validées, par `question_id`,
            à afficher en regard de la réponse candidate.
        questions_candidates: Question du référentiel proposée, par
            `question_id` candidat, pour les appariements incertains.
        taille_max_metadata: Seuil de repli de la metadata, en octets.
            L'import se faisant par lot, le repli est ici décidé sur la
            taille mesurée, sans nouvelle tentative après refus serveur.

    Returns:
        Les `external_id` des assets créés.
    """
    if not cas:
        return []

    contenus: list[list[dict]] = []
    metadatas: list[dict] = []

    for element in cas:
        rendu = rendu_asset_revue(
            element,
            reponses_par_question.get(
                element.question_id_candidat or element.question_id, []
            ),
            questions_candidates.get(element.question_id_candidat or ""),
        )
        charge = preparer_charge(
            element.model_dump(), rendu, taille_max_metadata
        )
        contenus.append(charge.json_content)
        metadatas.append(charge.json_metadata)

    kili.append_many_to_dataset(
        project_id=project_id,
        external_id_array=external_ids,
        json_content_array=contenus,
        json_metadata_array=metadatas,
    )
    logger.info("{} cas de revue importés.", len(external_ids))
    return external_ids


def lire_cas_arbitres(kili: object, project_id: str) -> list[CasArbitre]:
    """Lit les cas en attente qui portent un arbitrage métier.

    Args:
        kili: Client Kili.
        project_id: Identifiant du projet de revue.

    Returns:
        Les cas dont le `statut_revue` vaut `EN_ATTENTE` et qui portent au
        moins un label.
    """
    assets = kili.assets(
        project_id=project_id,
        fields=CHAMPS_CAS,
        metadata_where={"statut_revue": "EN_ATTENTE"},
    )
    resultat: list[CasArbitre] = []
    for asset in assets:
        metadata = charger_metadata(asset.get("jsonMetadata"))
        if metadata.get("statut_revue") != "EN_ATTENTE":
            continue
        brut = dernier_label(asset.get("labels") or [])
        if brut is None:
            continue
        label = _lire_label(brut)
        try:
            cas = CasRevue.model_validate(metadata)
        except ValueError as erreur:
            logger.warning(
                "Cas de revue illisible ({}) : {}",
                asset.get("externalId"),
                erreur,
            )
            continue
        resultat.append(
            CasArbitre(
                external_id=asset["externalId"], cas=cas, label=label
            )
        )
    return resultat


def marquer_statut(
    kili: object,
    project_id: str,
    external_ids: list[str],
    statut: StatutRevue,
    cas_par_external_id: dict[str, CasRevue],
) -> None:
    """Met à jour le `statut_revue` d'assets du projet B.

    Args:
        kili: Client Kili.
        project_id: Identifiant du projet de revue.
        external_ids: Assets à mettre à jour.
        statut: Nouveau statut de revue.
        cas_par_external_id: Cas correspondants, pour réécrire une
            metadata complète.
    """
    if not external_ids:
        return
    metadatas = []
    for external_id in external_ids:
        cas = cas_par_external_id[external_id].model_copy(
            update={"statut_revue": statut}
        )
        metadatas.append(cas.model_dump())
    kili.update_properties_in_assets(
        project_id=project_id,
        external_ids=external_ids,
        json_metadatas=metadatas,
    )
    logger.info("{} cas passés en {}.", len(external_ids), statut)


def _lire_label(label: dict) -> LabelRevue:
    """Traduit un label Kili en arbitrage métier.

    Args:
        label: Label renvoyé par Kili.

    Returns:
        L'arbitrage correspondant.
    """
    reponse = label.get("jsonResponse") or {}
    return LabelRevue(
        auteur=auteur_de(label),
        date=(label.get("createdAt") or "")[:10],
        meme_question=categorie(reponse, "MEME_QUESTION"),
        candidate_correcte=categorie(reponse, "CANDIDATE_CORRECTE"),
        version_corrigee=transcription(reponse, "VERSION_CORRIGEE"),
        sources_pertinentes=categorie(reponse, "SOURCES_PERTINENTES"),
        sources_corrigees=transcription(reponse, "SOURCES_CORRIGEES"),
    )
