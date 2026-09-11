"""Project B — Revue prod RAG: creation and reading of the cases.

This project is the working queue of the business team: one asset is one
production occurrence to arbitrate. It never pollutes the reference
repository; only `promote.py` moves arbitrations over to project A.
"""

from loguru import logger
from pydantic import BaseModel

from .config import Settings
from .interfaces import REVIEW_INTERFACE
from .labels import (
    author_of,
    category,
    latest_label,
    load_metadata,
    transcription,
)
from .normalisation import compute_review_external_id
from .rendering import render_review_asset
from .schemas import Answer, ReviewCase, ReviewStatus
from .sources import display_metadata
from .storage import prepare_payload

CASE_FIELDS = [
    "externalId",
    "id",
    "jsonMetadata",
    "status",
    "labels.author.email",
    "labels.createdAt",
    "labels.jsonResponse",
    "labels.labelType",
]


class ReviewLabel(BaseModel):
    """Business arbitration read on a project B asset."""

    author: str
    date: str
    same_question: str | None = None
    candidate_correct: str | None = None
    corrected_version: str | None = None
    sources_relevant: str | None = None
    corrected_sources: str | None = None


class ArbitratedCase(BaseModel):
    """Review case together with its arbitration."""

    external_id: str
    case: ReviewCase
    label: ReviewLabel


def create_project(kili: object, title: str) -> str:
    """Create the Kili review project.

    Args:
        kili: Kili client.
        title: Project title.

    Returns:
        The identifier of the created project.
    """
    project = kili.create_project(
        title=title,
        input_type="TEXT",
        json_interface=REVIEW_INTERFACE,
        description=(
            "File de revue métier des occurrences de production du RAG."
        ),
    )
    logger.info("Projet de revue créé : {}", project["id"])
    return project["id"]


def compute_external_ids(cases: list[ReviewCase]) -> list[str]:
    """Assign a unique `external_id` to every case of a batch.

    Two occurrences of the same run matched to the same question would
    produce the same identifier: a suffix tells them apart, otherwise the
    SDK would silently drop the duplicate at import time.

    Args:
        cases: Review cases of the batch.

    Returns:
        The `external_id` values, in the order of the cases.
    """
    taken: set[str] = set()
    identifiers: list[str] = []
    for case in cases:
        base = compute_review_external_id(case.question_id, case.run_id)
        identifier = base
        suffix = 2
        while identifier in taken:
            identifier = f"{base}_{suffix}"
            suffix += 1
        taken.add(identifier)
        identifiers.append(identifier)
    return identifiers


def create_cases(
    kili: object,
    project_id: str,
    cases: list[ReviewCase],
    external_ids: list[str],
    answers_by_question: dict[str, list[Answer]],
    candidate_questions: dict[str, str],
    settings: Settings,
) -> list[str]:
    """Import review cases into project B.

    Args:
        kili: Kili client.
        project_id: Identifier of the review project.
        cases: Cases to create.
        external_ids: External ids of the assets, in the order of the
            cases (see `compute_external_ids`).
        answers_by_question: Validated wordings, by `question_id`, to
            display next to the candidate answer.
        candidate_questions: Question of every reference entry, by
            `question_id`. The card shows the one the case was matched
            to — the candidate entry on an uncertain match, the matched
            entry otherwise.
        settings: Runtime settings. The import being batched, the
            metadata fallback is decided on the measured size, without a
            retry after a server refusal.

    Returns:
        The `external_id` values of the created assets.
    """
    if not cases:
        return []

    contents: list[list[dict]] = []
    metadatas: list[dict] = []

    template = settings.document_url_template
    for case in cases:
        rendering = render_review_asset(
            case,
            answers_by_question.get(
                case.question_id_candidat or case.question_id, []
            ),
            candidate_questions.get(
                case.question_id_candidat or case.question_id
            ),
            template,
        )
        payload = prepare_payload(
            case.model_dump() | display_metadata(case.sources, template),
            rendering,
            settings.max_metadata_size,
        )
        contents.append(payload.json_content)
        metadatas.append(payload.json_metadata)

    kili.append_many_to_dataset(
        project_id=project_id,
        external_id_array=external_ids,
        json_content_array=contents,
        json_metadata_array=metadatas,
    )
    logger.info("{} cas de revue importés.", len(external_ids))
    return external_ids


def read_arbitrated_cases(
    kili: object, project_id: str
) -> list[ArbitratedCase]:
    """Read the pending cases that carry a business arbitration.

    Args:
        kili: Kili client.
        project_id: Identifier of the review project.

    Returns:
        The cases whose `statut_revue` is `EN_ATTENTE` and that carry at
        least one label.
    """
    assets = kili.assets(
        project_id=project_id,
        fields=CASE_FIELDS,
        metadata_where={"statut_revue": "EN_ATTENTE"},
    )
    result: list[ArbitratedCase] = []
    for asset in assets:
        metadata = load_metadata(asset.get("jsonMetadata"))
        if metadata.get("statut_revue") != "EN_ATTENTE":
            continue
        raw_label = latest_label(asset.get("labels") or [])
        if raw_label is None:
            continue
        try:
            case = ReviewCase.model_validate(metadata)
        except ValueError as error:
            logger.warning(
                "Cas de revue illisible ({}) : {}",
                asset.get("externalId"),
                error,
            )
            continue
        result.append(
            ArbitratedCase(
                external_id=asset["externalId"],
                case=case,
                label=_parse_label(raw_label),
            )
        )
    return result


def set_review_status(
    kili: object,
    project_id: str,
    external_ids: list[str],
    status: ReviewStatus,
    cases_by_external_id: dict[str, ReviewCase],
) -> None:
    """Update the `statut_revue` of project B assets.

    Args:
        kili: Kili client.
        project_id: Identifier of the review project.
        external_ids: Assets to update.
        status: New review status.
        cases_by_external_id: Matching cases, to rewrite a complete
            metadata.
    """
    if not external_ids:
        return
    metadatas = []
    for external_id in external_ids:
        case = cases_by_external_id[external_id].model_copy(
            update={"statut_revue": status}
        )
        metadatas.append(case.model_dump())
    kili.update_properties_in_assets(
        project_id=project_id,
        external_ids=external_ids,
        json_metadatas=metadatas,
    )
    logger.info("{} cas passés en {}.", len(external_ids), status)


def _parse_label(label: dict) -> ReviewLabel:
    """Translate a Kili label into a business arbitration.

    Args:
        label: Label returned by Kili.

    Returns:
        The matching arbitration.
    """
    response = label.get("jsonResponse") or {}
    return ReviewLabel(
        author=author_of(label),
        date=(label.get("createdAt") or "")[:10],
        same_question=category(response, "MEME_QUESTION"),
        candidate_correct=category(response, "CANDIDATE_CORRECTE"),
        corrected_version=transcription(response, "VERSION_CORRIGEE"),
        sources_relevant=category(response, "SOURCES_PERTINENTES"),
        corrected_sources=transcription(response, "SOURCES_CORRIGEES"),
    )
