"""From production to review: process a JSONL of occurrences.

Every occurrence is matched against the repository, possibly submitted to
the LLM-as-judge, and sent to business review when needed. **Nothing is
written into project A at this stage.**
"""

import argparse
import time
from datetime import UTC, datetime
from pathlib import Path

from _commun import read_jsonl, settings, write_json
from loguru import logger

from rag_referentiel.client import create_client
from rag_referentiel.config import Settings
from rag_referentiel.embeddings import JinaEmbeddings
from rag_referentiel.judge import AnswerJudge, ClaudeJudge, LexicalJudge
from rag_referentiel.matching import (
    HybridMatcher,
    LexicalMatcher,
    QuestionMatcher,
)
from rag_referentiel.normalisation import compute_question_id
from rag_referentiel.referentiel import load_entries
from rag_referentiel.revue import compute_external_ids, create_cases
from rag_referentiel.schemas import (
    ProductionOccurrence,
    ReferenceEntry,
    ReviewCase,
)


def build_matcher(
    entries: list[ReferenceEntry],
    config: Settings,
    offline: bool,
) -> QuestionMatcher:
    """Build the matcher, hybrid by default.

    Args:
        entries: `ACTIF` entries of the repository.
        config: Runtime settings.
        offline: When true, restrict to BM25, with no network call.

    Returns:
        The matcher to use.

    Raises:
        RuntimeError: If the Jina key is missing in hybrid mode.
    """
    if offline:
        return LexicalMatcher(
            entries, config.match_threshold_high, config.match_threshold_low
        )
    if not config.jina_api_key:
        raise RuntimeError(
            "JINA_API_KEY absente : utiliser --hors-ligne ou renseigner "
            "la clé."
        )
    backend = JinaEmbeddings(
        api_key=config.jina_api_key,
        model=config.embedding_model,
        base_url=config.jina_base_url,
    )
    backend.check_model_available()
    return HybridMatcher(
        entries,
        backend,
        config.match_threshold_high,
        config.match_threshold_low,
        config.lexical_weight,
        config.semantic_weight,
    )


def build_judge(config: Settings, offline: bool) -> AnswerJudge:
    """Build the judge, backed by Claude by default.

    Args:
        config: Runtime settings.
        offline: When true, use the deterministic lexical judge.

    Returns:
        The judge to use.

    Raises:
        RuntimeError: If the Anthropic key is missing in online mode.
    """
    if offline:
        return LexicalJudge(config.lexical_judge_threshold)
    if not config.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY absente : utiliser --hors-ligne ou "
            "renseigner la clé."
        )
    import anthropic

    return ClaudeJudge(
        client=anthropic.Anthropic(api_key=config.anthropic_api_key),
        model=config.judge_model,
        max_references=config.max_judge_references,
    )


def process(
    occurrences: list[dict],
    entries: list[ReferenceEntry],
    matcher: QuestionMatcher,
    judge: AnswerJudge,
) -> tuple[list[ReviewCase], dict]:
    """Match, judge and prepare the review cases.

    Args:
        occurrences: Lines of the production JSONL.
        entries: `ACTIF` entries of the repository.
        matcher: Question matcher.
        judge: LLM-as-judge.

    Returns:
        The pair (review cases to create, report fields).
    """
    by_id = {entry.question_id: entry for entry in entries}
    start = time.perf_counter()
    decisions = {"MATCH": 0, "INCERTAIN": 0, "NOUVELLE": 0}
    judged = 0
    compliant = 0
    skipped = 0
    cases: list[ReviewCase] = []
    sent: list[dict] = []

    for line in occurrences:
        occurrence = ProductionOccurrence.model_validate(line)
        try:
            question_id = compute_question_id(occurrence.question)
        except ValueError:
            logger.warning(
                "Occurrence {} sans question exploitable : ignorée.",
                occurrence.run_id,
            )
            skipped += 1
            continue

        result = matcher.match(occurrence.question)
        decisions[result.decision] += 1
        reason = None
        verdict = None
        target = question_id
        candidate = None

        if result.decision == "MATCH":
            entry = by_id[result.question_id]
            judged += 1
            verdict = judge.judge(
                occurrence.question,
                occurrence.answer_markdown,
                [answer.text for answer in entry.answers],
            )
            if verdict.conforme:
                compliant += 1
                continue
            reason = "DIVERGENCE"
            target = entry.question_id
        elif result.decision == "INCERTAIN":
            reason = "APPARIEMENT_INCERTAIN"
            candidate = result.question_id
        else:
            reason = "NOUVELLE_QUESTION"

        cases.append(
            ReviewCase(
                question_id=target,
                run_id=occurrence.run_id,
                motif=reason,
                question=occurrence.question,
                candidate_answer=occurrence.answer_markdown,
                sources=occurrence.sources,
                verdict_juge=verdict,
                score_appariement=result.score,
                question_id_candidat=candidate,
            )
        )
        sent.append(
            {
                "run_id": occurrence.run_id,
                "motif": reason,
                "question_id": target,
                "question_id_candidat": candidate,
                "score_appariement": result.score,
            }
        )

    elapsed = time.perf_counter() - start
    processed = len(occurrences) - skipped
    report = {
        "occurrences": len(occurrences),
        "ignorees": skipped,
        "decisions": decisions,
        "conformite": {
            "cas_juges": judged,
            "conformes": compliant,
            "taux": round(compliant / judged, 4) if judged else None,
        },
        "latence_secondes": {
            "total": round(elapsed, 3),
            "moyenne_par_occurrence": (
                round(elapsed / processed, 4) if processed else None
            ),
        },
        "cas_envoyes_en_revue": sent,
    }
    return cases, report


def main() -> None:
    """Entry point of the monitoring script."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--entree",
        dest="input_path",
        type=Path,
        default=Path("data/samples/run_prod.jsonl"),
        help="JSONL des occurrences de production.",
    )
    parser.add_argument(
        "--projet-referentiel",
        dest="reference_project",
        required=True,
        help="Projet A.",
    )
    parser.add_argument(
        "--projet-revue",
        dest="review_project",
        required=True,
        help="Projet B.",
    )
    parser.add_argument(
        "--rapport",
        dest="report_path",
        type=Path,
        default=None,
        help="Fichier du rapport JSON.",
    )
    parser.add_argument(
        "--hors-ligne",
        dest="offline",
        action="store_true",
        help="Matcher BM25 et juge lexical : aucun appel de modèle.",
    )
    arguments = parser.parse_args()

    config = settings()
    kili = create_client(config)
    entries = load_entries(
        kili, arguments.reference_project, statuses=("ACTIF",)
    )
    logger.info("{} entrées ACTIF chargées.", len(entries))

    cases, report = process(
        read_jsonl(arguments.input_path),
        entries,
        build_matcher(entries, config, arguments.offline),
        build_judge(config, arguments.offline),
    )

    external_ids = compute_external_ids(cases)
    for sent, external_id in zip(
        report["cas_envoyes_en_revue"], external_ids, strict=True
    ):
        sent["external_id"] = external_id
    create_cases(
        kili,
        arguments.review_project,
        cases,
        external_ids,
        {entry.question_id: entry.answers for entry in entries},
        {entry.question_id: entry.question for entry in entries},
        config.max_metadata_size,
    )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    write_json(
        arguments.report_path or Path(f"reports/monitoring_{stamp}.json"),
        {
            "horodatage": stamp,
            "projet_referentiel": arguments.reference_project,
            "projet_revue": arguments.review_project,
            "hors_ligne": arguments.offline,
            **report,
        },
    )


if __name__ == "__main__":
    main()
