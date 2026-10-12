"""Regeneration of the answers the business team judged non compliant.

Writing a full answer is costly for the business team, and a model
structures a long answer better. When a case is arbitrated « Presque »
or « Non » without a corrected version, `promote.py` moves it to
`A_REGENERER`. This module then:

1. takes the ground truth sources of the arbitration — the corrected
   list, or the cited one when it was judged relevant;
2. renders their pages as images, from the local PDF files;
3. has a vision model draft the answer from those pages only;
4. imports a twin asset `<external_id>__relecture` into project B, with
   the draft pre-filled in `VERSION_CORRIGEE` by a `PREDICTION` label.

The proofreading is then promoted like any other arbitration. A case is
never stuck: when no draft can be written, the twin asset is imported
all the same, without a draft, and says why.

Prompts stay in French, like the content they produce.
"""

import base64
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from loguru import logger
from pydantic import BaseModel, Field

from .config import Settings
from .documents import DocumentStore
from .referentiel import (
    ground_truth_sources,
    load_entries,
    promotion_target,
)
from .revue import (
    ArbitratedCase,
    create_cases,
    read_arbitrated_cases,
    set_review_status,
)
from .schemas import ReviewCase, Source
from .sources import check_sources_exist

#: Suffixe de l'`external_id` de l'asset de relecture.
DRAFT_SUFFIX = "__relecture"
#: Bêta de l'API qui active le repli côté serveur sur refus du modèle.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

REGENERATION_SYSTEM_PROMPT = """Tu rédiges la réponse de référence à une
question posée à l'assistant d'un assureur. Cette réponse servira
d'étalon pour juger les réponses futures : elle doit être exacte avant
d'être élégante.

Tu disposes, en images, des pages de documents qui font foi, chacune
précédée de son repère. Règles :

- n'affirme rien qui ne figure pas sur ces pages ; si elles ne
  permettent pas de répondre entièrement, dis-le explicitement plutôt
  que de compléter ;
- reprends à l'identique les montants, délais, pourcentages, conditions
  et exclusions ;
- cite la source après chaque affirmation, sous la forme
  (document.pdf, p. 12) ;
- une réponse précédente a été jugée non conforme par un expert métier :
  elle t'est montrée pour que tu évites ses erreurs, pas comme modèle ;
- si l'expert a laissé une consigne, elle prime : elle désigne l'erreur
  à corriger ;
- réponds directement, en markdown, sans préambule ni commentaire sur ta
  démarche."""


class DraftingError(Exception):
    """The model could not produce a usable draft."""


@dataclass(frozen=True)
class PageImage:
    """One source page, rendered as an image."""

    doc_id: str
    page: int
    png: bytes


@runtime_checkable
class AnswerDrafter(Protocol):
    """Drafts a reference answer from source pages."""

    def draft(
        self,
        question: str,
        pages: list[PageImage],
        instruction: str | None,
        rejected_answer: str,
    ) -> str:
        """Draft the answer.

        Args:
            question: Question asked.
            pages: Ground truth pages, as images.
            instruction: What the business team said was wrong, if
                anything.
            rejected_answer: Answer judged non compliant.

        Returns:
            The draft, in markdown.

        Raises:
            DraftingError: If no usable draft could be produced.
        """
        ...


class OfflineDrafter:
    """Deterministic drafter that calls no model.

    It exists so that the whole regeneration and proofreading path can be
    tried in Kili — and tested — without an API key.
    """

    def draft(
        self,
        question: str,
        pages: list[PageImage],
        instruction: str | None,
        rejected_answer: str,
    ) -> str:
        """Return a placeholder draft listing what the model would see.

        Args:
            question: Question asked.
            pages: Ground truth pages, as images.
            instruction: What the business team said was wrong.
            rejected_answer: Answer judged non compliant (unused).

        Returns:
            The placeholder draft.
        """
        del rejected_answer
        listed = ", ".join(f"{p.doc_id} p. {p.page}" for p in pages)
        lines = [
            "**Brouillon factice (mode hors ligne)** : aucun modèle n'a "
            "été appelé.",
            "",
            f"Question : {question}",
            "",
            f"Pages qui auraient été transmises : {listed}.",
        ]
        if instruction:
            lines += ["", f"Consigne : {instruction}"]
        return "\n".join(lines)


class ClaudeDrafter:
    """Drafter backed by a Claude vision model."""

    def __init__(
        self,
        client: object,
        model: str,
        effort: str = "high",
        style: str | None = None,
        fallbacks: bool = True,
    ) -> None:
        """Initialize the drafter.

        Args:
            client: Configured `anthropic.Anthropic` client.
            model: Model identifier.
            effort: Reasoning effort, `low` to `max`.
            style: Formatting guidance of the production RAG prompt,
                appended to the system prompt so that drafts look like
                what the RAG is expected to produce.
            fallbacks: Whether a request the model declines is re-run
                server side on the recommended fallback model.
        """
        self._client = client
        self.model = model
        self.effort = effort
        self.fallbacks = fallbacks
        self.system = REGENERATION_SYSTEM_PROMPT
        if style and style.strip():
            self.system += (
                "\n\nConsignes de forme de l'assistant en production :\n"
                + style.strip()
            )

    def draft(
        self,
        question: str,
        pages: list[PageImage],
        instruction: str | None,
        rejected_answer: str,
    ) -> str:
        """Draft the answer by sending the pages to Claude.

        Args:
            question: Question asked.
            pages: Ground truth pages, as images.
            instruction: What the business team said was wrong.
            rejected_answer: Answer judged non compliant.

        Returns:
            The draft, in markdown.

        Raises:
            DraftingError: If the API fails, the model declines, or the
                draft is empty or truncated.
        """
        import anthropic

        content: list[dict] = []
        for page in pages:
            content.append(
                {
                    "type": "text",
                    "text": f"Document : {page.doc_id} — page {page.page}",
                }
            )
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.standard_b64encode(page.png).decode(
                            "ascii"
                        ),
                    },
                }
            )
        content.append(
            {
                "type": "text",
                "text": (
                    f"Question :\n{question}\n\n"
                    f"Réponse jugée non conforme :\n"
                    f"{rejected_answer or '(aucune)'}\n\n"
                    f"Consigne de l'expert :\n{instruction or '(aucune)'}"
                    "\n\nRédige la réponse de référence."
                ),
            }
        )
        options: dict = {}
        if self.fallbacks:
            options = {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        try:
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort},
                system=self.system,
                messages=[{"role": "user", "content": content}],
                **options,
            )
        except anthropic.APIError as error:
            raise DraftingError(f"erreur de l'API ({error})") from error

        if response.stop_reason == "refusal":
            raise DraftingError("le modèle a refusé de rédiger la réponse")
        if response.stop_reason == "max_tokens":
            raise DraftingError("le brouillon a été tronqué")
        text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
        if not text:
            raise DraftingError("le modèle n'a renvoyé aucun texte")
        return text


class RegenerationReport(BaseModel):
    """Summary of one regeneration run."""

    cases_read: int = 0
    drafts_created: int = 0
    failures: int = 0
    retries_pending: int = 0
    already_done: int = 0
    details: list[dict] = Field(default_factory=list)


def source_pages(
    sources: list[Source], page_counts: dict[str, int]
) -> list[tuple[str, int]]:
    """List the pages to send, in the order the sources give them.

    A source cited without a page stands for the whole document.

    Args:
        sources: Ground truth sources, known to exist.
        page_counts: Pages of each local document.

    Returns:
        Distinct `(doc_id, page)` pairs.
    """
    pages: list[tuple[str, int]] = []
    for source in sources:
        wanted = (
            [source.page]
            if source.page is not None
            else range(1, page_counts[source.doc_id] + 1)
        )
        for page in wanted:
            if (source.doc_id, page) not in pages:
                pages.append((source.doc_id, page))
    return pages


def _blocking_problem(
    sources: list[Source], page_counts: dict[str, int], max_pages: int
) -> str | None:
    """Find what prevents drafting for good, if anything.

    Args:
        sources: Ground truth sources.
        page_counts: Pages of each local document.
        max_pages: Maximum number of pages sent to the model.

    Returns:
        A sentence for the proofreader, or `None` when drafting can go on.
    """
    problems = check_sources_exist(sources, page_counts)
    if problems:
        return "sources introuvables (" + " ; ".join(problems) + ")."
    count = len(source_pages(sources, page_counts))
    if count > max_pages:
        return (
            f"{count} pages de sources, au-delà du plafond de {max_pages} "
            "(réglage REGENERATION_MAX_PAGES)."
        )
    return None


def _draft_case(
    arbitrated: ArbitratedCase,
    target: str,
    sources: list[Source],
    draft: str,
    error: str | None,
) -> ReviewCase:
    """Build the proofreading case of a regenerated answer.

    Args:
        arbitrated: Original case and its arbitration.
        target: `question_id` the arbitration settled on.
        sources: Ground truth sources the draft was written from.
        draft: The draft, empty when drafting failed.
        error: Why drafting failed, if it did.

    Returns:
        The case to import into project B.
    """
    case = arbitrated.case
    return ReviewCase(
        question_id=target,
        run_id=case.run_id,
        motif="RELECTURE_BROUILLON",
        question=case.question,
        candidate_answer=draft,
        sources=sources,
        cas_origine=arbitrated.external_id,
        consigne_correction=arbitrated.label.correction_instruction,
        reponse_rejetee=case.candidate_answer,
        erreur_regeneration=error,
    )


def regenerate_batch(
    kili: object,
    reference_project_id: str,
    review_project_id: str,
    store: DocumentStore,
    drafter: AnswerDrafter,
    settings: Settings,
) -> RegenerationReport:
    """Draft an answer for every case waiting in `A_REGENERER`.

    The operation is idempotent: the twin asset has a deterministic
    `external_id`, and the original case leaves `A_REGENERER` once it
    exists. A transient failure leaves the case in `A_REGENERER` for the
    next run, up to `regeneration_max_attempts`.

    Args:
        kili: Kili client.
        reference_project_id: Identifier of project A, read to show the
            validated wordings next to the draft.
        review_project_id: Identifier of project B.
        store: Local source documents.
        drafter: Model writing the drafts.
        settings: Runtime settings.

    Returns:
        The report of the run.
    """
    report = RegenerationReport()
    cases = read_arbitrated_cases(kili, review_project_id, "A_REGENERER")
    report.cases_read = len(cases)
    if not cases:
        return report

    entries = {
        entry.question_id: entry
        for entry in load_entries(kili, reference_project_id)
    }
    existing = {
        asset["externalId"]
        for asset in kili.assets(
            project_id=review_project_id, fields=["externalId"]
        )
    }
    page_counts = store.page_counts()

    for arbitrated in cases:
        external_id = arbitrated.external_id
        draft_id = external_id + DRAFT_SUFFIX
        cases_by_id = {external_id: arbitrated.case}
        if draft_id in existing:
            # Asset jumeau déjà créé par un passage interrompu avant la
            # mise à jour du cas d'origine : on termine le travail.
            set_review_status(
                kili, review_project_id, [external_id], "REGENERE",
                cases_by_id,
            )
            report.already_done += 1
            continue

        target = promotion_target(arbitrated)
        if target is None:
            continue
        sources = ground_truth_sources(arbitrated)
        draft = ""
        error = _blocking_problem(
            sources, page_counts, settings.regeneration_max_pages
        )
        if error is None:
            try:
                pages = [
                    PageImage(
                        doc_id,
                        page,
                        store.render_page(
                            doc_id, page, settings.regeneration_dpi
                        ),
                    )
                    for doc_id, page in source_pages(sources, page_counts)
                ]
                draft = drafter.draft(
                    arbitrated.case.question,
                    pages,
                    arbitrated.label.correction_instruction,
                    arbitrated.case.candidate_answer,
                )
            except DraftingError as failure:
                attempts = arbitrated.case.tentatives_regeneration + 1
                logger.warning(
                    "Rédaction impossible pour {} (tentative {}/{}) : {}",
                    external_id,
                    attempts,
                    settings.regeneration_max_attempts,
                    failure,
                )
                if attempts < settings.regeneration_max_attempts:
                    set_review_status(
                        kili,
                        review_project_id,
                        [external_id],
                        "A_REGENERER",
                        {
                            external_id: arbitrated.case.model_copy(
                                update={"tentatives_regeneration": attempts}
                            )
                        },
                    )
                    report.retries_pending += 1
                    continue
                error = f"échec après {attempts} tentatives ({failure})."

        draft_case = _draft_case(arbitrated, target, sources, draft, error)
        entry = entries.get(target)
        create_cases(
            kili,
            review_project_id,
            [draft_case],
            [draft_id],
            {target: entry.answers} if entry else {},
            {target: entry.question} if entry else {},
            settings,
        )
        if draft:
            kili.append_labels(
                project_id=review_project_id,
                asset_external_id_array=[draft_id],
                json_response_array=[{"VERSION_CORRIGEE": {"text": draft}}],
                label_type="PREDICTION",
                model_name=settings.regeneration_model,
            )
            report.drafts_created += 1
        else:
            report.failures += 1
        set_review_status(
            kili, review_project_id, [external_id], "REGENERE", cases_by_id
        )
        report.details.append(
            {
                "external_id": external_id,
                "relecture": draft_id,
                "brouillon": bool(draft),
                "erreur": error,
            }
        )
    return report
