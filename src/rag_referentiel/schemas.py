"""Pydantic models serialized into the `json_metadata` of Kili assets.

Field names follow the metadata contract given in the specification and
are therefore left untouched: they are a wire format, read back by every
run and by the JSONL exports.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["ACTIF", "A_REVERIFIER", "ARCHIVE"]
Origin = Literal["metier", "rag_valide", "rag_corrige"]
Reason = Literal[
    "NOUVELLE_QUESTION",
    "DIVERGENCE",
    "APPARIEMENT_INCERTAIN",
    "REVERIFICATION_DOC",
]
ReviewStatus = Literal["EN_ATTENTE", "PROMU", "REJETE"]


class Source(BaseModel):
    """Documentary reference cited by an answer."""

    model_config = ConfigDict(extra="ignore")

    doc_id: str
    page: int | None = None
    doc_version: str | None = None

    def label(self) -> str:
        """Render the source as `doc.pdf:12`.

        Returns:
            The source as text; without `:page` when the page is unknown.
        """
        if self.page is None:
            return self.doc_id
        return f"{self.doc_id}:{self.page}"


class Answer(BaseModel):
    """Validated wording of a reference answer."""

    model_config = ConfigDict(extra="ignore")

    id: str
    text: str
    origine: Origin
    auteur: str
    date: str
    run_id: str | None = None


class ReferenceEntry(BaseModel):
    """Project A entry: one question and its validated answers."""

    model_config = ConfigDict(extra="ignore")

    question_id: str
    question: str
    statut: Status = "ACTIF"
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
    """LLM-as-judge opinion on a candidate answer."""

    model_config = ConfigDict(extra="ignore")

    conforme: bool
    confiance: float = Field(ge=0.0, le=1.0)
    motif: str


class ReviewCase(BaseModel):
    """Project B asset: one production occurrence to arbitrate."""

    model_config = ConfigDict(extra="ignore")

    question_id: str
    run_id: str
    motif: Reason
    question: str
    candidate_answer: str
    sources: list[Source] = Field(default_factory=list)
    verdict_juge: Verdict | None = None
    score_appariement: float | None = None
    question_id_candidat: str | None = None
    statut_revue: ReviewStatus = "EN_ATTENTE"
    repli_texte: bool = False


class ProductionOccurrence(BaseModel):
    """One line of the production JSONL consumed by `monitor_run.py`."""

    model_config = ConfigDict(extra="ignore")

    run_id: str
    timestamp: str | None = None
    question: str
    answer_markdown: str = ""
    sources: list[Source] = Field(default_factory=list)


class SeedEntry(BaseModel):
    """One line of the seed JSONL consumed by `bootstrap.py`."""

    model_config = ConfigDict(extra="ignore")

    question: str
    answers: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)


def today() -> str:
    """Return the current date in ISO format.

    Returns:
        The current date, for instance `2026-07-18`.
    """
    return date.today().isoformat()
