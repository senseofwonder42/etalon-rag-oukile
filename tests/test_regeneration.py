import unicodedata
from types import SimpleNamespace

import pymupdf
import pytest

from rag_referentiel.config import Settings
from rag_referentiel.documents import DocumentStore
from rag_referentiel.referentiel import (
    build_entry,
    create_project,
    import_entries,
    load_entries,
    promote_batch,
)
from rag_referentiel.regeneration import (
    FALLBACK_BETA,
    ClaudeDrafter,
    DraftingError,
    OfflineDrafter,
    PageImage,
    regenerate_batch,
    source_pages,
)
from rag_referentiel.rendering import render_draft_review_asset
from rag_referentiel.revue import compute_external_ids, create_cases
from rag_referentiel.revue import create_project as create_review_project
from rag_referentiel.schemas import ReviewCase, Source, Verdict
from rag_referentiel.sources import check_sources_exist, source_list_problems

QUESTION = "Quel est le délai de déclaration d'un sinistre auto ?"
BUSINESS_ANSWER = "Le délai est de cinq jours ouvrés après le sinistre."
MRH = "DCON_ConditionsGénérales_MRH_202605.pdf"
PAGE_COUNTS = {"cg_auto.pdf": 20, "guide.pdf": 3, MRH: 64}


def write_pdf(path, pages):
    pdf = pymupdf.open()
    for number in range(1, pages + 1):
        pdf.new_page().insert_text((72, 72), f"{path.name} page {number}")
    pdf.save(path)
    pdf.close()


@pytest.fixture
def documents(tmp_path):
    folder = tmp_path / "documents"
    folder.mkdir()
    write_pdf(folder / "cg_auto.pdf", 20)
    write_pdf(folder / "guide.pdf", 3)
    return DocumentStore(folder)


@pytest.fixture
def settings():
    return Settings(
        kili_api_key="factice",
        near_duplicate_threshold=0.85,
        variant_cap=5,
        regeneration_dpi=50,
        regeneration_max_pages=5,
        regeneration_max_attempts=2,
    )


@pytest.fixture
def projects(kili, settings):
    reference_id = create_project(kili, "Référentiel")
    entry = build_entry(
        question=QUESTION,
        texts=[BUSINESS_ANSWER],
        sources=[Source(doc_id="cg_auto.pdf", page=12)],
        author="c.durand",
        date="2026-03-11",
    )
    import_entries(kili, reference_id, [entry], settings)
    review_id = create_review_project(kili, "Revue")
    return reference_id, review_id, entry.question_id


def submit_case(kili, review_id, settings, **overrides):
    case = ReviewCase(
        **{
            "question_id": overrides.pop("question_id"),
            "run_id": "run_42",
            "motif": "DIVERGENCE",
            "question": QUESTION,
            "candidate_answer": "Vous avez trente jours.",
            "sources": [Source(doc_id="cg_auto.pdf", page=12)],
            "verdict_juge": Verdict(
                conforme=False, confiance=0.4, motif="test"
            ),
            **overrides,
        }
    )
    identifiers = compute_external_ids([case])
    create_cases(kili, review_id, [case], identifiers, {}, {}, settings)
    return identifiers[0]


def arbitrate(kili, review_id, external_id, verdict, **jobs):
    response = {
        "CANDIDATE_CORRECTE": {"categories": [{"name": verdict}]},
        "SOURCES_PERTINENTES": {
            "categories": [{"name": jobs.pop("pertinentes", "OUI")}]
        },
    }
    for job, text in jobs.items():
        response[job] = {"text": text}
    kili.add_label(review_id, external_id, response)


class FailingDrafter:
    def __init__(self):
        self.calls = 0

    def draft(self, question, pages, instruction, rejected_answer):
        self.calls += 1
        raise DraftingError("service indisponible")


# --------------------------------------------------------------------- #
# Vérification des sources
# --------------------------------------------------------------------- #
def test_an_existing_source_raises_no_problem():
    sources = [Source(doc_id="cg_auto.pdf", page=20), Source(doc_id=MRH)]
    assert check_sources_exist(sources, PAGE_COUNTS) == []


def test_an_unknown_document_is_reported_with_a_suggestion():
    problems = check_sources_exist(
        [Source(doc_id="cg_autos.pdf", page=2)], PAGE_COUNTS
    )
    assert len(problems) == 1
    assert "document inconnu" in problems[0]
    assert "cg_auto.pdf" in problems[0]


def test_a_page_beyond_the_document_is_reported():
    problems = check_sources_exist(
        [Source(doc_id="guide.pdf", page=4)], PAGE_COUNTS
    )
    assert problems == [
        "page 4 inexistante : « guide.pdf » compte 3 pages"
    ]


def test_a_decomposed_document_name_matches_its_file():
    decomposed = unicodedata.normalize("NFD", MRH)
    assert check_sources_exist([Source(doc_id=decomposed, page=1)], {
        decomposed: 64
    }) == []


def test_unreadable_fragments_count_as_problems():
    problems = source_list_problems("cg_auto.pdf:12 abc", PAGE_COUNTS)
    assert problems == ["saisie illisible : « cg_auto.pdf:abc »"]


# --------------------------------------------------------------------- #
# Documents locaux
# --------------------------------------------------------------------- #
def test_the_store_counts_the_pages_of_each_document(documents):
    assert documents.page_counts() == {"cg_auto.pdf": 20, "guide.pdf": 3}


def test_a_page_is_rendered_as_png(documents):
    image = documents.render_page("guide.pdf", 2, dpi=50)
    assert image.startswith(b"\x89PNG")


def test_a_missing_page_cannot_be_rendered(documents):
    with pytest.raises(ValueError):
        documents.render_page("guide.pdf", 9, dpi=50)


def test_a_missing_directory_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError):
        DocumentStore(tmp_path / "absent")


def test_a_source_without_page_stands_for_the_whole_document():
    pages = source_pages(
        [Source(doc_id="guide.pdf"), Source(doc_id="guide.pdf", page=2)],
        PAGE_COUNTS,
    )
    assert pages == [("guide.pdf", 1), ("guide.pdf", 2), ("guide.pdf", 3)]


# --------------------------------------------------------------------- #
# Promotion : envoi en régénération
# --------------------------------------------------------------------- #
def test_no_without_a_correction_but_with_sources_goes_to_regeneration(
    kili, settings, projects
):
    reference_id, review_id, question_id = projects
    external_id = submit_case(
        kili, review_id, settings, question_id=question_id
    )
    arbitrate(kili, review_id, external_id, "NON")

    report = promote_batch(kili, reference_id, review_id, settings)

    assert report.sent_to_regeneration == 1
    assert report.rejected == 0
    assert (
        kili.metadata(review_id, external_id)["statut_revue"]
        == "A_REGENERER"
    )
    assert len(load_entries(kili, reference_id)[0].answers) == 1


def test_corrected_sources_are_applied_before_regeneration(
    kili, settings, projects
):
    reference_id, review_id, question_id = projects
    external_id = submit_case(
        kili, review_id, settings, question_id=question_id
    )
    arbitrate(
        kili,
        review_id,
        external_id,
        "PRESQUE",
        pertinentes="NON",
        SOURCES_CORRIGEES="guide.pdf:2",
    )

    report = promote_batch(kili, reference_id, review_id, settings)

    assert report.sent_to_regeneration == 1
    entry = load_entries(kili, reference_id)[0]
    assert [s.label() for s in entry.sources] == ["guide.pdf:2"]


def test_invalid_sources_block_the_case_until_corrected(
    kili, settings, projects
):
    reference_id, review_id, question_id = projects
    external_id = submit_case(
        kili, review_id, settings, question_id=question_id
    )
    arbitrate(
        kili,
        review_id,
        external_id,
        "NON",
        SOURCES_CORRIGEES="guide.pdf:9",
    )

    report = promote_batch(
        kili, reference_id, review_id, settings, PAGE_COUNTS
    )

    assert report.sources_to_fix == 1
    assert "guide.pdf" in report.invalid_sources[0]
    assert (
        kili.metadata(review_id, external_id)["statut_revue"]
        == "SOURCES_A_CORRIGER"
    )
    assert kili.calls == [("send_back_to_queue", (external_id,))]

    # Relancé sans correction : rien ne bouge, pas de second renvoi.
    promote_batch(kili, reference_id, review_id, settings, PAGE_COUNTS)
    assert len(kili.calls) == 1

    kili.add_label(
        review_id,
        external_id,
        {
            "CANDIDATE_CORRECTE": {"categories": [{"name": "NON"}]},
            "SOURCES_PERTINENTES": {"categories": [{"name": "NON"}]},
            "SOURCES_CORRIGEES": {"text": "guide.pdf:3"},
        },
        date="2026-07-19",
    )
    report = promote_batch(
        kili, reference_id, review_id, settings, PAGE_COUNTS
    )
    assert report.sent_to_regeneration == 1
    assert (
        kili.metadata(review_id, external_id)["statut_revue"]
        == "A_REGENERER"
    )


def test_without_a_catalogue_sources_are_not_checked(
    kili, settings, projects
):
    reference_id, review_id, question_id = projects
    external_id = submit_case(
        kili, review_id, settings, question_id=question_id
    )
    arbitrate(
        kili,
        review_id,
        external_id,
        "NON",
        SOURCES_CORRIGEES="guide.pdf:9",
    )

    report = promote_batch(kili, reference_id, review_id, settings)

    assert report.sources_to_fix == 0
    assert report.sent_to_regeneration == 1


def test_invalid_reference_sources_are_ignored(kili, settings, projects):
    reference_id, review_id, question_id = projects
    kili.add_label(
        reference_id,
        question_id,
        {
            "ENTREE_TOUJOURS_VALIDE": {"categories": [{"name": "OUI"}]},
            "SOURCES_CORRIGEES": {"text": "cg_auto.pdf:99"},
        },
    )

    report = promote_batch(
        kili, reference_id, review_id, settings, PAGE_COUNTS
    )

    entry = load_entries(kili, reference_id)[0]
    assert [s.label() for s in entry.sources] == ["cg_auto.pdf:12"]
    assert len(report.invalid_sources) == 1


# --------------------------------------------------------------------- #
# Régénération
# --------------------------------------------------------------------- #
def regenerated_case(kili, settings, projects, documents, **jobs):
    reference_id, review_id, question_id = projects
    external_id = submit_case(
        kili, review_id, settings, question_id=question_id
    )
    arbitrate(kili, review_id, external_id, "NON", **jobs)
    promote_batch(kili, reference_id, review_id, settings)
    report = regenerate_batch(
        kili,
        reference_id,
        review_id,
        documents,
        OfflineDrafter(),
        settings,
    )
    return external_id, external_id + "__relecture", report


def test_a_draft_is_imported_for_proofreading(
    kili, settings, projects, documents
):
    _, review_id, question_id = projects
    external_id, draft_id, report = regenerated_case(
        kili,
        settings,
        projects,
        documents,
        CONSIGNE_CORRECTION="C'est cinq jours ouvrés.",
    )

    assert report.drafts_created == 1
    draft = kili.metadata(review_id, draft_id)
    assert draft["motif"] == "RELECTURE_BROUILLON"
    assert draft["question_id"] == question_id
    assert draft["cas_origine"] == external_id
    assert draft["consigne_correction"] == "C'est cinq jours ouvrés."
    assert draft["reponse_rejetee"] == "Vous avez trente jours."
    assert "cg_auto.pdf p. 12" in draft["candidate_answer"]
    assert (
        kili.metadata(review_id, external_id)["statut_revue"] == "REGENERE"
    )
    prediction = kili.data[review_id][draft_id]["labels"][0]
    assert prediction["labelType"] == "PREDICTION"
    assert (
        prediction["jsonResponse"]["VERSION_CORRIGEE"]["text"]
        == draft["candidate_answer"]
    )


def test_regeneration_is_idempotent(kili, settings, projects, documents):
    reference_id, review_id, _ = projects
    regenerated_case(kili, settings, projects, documents)
    assets = len(kili.data[review_id])

    report = regenerate_batch(
        kili, reference_id, review_id, documents, OfflineDrafter(), settings
    )

    assert report.cases_read == 0
    assert len(kili.data[review_id]) == assets


def test_an_interrupted_run_is_completed(
    kili, settings, projects, documents
):
    reference_id, review_id, _ = projects
    external_id, _, _ = regenerated_case(kili, settings, projects, documents)
    metadata = kili.metadata(review_id, external_id)
    metadata["statut_revue"] = "A_REGENERER"

    report = regenerate_batch(
        kili, reference_id, review_id, documents, OfflineDrafter(), settings
    )

    assert report.already_done == 1
    assert (
        kili.metadata(review_id, external_id)["statut_revue"] == "REGENERE"
    )


def test_a_failure_is_retried_then_sent_without_draft(
    kili, settings, projects, documents
):
    reference_id, review_id, question_id = projects
    external_id = submit_case(
        kili, review_id, settings, question_id=question_id
    )
    arbitrate(kili, review_id, external_id, "NON")
    promote_batch(kili, reference_id, review_id, settings)
    drafter = FailingDrafter()

    first = regenerate_batch(
        kili, reference_id, review_id, documents, drafter, settings
    )
    assert first.retries_pending == 1
    metadata = kili.metadata(review_id, external_id)
    assert metadata["statut_revue"] == "A_REGENERER"
    assert metadata["tentatives_regeneration"] == 1

    second = regenerate_batch(
        kili, reference_id, review_id, documents, drafter, settings
    )
    assert second.failures == 1
    draft = kili.metadata(review_id, external_id + "__relecture")
    assert draft["candidate_answer"] == ""
    assert "2 tentatives" in draft["erreur_regeneration"]
    assert kili.data[review_id][external_id + "__relecture"]["labels"] == []


def test_missing_sources_skip_the_model(kili, settings, projects, documents):
    reference_id, review_id, question_id = projects
    external_id = submit_case(
        kili,
        review_id,
        settings,
        question_id=question_id,
        sources=[Source(doc_id="absent.pdf", page=1)],
    )
    arbitrate(kili, review_id, external_id, "NON")
    promote_batch(kili, reference_id, review_id, settings)
    drafter = FailingDrafter()

    report = regenerate_batch(
        kili, reference_id, review_id, documents, drafter, settings
    )

    assert drafter.calls == 0
    assert report.failures == 1
    draft = kili.metadata(review_id, external_id + "__relecture")
    assert "absent.pdf" in draft["erreur_regeneration"]


def test_too_many_pages_skip_the_model(kili, settings, projects, documents):
    reference_id, review_id, question_id = projects
    external_id = submit_case(
        kili,
        review_id,
        settings,
        question_id=question_id,
        sources=[Source(doc_id="cg_auto.pdf")],
    )
    arbitrate(kili, review_id, external_id, "NON")
    promote_batch(kili, reference_id, review_id, settings)

    regenerate_batch(
        kili, reference_id, review_id, documents, FailingDrafter(), settings
    )

    draft = kili.metadata(review_id, external_id + "__relecture")
    assert "20 pages" in draft["erreur_regeneration"]


# --------------------------------------------------------------------- #
# Relecture puis promotion
# --------------------------------------------------------------------- #
def proofread(kili, review_id, draft_id, verdict, text=None):
    response = {
        "CANDIDATE_CORRECTE": {"categories": [{"name": verdict}]},
        "SOURCES_PERTINENTES": {"categories": [{"name": "OUI"}]},
    }
    if text is not None:
        response["VERSION_CORRIGEE"] = {"text": text}
    kili.add_label(review_id, draft_id, response, date="2026-07-20")


def test_an_accepted_draft_enters_the_repository(
    kili, settings, projects, documents
):
    reference_id, review_id, _ = projects
    _, draft_id, _ = regenerated_case(kili, settings, projects, documents)
    draft = kili.metadata(review_id, draft_id)["candidate_answer"]
    # Le brouillon pré-rempli n'a pas été retouché.
    proofread(kili, review_id, draft_id, "OUI", text=draft)

    report = promote_batch(kili, reference_id, review_id, settings)

    entry = load_entries(kili, reference_id)[0]
    assert report.drafts_promoted == 1
    assert report.drafts_edited == 0
    assert entry.answers[-1].origine == "llm_regenere"
    assert entry.answers[-1].text == draft
    assert kili.metadata(review_id, draft_id)["statut_revue"] == "PROMU"


def test_an_accepted_draft_without_prefill_still_enters(
    kili, settings, projects, documents
):
    reference_id, review_id, _ = projects
    _, draft_id, _ = regenerated_case(kili, settings, projects, documents)
    proofread(kili, review_id, draft_id, "OUI")

    promote_batch(kili, reference_id, review_id, settings)

    entry = load_entries(kili, reference_id)[0]
    assert entry.answers[-1].origine == "llm_regenere"


def test_an_edited_draft_is_counted(kili, settings, projects, documents):
    reference_id, review_id, _ = projects
    _, draft_id, _ = regenerated_case(kili, settings, projects, documents)
    proofread(
        kili,
        review_id,
        draft_id,
        "PRESQUE",
        text="Vous disposez de cinq jours ouvrés pour déclarer.",
    )

    report = promote_batch(kili, reference_id, review_id, settings)

    entry = load_entries(kili, reference_id)[0]
    assert report.drafts_edited == 1
    assert entry.answers[-1].origine == "llm_regenere"
    assert entry.answers[-1].text.startswith("Vous disposez")


def test_a_rejected_draft_left_as_is_is_not_promoted(
    kili, settings, projects, documents
):
    reference_id, review_id, _ = projects
    _, draft_id, _ = regenerated_case(kili, settings, projects, documents)
    draft = kili.metadata(review_id, draft_id)["candidate_answer"]
    proofread(kili, review_id, draft_id, "NON", text=draft)

    report = promote_batch(kili, reference_id, review_id, settings)

    assert report.rejected == 1
    # Un brouillon rejeté n'est jamais réécrit : pas de boucle.
    assert report.sent_to_regeneration == 0
    assert kili.metadata(review_id, draft_id)["statut_revue"] == "REJETE"
    assert len(load_entries(kili, reference_id)[0].answers) == 1


def test_a_rewritten_answer_is_a_business_wording(
    kili, settings, projects, documents
):
    reference_id, review_id, _ = projects
    _, draft_id, _ = regenerated_case(kili, settings, projects, documents)
    proofread(
        kili,
        review_id,
        draft_id,
        "NON",
        text="Le délai court à compter de la connaissance du sinistre.",
    )

    promote_batch(kili, reference_id, review_id, settings)

    assert load_entries(kili, reference_id)[0].answers[-1].origine == (
        "metier"
    )


def test_a_new_question_gets_its_entry_from_the_draft(
    kili, settings, projects, documents
):
    reference_id, review_id, _ = projects
    question = "Quel délai pour déclarer un vol de véhicule ?"
    external_id = submit_case(
        kili,
        review_id,
        settings,
        question_id="q_nouvelle_000",
        motif="NOUVELLE_QUESTION",
        question=question,
        verdict_juge=None,
    )
    arbitrate(kili, review_id, external_id, "NON")
    report = promote_batch(kili, reference_id, review_id, settings)
    assert report.sent_to_regeneration == 1
    assert len(load_entries(kili, reference_id)) == 1

    regenerate_batch(
        kili, reference_id, review_id, documents, OfflineDrafter(), settings
    )
    proofread(kili, review_id, external_id + "__relecture", "OUI")
    report = promote_batch(kili, reference_id, review_id, settings)

    assert report.new_entries == 1
    created = [
        e for e in load_entries(kili, reference_id) if e.question == question
    ]
    assert created[0].answers[0].origine == "llm_regenere"
    assert [s.label() for s in created[0].sources] == ["cg_auto.pdf:12"]


# --------------------------------------------------------------------- #
# Carte de relecture
# --------------------------------------------------------------------- #
def texts_of(nodes):
    found = []
    for node in nodes:
        if "text" in node:
            found.append(node["text"])
        found.extend(texts_of(node.get("children", [])))
    return found


def test_the_card_shows_draft_instruction_and_rejected_answer():
    case = ReviewCase(
        question_id="q",
        run_id="run_42",
        motif="RELECTURE_BROUILLON",
        question=QUESTION,
        candidate_answer="Cinq jours ouvrés (cg_auto.pdf, p. 12).",
        sources=[Source(doc_id="cg_auto.pdf", page=12)],
        consigne_correction="C'est cinq jours ouvrés.",
        reponse_rejetee="Vous avez trente jours.",
    )

    texts = " ".join(texts_of(render_draft_review_asset(case, [])))

    assert "Brouillon à relire" in texts
    assert "Cinq jours ouvrés" in texts
    assert "C'est cinq jours ouvrés." in texts
    assert "Vous avez trente jours." in texts
    assert "n'a pas pu être rédigé" not in texts


def test_the_card_explains_a_failed_draft():
    case = ReviewCase(
        question_id="q",
        run_id="run_42",
        motif="RELECTURE_BROUILLON",
        question=QUESTION,
        candidate_answer="",
        erreur_regeneration="sources introuvables.",
    )

    texts = " ".join(texts_of(render_draft_review_asset(case, [])))

    assert "n'a pas pu être rédigé : sources introuvables." in texts
    assert "Aucun brouillon." in texts


# --------------------------------------------------------------------- #
# Rédacteur Claude (client simulé, aucun appel réseau)
# --------------------------------------------------------------------- #
class FakeMessages:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def fake_client(messages):
    return SimpleNamespace(beta=SimpleNamespace(messages=messages))


def reply(text="Cinq jours ouvrés (cg_auto.pdf, p. 12).", stop="end_turn"):
    return SimpleNamespace(
        stop_reason=stop,
        content=[SimpleNamespace(type="text", text=text)],
    )


PAGES = [PageImage("cg_auto.pdf", 12, b"\x89PNG fausse image")]


def test_the_drafter_sends_every_page_as_an_image():
    messages = FakeMessages(reply())
    drafter = ClaudeDrafter(
        fake_client(messages), "claude-opus-5-5", style="Vouvoyer."
    )

    text = drafter.draft(QUESTION, PAGES, "Cinq jours.", "Trente jours.")

    assert text.startswith("Cinq jours ouvrés")
    content = messages.kwargs["messages"][0]["content"]
    assert content[0]["text"] == "Document : cg_auto.pdf — page 12"
    assert content[1]["type"] == "image"
    assert "Trente jours." in content[2]["text"]
    assert messages.kwargs["betas"] == [FALLBACK_BETA]
    assert messages.kwargs["fallbacks"] == "default"
    assert "Vouvoyer." in messages.kwargs["system"]


def test_fallbacks_can_be_turned_off():
    messages = FakeMessages(reply())
    drafter = ClaudeDrafter(fake_client(messages), "m", fallbacks=False)

    drafter.draft(QUESTION, PAGES, None, "")

    assert "fallbacks" not in messages.kwargs
    assert "betas" not in messages.kwargs


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_an_unusable_reply_is_a_drafting_error(stop):
    drafter = ClaudeDrafter(fake_client(FakeMessages(reply(stop=stop))), "m")
    with pytest.raises(DraftingError):
        drafter.draft(QUESTION, PAGES, None, "")


def test_an_api_error_is_a_drafting_error():
    import anthropic
    import httpx2

    error = anthropic.APIConnectionError(
        request=httpx2.Request("POST", "https://api.anthropic.com")
    )
    drafter = ClaudeDrafter(fake_client(FakeMessages(error=error)), "m")
    with pytest.raises(DraftingError):
        drafter.draft(QUESTION, PAGES, None, "")
