"""Manually triggered recheck after documents evolve.

Documents move often, in minor ways: **no automatic invalidation**. This
script only reports the drift (`--rapport`), or puts the entries citing
the designated documents into recheck (`--declencher`). Going back to
`ACTIF` — or moving to `ARCHIVE` — happens through the
`ENTREE_TOUJOURS_VALIDE` job of project A, picked up by `promote.py`.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from _commun import settings, write_json
from loguru import logger

from rag_referentiel.client import create_client
from rag_referentiel.referentiel import load_entries, write_entry
from rag_referentiel.schemas import ReferenceEntry

RECHECK_PRIORITY = 10


def read_versions(path: Path) -> dict[str, str]:
    """Read the current versions of the documents.

    Args:
        path: JSON file mapping a `doc_id` to its `doc_version`.

    Returns:
        The current versions.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def parse_pages(text: str | None) -> tuple[int, int] | None:
    """Parse a page range such as `10-20`.

    Args:
        text: Range as typed, or `None`.

    Returns:
        The pair (first page, last page), or `None`.

    Raises:
        ValueError: If the range is malformed.
    """
    if not text:
        return None
    parts = text.split("-")
    if len(parts) != 2 or not all(p.strip().isdigit() for p in parts):
        raise ValueError(
            f"Intervalle de pages illisible : {text} (attendu « 10-20 »)."
        )
    first, last = (int(p) for p in parts)
    if first > last:
        raise ValueError(f"Intervalle de pages inversé : {text}.")
    return first, last


def drifting_entries(
    entries: list[ReferenceEntry], versions: dict[str, str]
) -> list[dict]:
    """List the entries whose source changed version.

    Args:
        entries: Repository entries.
        versions: Current versions of the documents.

    Returns:
        One record per affected entry, detailing the drifting sources.
    """
    report = []
    for entry in entries:
        drifts = [
            {
                "doc_id": source.doc_id,
                "page": source.page,
                "version_stockee": source.doc_version,
                "version_courante": versions[source.doc_id],
            }
            for source in entry.sources
            if source.doc_id in versions
            and source.doc_version != versions[source.doc_id]
        ]
        if drifts:
            report.append(
                {
                    "question_id": entry.question_id,
                    "question": entry.question,
                    "statut": entry.statut,
                    "sources_derivantes": drifts,
                }
            )
    return report


def impacted_entries(
    entries: list[ReferenceEntry],
    documents: list[str],
    pages: tuple[int, int] | None,
) -> list[ReferenceEntry]:
    """Select the entries citing the designated documents.

    A source without a page is kept as soon as its document is
    designated: the page range cannot rule it out.

    Args:
        entries: Repository entries.
        documents: Designated documents.
        pages: Page range, or `None` for the whole document.

    Returns:
        The impacted entries.
    """
    designated = set(documents)
    kept = []
    for entry in entries:
        for source in entry.sources:
            if source.doc_id not in designated:
                continue
            if (
                pages is not None
                and source.page is not None
                and not pages[0] <= source.page <= pages[1]
            ):
                continue
            kept.append(entry)
            break
    return kept


def trigger_recheck(
    kili: object,
    project_id: str,
    entries: list[ReferenceEntry],
    max_metadata_size: int,
) -> None:
    """Put entries into recheck and send them back to the queue.

    Args:
        kili: Kili client.
        project_id: Identifier of project A.
        entries: Entries to put into recheck.
        max_metadata_size: Metadata fallback threshold, in bytes.
    """
    external_ids = [entry.question_id for entry in entries]
    for entry in entries:
        entry.statut = "A_REVERIFIER"
        entry.version += 1
        write_entry(kili, project_id, entry, max_metadata_size)
    kili.update_properties_in_assets(
        project_id=project_id,
        external_ids=external_ids,
        priorities=[RECHECK_PRIORITY] * len(external_ids),
    )
    kili.send_back_to_queue(
        project_id=project_id, external_ids=external_ids
    )
    logger.info("{} entrées remises en file.", len(external_ids))


def main() -> None:
    """Entry point of the recheck script."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--projet-referentiel",
        dest="reference_project",
        required=True,
        help="Projet A.",
    )
    parser.add_argument(
        "--rapport",
        dest="report",
        action="store_true",
        help="Compare les versions stockées aux versions courantes.",
    )
    parser.add_argument(
        "--versions",
        dest="versions_path",
        type=Path,
        default=None,
        help="JSON { doc_id: doc_version } des versions courantes.",
    )
    parser.add_argument(
        "--declencher",
        dest="trigger",
        action="store_true",
        help="Passe les entrées visées en A_REVERIFIER.",
    )
    parser.add_argument(
        "--doc",
        dest="documents",
        action="append",
        default=[],
        help="Document concerné (répétable).",
    )
    parser.add_argument(
        "--pages",
        dest="pages",
        default=None,
        help="Intervalle de pages, ex. « 10-20 ».",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Affiche ce qui serait fait, sans rien modifier.",
    )
    parser.add_argument(
        "--sortie",
        dest="output_path",
        type=Path,
        default=None,
        help="Fichier du rapport de dérive.",
    )
    arguments = parser.parse_args()

    if not arguments.report and not arguments.trigger:
        parser.error("Choisir --rapport ou --declencher.")

    config = settings()
    kili = create_client(config)
    entries = load_entries(kili, arguments.reference_project)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    if arguments.report:
        if arguments.versions_path is None:
            parser.error("--rapport exige --versions.")
        drifts = drifting_entries(
            entries, read_versions(arguments.versions_path)
        )
        for item in drifts:
            logger.info(
                "Dérive : {} — {}", item["question_id"], item["question"]
            )
        write_json(
            arguments.output_path
            or Path(f"reports/derive_documentaire_{stamp}.json"),
            {
                "horodatage": stamp,
                "entrees_examinees": len(entries),
                "entrees_derivantes": drifts,
            },
        )

    if arguments.trigger:
        if not arguments.documents:
            parser.error("--declencher exige au moins un --doc.")
        impacted = impacted_entries(
            entries, arguments.documents, parse_pages(arguments.pages)
        )
        for entry in impacted:
            logger.info(
                "{} : {} — {}",
                "serait mise en revérification"
                if arguments.dry_run
                else "à revérifier",
                entry.question_id,
                entry.question,
            )
        if arguments.dry_run:
            logger.info(
                "--dry-run : {} entrées seraient modifiées, rien n'a été "
                "écrit.",
                len(impacted),
            )
            return
        trigger_recheck(
            kili,
            arguments.reference_project,
            impacted,
            config.max_metadata_size,
        )


if __name__ == "__main__":
    main()
