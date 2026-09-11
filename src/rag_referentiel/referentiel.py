"""Project A — Référentiel RAG: reading, writing and enrichment.

One asset is one question. This is the source of truth: it is annotated
only when an entry is created and during recheck campaigns. Every write
coming from production goes through `promote_batch`.
"""

import json

from loguru import logger
from pydantic import BaseModel, Field

from .config import Settings
from .interfaces import REFERENCE_INTERFACE
from .labels import (
    author_of,
    categories,
    category,
    human_labels,
    load_metadata,
    transcription,
)
from .matching import lexical_similarity
from .normalisation import compute_question_id
from .rendering import render_reference_asset
from .revue import (
    ArbitratedCase,
    read_arbitrated_cases,
    set_review_status,
)
from .schemas import (
    Answer,
    Origin,
    ReferenceEntry,
    ReviewCase,
    Source,
    Status,
    today,
)
from .sources import parse_sources
from .storage import AssetPayload, prepare_payload, write_with_fallback

ENTRY_FIELDS = [
    "externalId",
    "id",
    "jsonMetadata",
    "status",
    "labels.author.email",
    "labels.createdAt",
    "labels.jsonResponse",
    "labels.labelType",
]

class UnknownAnswerMarkerError(ValueError):
    """The designated answer marker does not exist on the entry."""


class PromotionReport(BaseModel):
    """Summary of one promotion run."""

    cases_read: int = 0
    promoted: int = 0
    rejected: int = 0
    skipped: int = 0
    new_entries: int = 0
    variants_added: int = 0
    entries_updated: int = 0
    entries_revalidated: int = 0
    entries_archived: int = 0
    judge_business_disagreements: int = 0
    reference_labels_consumed: int = 0
    answers_replaced: int = 0
    answers_removed: int = 0
    unknown_markers: list[str] = Field(default_factory=list)
    unreadable_sources: list[str] = Field(default_factory=list)
    removed_sources: list[str] = Field(default_factory=list)
    details: list[dict] = Field(default_factory=list)


# --------------------------------------------------------------------- #
# Projet Kili
# --------------------------------------------------------------------- #
def create_project(kili: object, title: str) -> str:
    """Create the Kili reference project.

    Args:
        kili: Kili client.
        title: Project title.

    Returns:
        The identifier of the created project.
    """
    project = kili.create_project(
        title=title,
        input_type="TEXT",
        json_interface=REFERENCE_INTERFACE,
        description=(
            "Référentiel des questions et de leurs réponses validées."
        ),
    )
    logger.info("Projet de référentiel créé : {}", project["id"])
    return project["id"]


def import_entries(
    kili: object,
    project_id: str,
    entries: list[ReferenceEntry],
    max_metadata_size: int,
) -> list[str]:
    """Import brand new entries into the repository.

    Args:
        kili: Kili client.
        project_id: Identifier of project A.
        entries: Entries to create.
        max_metadata_size: Metadata fallback threshold, in bytes.

    Returns:
        The `external_id` values of the created assets.
    """
    if not entries:
        return []
    payloads = [
        prepare_payload(
            entry.model_dump(),
            render_reference_asset(entry),
            max_metadata_size,
        )
        for entry in entries
    ]
    external_ids = [entry.question_id for entry in entries]
    kili.append_many_to_dataset(
        project_id=project_id,
        external_id_array=external_ids,
        json_content_array=[p.json_content for p in payloads],
        json_metadata_array=[p.json_metadata for p in payloads],
    )
    logger.info("{} entrées importées au référentiel.", len(external_ids))
    return external_ids


def load_entries(
    kili: object,
    project_id: str,
    statuses: tuple[Status, ...] | None = None,
) -> list[ReferenceEntry]:
    """Load the entries of the repository.

    Args:
        kili: Kili client.
        project_id: Identifier of project A.
        statuses: Statuses to keep; all of them when `None`.

    Returns:
        The readable entries of the repository.
    """
    entries: list[ReferenceEntry] = []
    for asset in kili.assets(project_id=project_id, fields=ENTRY_FIELDS):
        metadata = load_metadata(asset.get("jsonMetadata"))
        if not metadata.get("question_id"):
            continue
        try:
            entry = ReferenceEntry.model_validate(metadata)
        except ValueError as error:
            logger.warning(
                "Entrée illisible ({}) : {}", asset.get("externalId"), error
            )
            continue
        if statuses is None or entry.statut in statuses:
            entries.append(entry)
    return entries


def write_entry(
    kili: object,
    project_id: str,
    entry: ReferenceEntry,
    max_metadata_size: int,
) -> None:
    """Refresh both the metadata and the rendering of an existing entry.

    Args:
        kili: Kili client.
        project_id: Identifier of project A.
        entry: Entry to write, with its version already bumped.
        max_metadata_size: Metadata fallback threshold, in bytes.
    """

    def write(payload: AssetPayload) -> None:
        kili.update_properties_in_assets(
            project_id=project_id,
            external_ids=[entry.question_id],
            json_metadatas=[payload.json_metadata],
            json_contents=[
                json.dumps(payload.json_content, ensure_ascii=False)
            ],
        )

    write_with_fallback(
        write,
        entry.model_dump(),
        render_reference_asset(entry),
        max_metadata_size,
    )


def append_audit_label(
    kili: object, project_id: str, question_id: str, text: str
) -> None:
    """Write the audit trail of a wording into project A.

    The metadata carries the aggregated state; this label carries the
    addition, timestamped by Kili. The label author is the API key doing
    the write; the business user who actually arbitrated is kept in
    `answers[].auteur`.

    The label type is `INFERENCE`: it is written by an automation and
    must not be read back as a human arbitration — otherwise every run of
    `promote.py` would replay the wordings already recorded.

    Args:
        kili: Kili client.
        project_id: Identifier of project A.
        question_id: Entry concerned.
        text: Wording that was added.
    """
    kili.append_labels(
        project_id=project_id,
        asset_external_id_array=[question_id],
        json_response_array=[{"REPONSE_VALIDEE": {"text": text}}],
        label_type="INFERENCE",
    )


# --------------------------------------------------------------------- #
# Règles pures : formulations et sources
# --------------------------------------------------------------------- #
def renumber_answers(entry: ReferenceEntry) -> None:
    """Renumber the wordings as `a1`, `a2`, … in their current order.

    Markers are the categories of the `FORMULATION_CIBLE` job of project
    A: they must stay within the `a1`–`a5` range set by the variant cap,
    with no hole after a removal.

    Args:
        entry: Entry to renumber, modified in place.
    """
    for number, answer in enumerate(entry.answers, start=1):
        answer.id = f"a{number}"


def select_variants(answers: list[Answer], cap: int) -> list[Answer]:
    """Keep the wordings that are the most diverse from one another.

    The first wording of business origin is always kept: it prevails. The
    next ones are picked greedily, maximizing the minimum distance to the
    already selected wordings.

    Args:
        answers: Candidate wordings.
        cap: Maximum number of wordings to keep.

    Returns:
        The selected wordings, in their original order.
    """
    if len(answers) <= cap:
        return list(answers)

    business = next(
        (a for a in answers if a.origine == "metier"), answers[0]
    )
    kept = [business]
    remaining = [a for a in answers if a.id != business.id]
    while len(kept) < cap and remaining:
        following = max(
            remaining,
            key=lambda candidate: min(
                1.0 - lexical_similarity(candidate.text, selected.text)
                for selected in kept
            ),
        )
        kept.append(following)
        remaining = [a for a in remaining if a.id != following.id]
    identifiers = {a.id for a in kept}
    return [a for a in answers if a.id in identifiers]


def add_variant(
    entry: ReferenceEntry,
    text: str,
    origin: Origin,
    author: str,
    date: str,
    run_id: str | None,
    near_duplicate_threshold: float,
    cap: int,
) -> bool:
    """Add a wording to an entry, when it brings something.

    A variant too close to an existing wording is discarded. Beyond the
    cap, only the most diverse wordings are kept.

    Args:
        entry: Entry to enrich, modified in place.
        text: Wording to add.
        origin: Provenance of the wording.
        author: Business user who arbitrated the wording.
        date: Arbitration date, in ISO format.
        run_id: Originating production occurrence, when there is one.
        near_duplicate_threshold: Similarity above which the variant is
            considered a duplicate.
        cap: Maximum number of wordings kept.

    Returns:
        `True` when the list of wordings changed.
    """
    text = (text or "").strip()
    if not text:
        return False
    if entry.repli_texte:
        logger.error(
            "Entrée {} repliée (textes absents de la metadata) : ajout de "
            "variante refusé pour ne pas dédoublonner à l'aveugle.",
            entry.question_id,
        )
        return False
    for answer in entry.answers:
        if lexical_similarity(answer.text, text) >= near_duplicate_threshold:
            logger.info(
                "Variante écartée (quasi-doublon de {}) sur {}.",
                answer.id,
                entry.question_id,
            )
            return False

    before = [answer.text for answer in entry.answers]
    entry.answers.append(
        Answer(
            id=f"a{len(entry.answers) + 1}",
            text=text,
            origine=origin,
            auteur=author,
            date=date,
            run_id=run_id,
        )
    )
    entry.answers = select_variants(entry.answers, cap)
    renumber_answers(entry)
    return [answer.text for answer in entry.answers] != before


def replace_answer(
    entry: ReferenceEntry,
    marker: str,
    text: str,
    author: str,
    date: str,
    near_duplicate_threshold: float,
) -> bool:
    """Replace the text of the wording designated by its marker.

    The marker and the position of the wording are preserved; the origin
    goes back to `metier` and the `run_id` is cleared, the wording no
    longer being the one produced by the RAG.

    Args:
        entry: Entry to fix, modified in place.
        marker: Marker of the wording, `a1` to `a5`.
        text: Corrected text.
        author: Business user who corrected it.
        date: Correction date, in ISO format.
        near_duplicate_threshold: Similarity above which the correction
            is reported as redundant with another wording. It is applied
            all the same: this is an explicit business arbitration.

    Returns:
        `True` when the text changed.

    Raises:
        UnknownAnswerMarkerError: If no wording carries that marker.
    """
    text = (text or "").strip()
    if not text:
        return False
    if entry.repli_texte:
        logger.error(
            "Entrée {} repliée : remplacement refusé, les textes ne sont "
            "pas lisibles en metadata.",
            entry.question_id,
        )
        return False

    found = next((a for a in entry.answers if a.id == marker), None)
    if found is None:
        raise UnknownAnswerMarkerError(
            f"L'entrée {entry.question_id} n'a pas de formulation "
            f"« {marker} » (repères existants : "
            f"{', '.join(a.id for a in entry.answers) or 'aucun'})."
        )
    if found.text.strip() == text:
        return False

    for other in entry.answers:
        if other.id == marker:
            continue
        if lexical_similarity(other.text, text) >= near_duplicate_threshold:
            logger.warning(
                "La correction de {} sur {} est très proche de {} : les "
                "deux formulations sont conservées.",
                marker,
                entry.question_id,
                other.id,
            )

    found.text = text
    found.origine = "metier"
    found.auteur = author
    found.date = date
    found.run_id = None
    return True


def remove_answers(
    entry: ReferenceEntry, markers: list[str]
) -> tuple[list[str], list[str]]:
    """Remove the designated wordings from the repository.

    Args:
        entry: Entry to fix, modified in place.
        markers: Markers of the wordings to remove.

    Returns:
        The pair (removed texts, unknown markers). The last wording of an
        entry is never removed: an entry without an answer would be
        useless.
    """
    unknown = [
        marker
        for marker in markers
        if not any(a.id == marker for a in entry.answers)
    ]
    to_remove = set(markers) - set(unknown)
    if not to_remove:
        return [], unknown

    remaining = [a for a in entry.answers if a.id not in to_remove]
    if not remaining:
        logger.warning(
            "Retrait refusé sur {} : il ne resterait aucune formulation.",
            entry.question_id,
        )
        return [], unknown

    removed = [a.text for a in entry.answers if a.id in to_remove]
    entry.answers = remaining
    renumber_answers(entry)
    return removed, unknown


def merge_sources(
    entry: ReferenceEntry, new_sources: list[Source]
) -> bool:
    """Add sources that are missing from the entry.

    Args:
        entry: Entry to complete, modified in place.
        new_sources: Sources to add.

    Returns:
        `True` when the source list changed.
    """
    known = {(source.doc_id, source.page) for source in entry.sources}
    added = False
    for source in new_sources:
        if (source.doc_id, source.page) in known:
            continue
        entry.sources.append(source)
        known.add((source.doc_id, source.page))
        added = True
    return added


def replace_sources(
    entry: ReferenceEntry, new_sources: list[Source]
) -> bool:
    """Replace the sources of an entry with a corrected list.

    Known `doc_version` values are carried over to corrected sources
    citing the same document: the annotator only types `doc.pdf:page`.

    Args:
        entry: Entry to fix, modified in place.
        new_sources: Corrected sources.

    Returns:
        `True` when the source list changed.
    """
    versions = {
        source.doc_id: source.doc_version
        for source in entry.sources
        if source.doc_version
    }
    corrected = [
        source.model_copy(
            update={"doc_version": versions.get(source.doc_id)}
        )
        for source in new_sources
    ]
    if [s.model_dump() for s in corrected] == [
        s.model_dump() for s in entry.sources
    ]:
        return False
    entry.sources = corrected
    return True


def build_entry(
    question: str,
    texts: list[str],
    sources: list[Source],
    author: str,
    date: str,
    origin: Origin = "metier",
    run_id: str | None = None,
) -> ReferenceEntry:
    """Build a brand new repository entry.

    Args:
        question: Question, as asked.
        texts: Validated wordings, in order.
        sources: Cited sources.
        author: Business user behind the entry.
        date: Creation date, in ISO format.
        origin: Provenance of the wordings.
        run_id: Originating production occurrence, when there is one.

    Returns:
        The entry, ready to be imported.
    """
    answers = [
        Answer(
            id=f"a{index}",
            text=text,
            origine=origin,
            auteur=author,
            date=date,
            run_id=run_id,
        )
        for index, text in enumerate(texts, start=1)
        if text.strip()
    ]
    return ReferenceEntry(
        question_id=compute_question_id(question),
        question=question,
        answers=answers,
        sources=sources,
        derniere_verification=date,
    )


# --------------------------------------------------------------------- #
# Promotion : de la revue vers le référentiel
# --------------------------------------------------------------------- #
def _promotion_target(arbitrated: ArbitratedCase) -> str | None:
    """Determine which repository entry an arbitration targets.

    Args:
        arbitrated: Review case and its arbitration.

    Returns:
        The targeted `question_id`, or `None` when the arbitration does
        not settle it — typically an uncertain case whose `MEME_QUESTION`
        job was left empty.
    """
    case, label = arbitrated.case, arbitrated.label
    if case.motif != "APPARIEMENT_INCERTAIN":
        return case.question_id
    if label.same_question == "OUI":
        return case.question_id_candidat or case.question_id
    if label.same_question == "NON":
        return case.question_id
    logger.warning(
        "Cas incertain {} sans réponse à MEME_QUESTION : laissé en attente.",
        arbitrated.external_id,
    )
    return None


def _text_to_promote(arbitrated: ArbitratedCase) -> tuple[str | None, Origin]:
    """Determine the wording to push into the repository.

    Args:
        arbitrated: Review case and its arbitration.

    Returns:
        The pair (text to push or `None`, origin to record).
    """
    label = arbitrated.label
    if label.candidate_correct == "OUI":
        return arbitrated.case.candidate_answer, "rag_valide"
    if label.candidate_correct == "PRESQUE":
        if label.corrected_version:
            return label.corrected_version, "rag_corrige"
        logger.warning(
            "Cas {} arbitré « PRESQUE » sans version corrigée : rien n'est "
            "versé au référentiel.",
            arbitrated.external_id,
        )
    return None, "rag_valide"


def _update_sources(
    entry: ReferenceEntry,
    arbitrated: ArbitratedCase,
    report: PromotionReport,
) -> bool:
    """Apply the source corrections of an arbitration.

    Args:
        entry: Entry to update, modified in place.
        arbitrated: Review case and its arbitration.
        report: Report to complete with the unreadable fragments.

    Returns:
        `True` when the sources changed.
    """
    label = arbitrated.label
    if label.corrected_sources:
        sources, unreadable = parse_sources(label.corrected_sources)
        report.unreadable_sources.extend(
            f"{arbitrated.external_id} : {fragment}"
            for fragment in unreadable
        )
        if sources:
            return replace_sources(entry, sources)
        return False
    if label.sources_relevant == "OUI":
        return merge_sources(entry, arbitrated.case.sources)
    return False


def _judge_business_disagreement(arbitrated: ArbitratedCase) -> bool:
    """Tell whether the business team contradicted the LLM-as-judge.

    Args:
        arbitrated: Review case and its arbitration.

    Returns:
        `True` when a judge verdict exists and diverges from the business
        arbitration (`OUI` means compliant, `NON` non compliant;
        `PRESQUE` counts as a disagreement with a judge saying
        « compliant »).
    """
    verdict = arbitrated.case.verdict_juge
    if verdict is None or arbitrated.label.candidate_correct is None:
        return False
    business_compliant = arbitrated.label.candidate_correct == "OUI"
    return verdict.conforme != business_compliant


def promote_batch(
    kili: object,
    reference_project_id: str,
    review_project_id: str,
    settings: Settings,
) -> PromotionReport:
    """Move the arbitrations of project B into project A.

    The operation is idempotent: a processed case is no longer
    `EN_ATTENTE`, a wording already present is discarded as a near
    duplicate, and `version` is bumped only when the state changes.

    Args:
        kili: Kili client.
        reference_project_id: Identifier of project A.
        review_project_id: Identifier of project B.
        settings: Runtime settings.

    Returns:
        The report of the run.
    """
    report = PromotionReport()
    entries = {
        entry.question_id: entry
        for entry in load_entries(kili, reference_project_id)
    }
    apply_reference_labels(
        kili, reference_project_id, entries, settings, report
    )

    arbitrated_cases = read_arbitrated_cases(kili, review_project_id)
    report.cases_read = len(arbitrated_cases)
    promoted: list[str] = []
    rejected: list[str] = []
    cases_by_id: dict[str, ReviewCase] = {}

    for arbitrated in arbitrated_cases:
        cases_by_id[arbitrated.external_id] = arbitrated.case
        question_id = _promotion_target(arbitrated)
        if question_id is None:
            report.skipped += 1
            continue

        text, origin = _text_to_promote(arbitrated)
        date = arbitrated.label.date or today()
        if _judge_business_disagreement(arbitrated):
            report.judge_business_disagreements += 1

        if question_id not in entries:
            if text is None:
                rejected.append(arbitrated.external_id)
                report.rejected += 1
                continue
            entry = build_entry(
                question=arbitrated.case.question,
                texts=[text],
                sources=list(arbitrated.case.sources),
                author=arbitrated.label.author,
                date=date,
                origin=origin,
                run_id=arbitrated.case.run_id,
            )
            _update_sources(entry, arbitrated, report)
            import_entries(
                kili,
                reference_project_id,
                [entry],
                settings.max_metadata_size,
            )
            append_audit_label(
                kili, reference_project_id, entry.question_id, text
            )
            entries[entry.question_id] = entry
            report.new_entries += 1
            report.variants_added += 1
            promoted.append(arbitrated.external_id)
            report.promoted += 1
            report.details.append(
                {
                    "external_id": arbitrated.external_id,
                    "action": "nouvelle_entree",
                    "question_id": entry.question_id,
                }
            )
            continue

        entry = entries[question_id]
        variant_added = False
        if text is not None:
            variant_added = add_variant(
                entry,
                text=text,
                origin=origin,
                author=arbitrated.label.author,
                date=date,
                run_id=arbitrated.case.run_id,
                near_duplicate_threshold=settings.near_duplicate_threshold,
                cap=settings.variant_cap,
            )
        sources_changed = _update_sources(entry, arbitrated, report)

        if variant_added or sources_changed:
            entry.version += 1
            entry.derniere_verification = date
            write_entry(
                kili,
                reference_project_id,
                entry,
                settings.max_metadata_size,
            )
            report.entries_updated += 1
            if variant_added:
                report.variants_added += 1
                append_audit_label(
                    kili,
                    reference_project_id,
                    entry.question_id,
                    text or "",
                )

        if text is None:
            rejected.append(arbitrated.external_id)
            report.rejected += 1
        else:
            promoted.append(arbitrated.external_id)
            report.promoted += 1
        report.details.append(
            {
                "external_id": arbitrated.external_id,
                "action": "variante" if variant_added else "sans_effet",
                "question_id": entry.question_id,
            }
        )

    set_review_status(
        kili, review_project_id, promoted, "PROMU", cases_by_id
    )
    set_review_status(
        kili, review_project_id, rejected, "REJETE", cases_by_id
    )
    return report


def _apply_label(
    entry: ReferenceEntry,
    label: dict,
    settings: Settings,
    report: PromotionReport,
) -> bool:
    """Apply one project A arbitration to an entry.

    Args:
        entry: Entry to update, modified in place.
        label: Human label returned by Kili.
        settings: Runtime settings.
        report: Report to complete.

    Returns:
        `True` when the entry changed.
    """
    response = label.get("jsonResponse") or {}
    author = author_of(label)
    date = (label.get("createdAt") or "")[:10] or today()
    changed = False

    still_valid = category(response, "ENTREE_TOUJOURS_VALIDE")
    if still_valid == "OUI" and (
        entry.statut != "ACTIF" or entry.derniere_verification != date
    ):
        entry.statut = "ACTIF"
        entry.derniere_verification = date
        report.entries_revalidated += 1
        changed = True
    elif still_valid == "NON" and entry.statut != "ARCHIVE":
        entry.statut = "ARCHIVE"
        entry.derniere_verification = date
        report.entries_archived += 1
        changed = True

    text = transcription(response, "REPONSE_VALIDEE")
    marker = category(response, "FORMULATION_CIBLE")
    if text and marker:
        try:
            if replace_answer(
                entry,
                marker=marker,
                text=text,
                author=author,
                date=date,
                near_duplicate_threshold=settings.near_duplicate_threshold,
            ):
                report.answers_replaced += 1
                changed = True
        except UnknownAnswerMarkerError as error:
            logger.warning("{}", error)
            report.unknown_markers.append(str(error))
    elif text and add_variant(
        entry,
        text=text,
        origin="metier",
        author=author,
        date=date,
        run_id=None,
        near_duplicate_threshold=settings.near_duplicate_threshold,
        cap=settings.variant_cap,
    ):
        report.variants_added += 1
        changed = True
    elif marker and not text:
        logger.warning(
            "Repère {} désigné sur {} sans texte de remplacement : ignoré.",
            marker,
            entry.question_id,
        )

    to_remove = categories(response, "FORMULATIONS_A_RETIRER")
    if to_remove:
        removed, unknown = remove_answers(entry, to_remove)
        report.answers_removed += len(removed)
        report.unknown_markers.extend(
            f"{entry.question_id} : repère {marker} introuvable"
            for marker in unknown
        )
        changed = changed or bool(removed)

    sources_text = transcription(response, "SOURCES_CORRIGEES")
    if sources_text:
        sources, unreadable = parse_sources(sources_text)
        report.unreadable_sources.extend(
            f"{entry.question_id} : {fragment}" for fragment in unreadable
        )
        if sources:
            dropped = {
                (s.doc_id, s.page) for s in entry.sources
            } - {(s.doc_id, s.page) for s in sources}
            if replace_sources(entry, sources):
                changed = True
            for doc_id, page in sorted(dropped):
                logger.info(
                    "Source retirée de {} par correction : {}:{}",
                    entry.question_id,
                    doc_id,
                    page,
                )
                report.removed_sources.append(
                    f"{entry.question_id} : {doc_id}:{page}"
                )
    return changed


def apply_reference_labels(
    kili: object,
    project_id: str,
    entries: dict[str, ReferenceEntry],
    settings: Settings,
    report: PromotionReport,
) -> None:
    """Apply the arbitrations carried by the project A assets.

    Every human label created **since the `derniere_promotion`
    watermark** is applied, oldest first: a business user correcting two
    wordings saves twice, and both corrections are taken. The watermark
    is then moved forward, which makes the operation idempotent without
    relying on state comparison.

    Args:
        kili: Kili client.
        project_id: Identifier of project A.
        entries: Repository entries, by `question_id`, modified in place.
        settings: Runtime settings.
        report: Report to complete.
    """
    for asset in kili.assets(project_id=project_id, fields=ENTRY_FIELDS):
        metadata = load_metadata(asset.get("jsonMetadata"))
        entry = entries.get(metadata.get("question_id", ""))
        if entry is None:
            continue

        watermark = entry.derniere_promotion or ""
        pending = [
            label
            for label in human_labels(asset.get("labels") or [])
            if (label.get("createdAt") or "") > watermark
        ]
        if not pending:
            continue

        changed = False
        for label in pending:
            changed = _apply_label(entry, label, settings, report) or changed
        report.reference_labels_consumed += len(pending)

        if changed:
            entry.version += 1
        entry.derniere_promotion = pending[-1].get("createdAt") or ""
        write_entry(kili, project_id, entry, settings.max_metadata_size)
