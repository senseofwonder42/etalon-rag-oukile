"""Modèles pydantic sérialisés dans les `json_metadata` des assets Kili."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Statut = Literal["ACTIF", "A_REVERIFIER", "ARCHIVE"]
Origine = Literal["metier", "rag_valide", "rag_corrige"]
Motif = Literal[
    "NOUVELLE_QUESTION",
    "DIVERGENCE",
    "APPARIEMENT_INCERTAIN",
    "REVERIFICATION_DOC",
]
StatutRevue = Literal["EN_ATTENTE", "PROMU", "REJETE"]


class Source(BaseModel):
    """Référence documentaire citée par une réponse."""

    model_config = ConfigDict(extra="ignore")

    doc_id: str
    page: int | None = None
    doc_version: str | None = None

    def libelle(self) -> str:
        """Rend la source au format `doc.pdf:12`.

        Returns:
            La source sous forme textuelle ; sans `:page` si la page est
            inconnue.
        """
        if self.page is None:
            return self.doc_id
        return f"{self.doc_id}:{self.page}"


class Answer(BaseModel):
    """Formulation validée d'une réponse du référentiel."""

    model_config = ConfigDict(extra="ignore")

    id: str
    text: str
    origine: Origine
    auteur: str
    date: str
    run_id: str | None = None


class EntreeReferentiel(BaseModel):
    """Entrée du projet A : une question et ses réponses validées."""

    model_config = ConfigDict(extra="ignore")

    question_id: str
    question: str
    statut: Statut = "ACTIF"
    version: int = 1
    answers: list[Answer] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    derniere_verification: str | None = None
    # Horodatage du dernier label du projet A déjà consommé par
    # `promote.py`. Sert de filigrane : tous les labels humains créés
    # après lui seront appliqués, dans l'ordre, à la prochaine promotion.
    derniere_promotion: str | None = None
    # Positionné par la couche de stockage quand la metadata a dû être
    # allégée : les textes ne sont alors plus lisibles que dans le rendu.
    repli_texte: bool = False


class Verdict(BaseModel):
    """Avis du LLM-as-judge sur une réponse candidate."""

    model_config = ConfigDict(extra="ignore")

    conforme: bool
    confiance: float = Field(ge=0.0, le=1.0)
    motif: str


class CasRevue(BaseModel):
    """Asset du projet B : une occurrence de production à arbitrer."""

    model_config = ConfigDict(extra="ignore")

    question_id: str
    run_id: str
    motif: Motif
    question: str
    candidate_answer: str
    sources: list[Source] = Field(default_factory=list)
    verdict_juge: Verdict | None = None
    score_appariement: float | None = None
    question_id_candidat: str | None = None
    statut_revue: StatutRevue = "EN_ATTENTE"
    repli_texte: bool = False


class OccurrenceProd(BaseModel):
    """Ligne du JSONL de production consommé par `monitor_run.py`."""

    model_config = ConfigDict(extra="ignore")

    run_id: str
    timestamp: str | None = None
    question: str
    answer_markdown: str = ""
    sources: list[Source] = Field(default_factory=list)


class EntreeInitiale(BaseModel):
    """Ligne du JSONL d'amorçage consommé par `bootstrap.py`."""

    model_config = ConfigDict(extra="ignore")

    question: str
    answers: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)


def aujourdhui() -> str:
    """Renvoie la date du jour au format ISO.

    Returns:
        La date courante, par exemple `2026-07-18`.
    """
    return date.today().isoformat()
