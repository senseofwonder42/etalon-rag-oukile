import importlib.util
import sys

import pytest
from deploy_plugin import build

from rag_referentiel.config import Settings
from rag_referentiel.referentiel import (
    build_entry,
    create_project,
    import_entries,
)
from rag_referentiel.revue import compute_external_ids, create_cases
from rag_referentiel.revue import create_project as create_review_project
from rag_referentiel.schemas import ReviewCase, Source

PAGE_COUNTS = {"cg_auto.pdf": 20, "guide.pdf": 3}


@pytest.fixture
def plugin_folder(tmp_path):
    return build(PAGE_COUNTS, tmp_path / "plugin")


@pytest.fixture
def handler_class(plugin_folder):
    """Load the plugin the way Kili would, from the assembled folder."""
    sys.path.insert(0, str(plugin_folder))
    try:
        spec = importlib.util.spec_from_file_location(
            "plugin_main", plugin_folder / "main.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module.PluginHandler
    finally:
        sys.path.remove(str(plugin_folder))
        sys.modules.pop("catalogue", None)


@pytest.fixture
def review(kili):
    settings = Settings(kili_api_key="factice")
    review_id = create_review_project(kili, "Revue")
    case = ReviewCase(
        question_id="q_1",
        run_id="run_42",
        motif="DIVERGENCE",
        question="Quel délai ?",
        candidate_answer="Trente jours.",
        sources=[Source(doc_id="cg_auto.pdf", page=12)],
    )
    external_id = compute_external_ids([case])[0]
    create_cases(kili, review_id, [case], [external_id], {}, {}, settings)
    return review_id, external_id


def submit(kili, project_id, external_id, sources, date="2026-07-18"):
    response = {"CANDIDATE_CORRECTE": {"categories": [{"name": "NON"}]}}
    if sources is not None:
        response["SOURCES_CORRIGEES"] = {"text": sources}
    kili.add_label(project_id, external_id, response, date=date)
    asset = kili.data[project_id][external_id]
    return asset["labels"][-1], asset["id"]


def test_the_assembled_folder_holds_only_what_kili_uploads(plugin_folder):
    files = sorted(
        str(path.relative_to(plugin_folder))
        for path in plugin_folder.rglob("*")
        if path.is_file()
    )
    assert files == [
        "catalogue.py",
        "main.py",
        "rag_referentiel/__init__.py",
        "rag_referentiel/schemas.py",
        "rag_referentiel/sources.py",
        "requirements.txt",
    ]
    catalogue = (plugin_folder / "catalogue.py").read_text()
    assert "'guide.pdf': 3," in catalogue


def test_wrong_sources_open_an_issue_and_block_the_case(
    kili, review, handler_class
):
    review_id, external_id = review
    label, asset_id = submit(kili, review_id, external_id, "guide.pdf:7")

    handler_class(kili, review_id).on_submit(label, asset_id)

    assert len(kili.issues) == 1
    assert "page 7 inexistante" in kili.issues[0]["text"]
    assert kili.issues[0]["label_id"] == label["id"]
    assert (
        kili.metadata(review_id, external_id)["statut_revue"]
        == "SOURCES_A_CORRIGER"
    )
    assert kili.calls == [("send_back_to_queue", (external_id,))]
    # Le reste de la metadata est conservé.
    assert kili.metadata(review_id, external_id)["question_id"] == "q_1"


def test_a_corrected_submission_releases_the_case(
    kili, review, handler_class
):
    review_id, external_id = review
    handler = handler_class(kili, review_id)
    handler.on_submit(*submit(kili, review_id, external_id, "guide.pdf:7"))

    handler.on_submit(
        *submit(kili, review_id, external_id, "guide.pdf:3", "2026-07-19")
    )

    assert len(kili.issues) == 1
    assert (
        kili.metadata(review_id, external_id)["statut_revue"] == "EN_ATTENTE"
    )


def test_valid_or_absent_sources_change_nothing(kili, review, handler_class):
    review_id, external_id = review
    handler = handler_class(kili, review_id)

    handler.on_submit(*submit(kili, review_id, external_id, "cg_auto.pdf:1"))
    handler.on_submit(*submit(kili, review_id, external_id, None))

    assert kili.issues == []
    assert kili.calls == []
    assert (
        kili.metadata(review_id, external_id)["statut_revue"] == "EN_ATTENTE"
    )


def test_on_the_reference_project_only_an_issue_is_raised(
    kili, handler_class
):
    settings = Settings(kili_api_key="factice")
    reference_id = create_project(kili, "Référentiel")
    entry = build_entry(
        question="Quel délai ?",
        texts=["Cinq jours."],
        sources=[],
        author="c.durand",
        date="2026-03-11",
    )
    import_entries(kili, reference_id, [entry], settings)
    before = dict(kili.metadata(reference_id, entry.question_id))
    label, asset_id = submit(
        kili, reference_id, entry.question_id, "absent.pdf:1"
    )

    handler_class(kili, reference_id).on_submit(label, asset_id)

    assert len(kili.issues) == 1
    assert "document inconnu" in kili.issues[0]["text"]
    assert kili.metadata(reference_id, entry.question_id) == before
