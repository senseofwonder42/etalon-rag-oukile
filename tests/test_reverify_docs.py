import json

import pytest
import reverify_docs

from rag_referentiel.config import Settings
from rag_referentiel.referentiel import (
    build_entry,
    create_project,
    import_entries,
    load_entries,
)
from rag_referentiel.schemas import Source

VERSIONS = {
    "cg_auto.pdf": "sha1:aaa",
    "cg_hab.pdf": "sha1:bbb",
}


@pytest.fixture
def settings():
    return Settings(kili_api_key="factice")


@pytest.fixture
def project(kili, settings):
    entries = [
        build_entry(
            "Délai de déclaration auto ?",
            ["Cinq jours."],
            [Source(doc_id="cg_auto.pdf", page=12, doc_version="sha1:aaa")],
            "c.durand",
            "2026-03-11",
        ),
        build_entry(
            "Résiliation habitation ?",
            ["Un mois de préavis."],
            [Source(doc_id="cg_hab.pdf", page=40, doc_version="sha1:vieux")],
            "c.durand",
            "2026-03-11",
        ),
        build_entry(
            "Vol de vélo ?",
            ["Couvert au domicile."],
            [Source(doc_id="cg_hab.pdf", doc_version="sha1:bbb")],
            "c.durand",
            "2026-03-11",
        ),
    ]
    project_id = create_project(kili, "Référentiel")
    import_entries(kili, project_id, entries, settings)
    return project_id, entries


def test_drifting_entries(project):
    _, entries = project
    drifts = reverify_docs.drifting_entries(entries, VERSIONS)
    assert len(drifts) == 1
    assert drifts[0]["question"] == "Résiliation habitation ?"
    assert drifts[0]["sources_derivantes"][0]["version_courante"] == (
        "sha1:bbb"
    )


def test_impacted_entries_by_document(project):
    _, entries = project
    impacted = reverify_docs.impacted_entries(entries, ["cg_hab.pdf"], None)
    assert {e.question for e in impacted} == {
        "Résiliation habitation ?",
        "Vol de vélo ?",
    }


def test_impacted_entries_by_page_range(project):
    _, entries = project
    impacted = reverify_docs.impacted_entries(
        entries, ["cg_hab.pdf"], (10, 20)
    )
    # La source sans page reste retenue, l'intervalle ne peut l'écarter.
    assert {e.question for e in impacted} == {"Vol de vélo ?"}


def test_parse_pages():
    assert reverify_docs.parse_pages("10-20") == (10, 20)
    assert reverify_docs.parse_pages(None) is None
    with pytest.raises(ValueError, match="illisible"):
        reverify_docs.parse_pages("dix-vingt")
    with pytest.raises(ValueError, match="inversé"):
        reverify_docs.parse_pages("20-10")


def _run_cli(monkeypatch, kili, settings, arguments):
    monkeypatch.setattr(reverify_docs, "settings", lambda: settings)
    monkeypatch.setattr(reverify_docs, "create_client", lambda _: kili)
    monkeypatch.setattr("sys.argv", ["reverify_docs.py", *arguments])
    reverify_docs.main()


def test_dry_run_changes_nothing(monkeypatch, kili, settings, project):
    project_id, _ = project
    before = [e.model_dump() for e in load_entries(kili, project_id)]

    _run_cli(
        monkeypatch,
        kili,
        settings,
        [
            "--projet-referentiel",
            project_id,
            "--declencher",
            "--doc",
            "cg_hab.pdf",
            "--dry-run",
        ],
    )

    assert [e.model_dump() for e in load_entries(kili, project_id)] == before
    assert kili.calls == []


def test_triggering_puts_entries_into_recheck(
    monkeypatch, kili, settings, project
):
    project_id, _ = project

    _run_cli(
        monkeypatch,
        kili,
        settings,
        [
            "--projet-referentiel",
            project_id,
            "--declencher",
            "--doc",
            "cg_hab.pdf",
        ],
    )

    by_question = {e.question: e for e in load_entries(kili, project_id)}
    assert by_question["Résiliation habitation ?"].statut == "A_REVERIFIER"
    assert by_question["Résiliation habitation ?"].version == 2
    assert by_question["Délai de déclaration auto ?"].statut == "ACTIF"
    assert kili.calls and kili.calls[0][0] == "send_back_to_queue"
    assert all(
        asset["priority"] == reverify_docs.RECHECK_PRIORITY
        for asset in kili.assets(project_id)
        if asset["jsonMetadata"]["statut"] == "A_REVERIFIER"
    )


def test_the_drift_report_writes_a_json_file(
    monkeypatch, kili, settings, project, tmp_path
):
    project_id, _ = project
    versions = tmp_path / "versions.json"
    versions.write_text(json.dumps(VERSIONS), encoding="utf-8")
    output = tmp_path / "derive.json"

    _run_cli(
        monkeypatch,
        kili,
        settings,
        [
            "--projet-referentiel",
            project_id,
            "--rapport",
            "--versions",
            str(versions),
            "--sortie",
            str(output),
        ],
    )

    content = json.loads(output.read_text(encoding="utf-8"))
    assert content["entrees_examinees"] == 3
    assert len(content["entrees_derivantes"]) == 1
