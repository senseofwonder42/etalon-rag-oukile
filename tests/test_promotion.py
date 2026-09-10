import pytest

from rag_referentiel.config import Settings
from rag_referentiel.referentiel import (
    UnknownAnswerMarkerError,
    add_variant,
    build_entry,
    create_project,
    import_entries,
    load_entries,
    parse_sources,
    promote_batch,
    remove_answers,
    replace_answer,
    select_variants,
)
from rag_referentiel.revue import compute_external_ids, create_cases
from rag_referentiel.revue import create_project as create_review_project
from rag_referentiel.schemas import Answer, ReviewCase, Source, Verdict

QUESTION = "Quel est le délai de déclaration d'un sinistre auto ?"
BUSINESS_ANSWER = "Le délai est de cinq jours ouvrés après le sinistre."


@pytest.fixture
def settings():
    return Settings(
        kili_api_key="factice",
        near_duplicate_threshold=0.85,
        variant_cap=5,
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
    import_entries(
        kili, reference_id, [entry], settings.max_metadata_size
    )
    review_id = create_review_project(kili, "Revue")
    return reference_id, review_id, entry.question_id


def submit_case(kili, review_id, settings, **overrides):
    case = ReviewCase(
        **{
            "question_id": overrides.pop("question_id"),
            "run_id": "run_42",
            "motif": "DIVERGENCE",
            "question": QUESTION,
            "candidate_answer": "Vous avez cinq jours ouvrés.",
            "sources": [Source(doc_id="cg_auto.pdf", page=12)],
            "verdict_juge": Verdict(
                conforme=False, confiance=0.4, motif="test"
            ),
            "score_appariement": 0.9,
            **overrides,
        }
    )
    identifiers = compute_external_ids([case])
    create_cases(
        kili,
        review_id,
        [case],
        identifiers,
        {},
        {},
        settings.max_metadata_size,
    )
    return identifiers[0]


def test_verdict_yes_adds_a_variant(kili, settings, projects):
    reference_id, review_id, question_id = projects
    external_id = submit_case(
        kili, review_id, settings, question_id=question_id
    )
    kili.add_label(
        review_id,
        external_id,
        {
            "CANDIDATE_CORRECTE": {"categories": [{"name": "OUI"}]},
            "SOURCES_PERTINENTES": {"categories": [{"name": "OUI"}]},
        },
        author="m.leroy@exemple.fr",
    )

    report = promote_batch(kili, reference_id, review_id, settings)

    assert report.promoted == 1
    assert report.variants_added == 1
    entry = load_entries(kili, reference_id)[0]
    assert len(entry.answers) == 2
    assert entry.answers[1].origine == "rag_valide"
    assert entry.answers[1].auteur == "m.leroy@exemple.fr"
    assert entry.answers[1].run_id == "run_42"
    assert entry.version == 2
    assert kili.metadata(review_id, external_id)["statut_revue"] == "PROMU"


def test_verdict_almost_promotes_the_corrected_version(
    kili, settings, projects
):
    reference_id, review_id, question_id = projects
    external_id = submit_case(
        kili, review_id, settings, question_id=question_id
    )
    kili.add_label(
        review_id,
        external_id,
        {
            "CANDIDATE_CORRECTE": {"categories": [{"name": "PRESQUE"}]},
            "VERSION_CORRIGEE": {
                "text": "Cinq jours ouvrés, hors vol et hors catastrophe."
            },
            "SOURCES_PERTINENTES": {"categories": [{"name": "OUI"}]},
        },
    )

    promote_batch(kili, reference_id, review_id, settings)

    entry = load_entries(kili, reference_id)[0]
    assert entry.answers[1].origine == "rag_corrige"
    assert "hors vol" in entry.answers[1].text


def test_almost_without_a_correction_writes_nothing(
    kili, settings, projects
):
    reference_id, review_id, question_id = projects
    external_id = submit_case(
        kili, review_id, settings, question_id=question_id
    )
    kili.add_label(
        review_id,
        external_id,
        {
            "CANDIDATE_CORRECTE": {"categories": [{"name": "PRESQUE"}]},
            "SOURCES_PERTINENTES": {"categories": [{"name": "NON"}]},
        },
    )

    report = promote_batch(kili, reference_id, review_id, settings)

    assert report.rejected == 1
    assert len(load_entries(kili, reference_id)[0].answers) == 1
    assert kili.metadata(review_id, external_id)["statut_revue"] == "REJETE"


def test_verdict_no_writes_nothing(kili, settings, projects):
    reference_id, review_id, question_id = projects
    external_id = submit_case(
        kili, review_id, settings, question_id=question_id
    )
    kili.add_label(
        review_id,
        external_id,
        {
            "CANDIDATE_CORRECTE": {"categories": [{"name": "NON"}]},
            "SOURCES_PERTINENTES": {"categories": [{"name": "NON"}]},
        },
    )

    report = promote_batch(kili, reference_id, review_id, settings)

    entry = load_entries(kili, reference_id)[0]
    assert report.rejected == 1
    assert len(entry.answers) == 1
    assert entry.version == 1
    assert kili.metadata(review_id, external_id)["statut_revue"] == "REJETE"


def test_same_question_no_creates_a_new_entry(kili, settings, projects):
    reference_id, review_id, _ = projects
    external_id = submit_case(
        kili,
        review_id,
        settings,
        question_id="q_nouvelle_000",
        motif="APPARIEMENT_INCERTAIN",
        question="Quel délai pour déclarer un vol de véhicule ?",
        question_id_candidat="q_existante",
    )
    kili.add_label(
        review_id,
        external_id,
        {
            "MEME_QUESTION": {"categories": [{"name": "NON"}]},
            "CANDIDATE_CORRECTE": {"categories": [{"name": "OUI"}]},
            "SOURCES_PERTINENTES": {"categories": [{"name": "OUI"}]},
        },
    )

    report = promote_batch(kili, reference_id, review_id, settings)

    assert report.new_entries == 1
    questions = {e.question for e in load_entries(kili, reference_id)}
    assert "Quel délai pour déclarer un vol de véhicule ?" in questions


def test_an_uncertain_case_without_an_answer_stays_pending(
    kili, settings, projects
):
    reference_id, review_id, _ = projects
    external_id = submit_case(
        kili,
        review_id,
        settings,
        question_id="q_nouvelle_000",
        motif="APPARIEMENT_INCERTAIN",
        question_id_candidat="q_existante",
    )
    kili.add_label(
        review_id,
        external_id,
        {"CANDIDATE_CORRECTE": {"categories": [{"name": "OUI"}]}},
    )

    report = promote_batch(kili, reference_id, review_id, settings)

    assert report.skipped == 1
    assert (
        kili.metadata(review_id, external_id)["statut_revue"] == "EN_ATTENTE"
    )


def test_promotion_is_idempotent(kili, settings, projects):
    reference_id, review_id, question_id = projects
    external_id = submit_case(
        kili, review_id, settings, question_id=question_id
    )
    kili.add_label(
        review_id,
        external_id,
        {
            "CANDIDATE_CORRECTE": {"categories": [{"name": "OUI"}]},
            "SOURCES_PERTINENTES": {"categories": [{"name": "OUI"}]},
        },
    )

    promote_batch(kili, reference_id, review_id, settings)
    after_first = load_entries(kili, reference_id)[0]
    report = promote_batch(kili, reference_id, review_id, settings)
    after_second = load_entries(kili, reference_id)[0]

    assert report.cases_read == 0
    assert after_second.model_dump() == after_first.model_dump()


def test_an_identical_variant_is_rejected_as_a_near_duplicate(
    kili, settings, projects
):
    reference_id, review_id, question_id = projects
    external_id = submit_case(
        kili,
        review_id,
        settings,
        question_id=question_id,
        candidate_answer=BUSINESS_ANSWER,
    )
    kili.add_label(
        review_id,
        external_id,
        {
            "CANDIDATE_CORRECTE": {"categories": [{"name": "OUI"}]},
            "SOURCES_PERTINENTES": {"categories": [{"name": "OUI"}]},
        },
    )

    report = promote_batch(kili, reference_id, review_id, settings)

    entry = load_entries(kili, reference_id)[0]
    assert report.variants_added == 0
    assert len(entry.answers) == 1
    assert entry.version == 1


def test_corrected_sources_replace_the_source_list(
    kili, settings, projects
):
    reference_id, review_id, question_id = projects
    external_id = submit_case(
        kili, review_id, settings, question_id=question_id
    )
    kili.add_label(
        review_id,
        external_id,
        {
            "CANDIDATE_CORRECTE": {"categories": [{"name": "OUI"}]},
            "SOURCES_PERTINENTES": {"categories": [{"name": "PARTIEL"}]},
            "SOURCES_CORRIGEES": {"text": "cg_auto.pdf:14, guide.pdf:3"},
        },
    )

    promote_batch(kili, reference_id, review_id, settings)

    entry = load_entries(kili, reference_id)[0]
    assert [(s.doc_id, s.page) for s in entry.sources] == [
        ("cg_auto.pdf", 14),
        ("guide.pdf", 3),
    ]


def test_judge_business_disagreement_is_counted(kili, settings, projects):
    reference_id, review_id, question_id = projects
    external_id = submit_case(
        kili, review_id, settings, question_id=question_id
    )
    kili.add_label(
        review_id,
        external_id,
        {
            "CANDIDATE_CORRECTE": {"categories": [{"name": "OUI"}]},
            "SOURCES_PERTINENTES": {"categories": [{"name": "OUI"}]},
        },
    )

    report = promote_batch(kili, reference_id, review_id, settings)

    assert report.judge_business_disagreements == 1


def test_still_valid_yes_puts_the_entry_back_to_active(
    kili, settings, projects
):
    reference_id, review_id, question_id = projects
    kili.metadata(reference_id, question_id)["statut"] = "A_REVERIFIER"
    kili.add_label(
        reference_id,
        question_id,
        {"ENTREE_TOUJOURS_VALIDE": {"categories": [{"name": "OUI"}]}},
        date="2026-08-01",
    )

    report = promote_batch(kili, reference_id, review_id, settings)

    entry = load_entries(kili, reference_id)[0]
    assert report.entries_revalidated == 1
    assert entry.statut == "ACTIF"
    assert entry.derniere_verification == "2026-08-01"

    # Rejouer ne doit plus rien changer.
    before = entry.model_dump()
    promote_batch(kili, reference_id, review_id, settings)
    assert load_entries(kili, reference_id)[0].model_dump() == before


def test_still_valid_no_archives_the_entry(kili, settings, projects):
    reference_id, review_id, question_id = projects
    kili.add_label(
        reference_id,
        question_id,
        {"ENTREE_TOUJOURS_VALIDE": {"categories": [{"name": "NON"}]}},
    )

    report = promote_batch(kili, reference_id, review_id, settings)

    assert report.entries_archived == 1
    assert load_entries(kili, reference_id)[0].statut == "ARCHIVE"


def test_the_audit_trail_is_not_read_back_as_an_arbitration(
    kili, settings, projects
):
    reference_id, review_id, question_id = projects
    external_id = submit_case(
        kili, review_id, settings, question_id=question_id
    )
    kili.add_label(
        review_id,
        external_id,
        {
            "CANDIDATE_CORRECTE": {"categories": [{"name": "OUI"}]},
            "SOURCES_PERTINENTES": {"categories": [{"name": "OUI"}]},
        },
    )
    promote_batch(kili, reference_id, review_id, settings)

    labels = kili.data[reference_id][question_id]["labels"]
    assert labels and labels[-1]["labelType"] == "INFERENCE"
    assert labels[-1]["jsonResponse"]["REPONSE_VALIDEE"]["text"]


# --- option A : correction ciblée d'une formulation -------------------
def _reference_label(**jobs):
    response = {"ENTREE_TOUJOURS_VALIDE": {"categories": [{"name": "OUI"}]}}
    if "marker" in jobs:
        response["FORMULATION_CIBLE"] = {
            "categories": [{"name": jobs["marker"]}]
        }
    if "text" in jobs:
        response["REPONSE_VALIDEE"] = {"text": jobs["text"]}
    if "remove" in jobs:
        response["FORMULATIONS_A_RETIRER"] = {
            "categories": [{"name": m} for m in jobs["remove"]]
        }
    if "sources" in jobs:
        response["SOURCES_CORRIGEES"] = {"text": jobs["sources"]}
    return response


@pytest.fixture
def entry_with_three_answers(kili, settings):
    reference_id = create_project(kili, "Référentiel")
    entry = build_entry(
        question=QUESTION,
        texts=[
            "Le délai est de cinq jours ouvrés après le sinistre.",
            "Vous disposez de cinq jours ouvrés pour déclarer.",
            "La déclaration intervient sous cinq jours ouvrés.",
        ],
        sources=[Source(doc_id="cg_auto.pdf", page=12)],
        author="c.durand",
        date="2026-03-11",
    )
    import_entries(
        kili, reference_id, [entry], settings.max_metadata_size
    )
    review_id = create_review_project(kili, "Revue")
    return reference_id, review_id, entry.question_id


def test_a_targeted_replacement_fixes_the_right_answer(
    kili, settings, entry_with_three_answers
):
    reference_id, review_id, question_id = entry_with_three_answers
    kili.add_label(
        reference_id,
        question_id,
        _reference_label(
            marker="a2", text="Vous disposez de cinq jours ouvrés pleins."
        ),
        author="c.durand@exemple.fr",
        date="2026-08-01",
    )

    report = promote_batch(kili, reference_id, review_id, settings)

    entry = load_entries(kili, reference_id)[0]
    assert report.answers_replaced == 1
    assert len(entry.answers) == 3
    assert entry.answers[1].id == "a2"
    assert entry.answers[1].text.endswith("cinq jours ouvrés pleins.")
    assert entry.answers[1].origine == "metier"
    assert entry.answers[1].auteur == "c.durand@exemple.fr"
    assert entry.answers[0].text.startswith("Le délai est de")
    assert entry.version == 2


def test_a_light_correction_is_no_longer_lost(
    kili, settings, entry_with_three_answers
):
    reference_id, review_id, question_id = entry_with_three_answers
    # Texte quasi identique à a2 : sans repère il serait écarté comme
    # quasi-doublon ; avec le repère, il remplace bien la formulation.
    kili.add_label(
        reference_id,
        question_id,
        _reference_label(
            marker="a2", text="Vous disposez de cinq jours ouvrés pour agir."
        ),
    )

    promote_batch(kili, reference_id, review_id, settings)

    entry = load_entries(kili, reference_id)[0]
    assert entry.answers[1].text.endswith("pour agir.")


def test_without_a_marker_the_text_is_added(
    kili, settings, entry_with_three_answers
):
    reference_id, review_id, question_id = entry_with_three_answers
    kili.add_label(
        reference_id,
        question_id,
        _reference_label(
            text="Comptez cinq jours ouvrables, dimanche exclu, dès "
            "connaissance du fait générateur."
        ),
    )

    report = promote_batch(kili, reference_id, review_id, settings)

    entry = load_entries(kili, reference_id)[0]
    assert report.variants_added == 1
    assert len(entry.answers) == 4
    assert entry.answers[3].id == "a4"


def test_an_unknown_marker_is_reported_without_crashing(
    kili, settings, entry_with_three_answers
):
    reference_id, review_id, question_id = entry_with_three_answers
    kili.add_label(
        reference_id,
        question_id,
        _reference_label(marker="a5", text="Un texte quelconque."),
    )

    report = promote_batch(kili, reference_id, review_id, settings)

    assert report.answers_replaced == 0
    assert report.unknown_markers
    assert "a5" in report.unknown_markers[0]
    assert len(load_entries(kili, reference_id)[0].answers) == 3


def test_multiple_removal_and_renumbering(
    kili, settings, entry_with_three_answers
):
    reference_id, review_id, question_id = entry_with_three_answers
    kili.add_label(
        reference_id, question_id, _reference_label(remove=["a1", "a3"])
    )

    report = promote_batch(kili, reference_id, review_id, settings)

    entry = load_entries(kili, reference_id)[0]
    assert report.answers_removed == 2
    assert [a.id for a in entry.answers] == ["a1"]
    assert entry.answers[0].text.startswith("Vous disposez")


def test_two_successive_labels_are_both_consumed(
    kili, settings, entry_with_three_answers
):
    reference_id, review_id, question_id = entry_with_three_answers
    kili.add_label(
        reference_id,
        question_id,
        _reference_label(marker="a1", text="Première correction ouvrés."),
        date="2026-08-01",
    )
    kili.add_label(
        reference_id,
        question_id,
        _reference_label(marker="a3", text="Seconde correction ouvrés."),
        date="2026-08-02",
    )

    report = promote_batch(kili, reference_id, review_id, settings)

    entry = load_entries(kili, reference_id)[0]
    assert report.reference_labels_consumed == 2
    assert report.answers_replaced == 2
    assert entry.answers[0].text == "Première correction ouvrés."
    assert entry.answers[2].text == "Seconde correction ouvrés."
    assert entry.derniere_promotion.startswith("2026-08-02")


def test_the_watermark_makes_the_campaign_idempotent(
    kili, settings, entry_with_three_answers
):
    reference_id, review_id, question_id = entry_with_three_answers
    kili.add_label(
        reference_id,
        question_id,
        _reference_label(marker="a2", text="Une correction ouvrés."),
    )

    promote_batch(kili, reference_id, review_id, settings)
    after_first = load_entries(kili, reference_id)[0].model_dump()
    report = promote_batch(kili, reference_id, review_id, settings)

    assert report.reference_labels_consumed == 0
    assert load_entries(kili, reference_id)[0].model_dump() == after_first


def test_a_label_after_the_watermark_is_taken(
    kili, settings, entry_with_three_answers
):
    reference_id, review_id, question_id = entry_with_three_answers
    kili.add_label(
        reference_id,
        question_id,
        _reference_label(marker="a2", text="Correction ouvrés initiale."),
        date="2026-08-01",
    )
    promote_batch(kili, reference_id, review_id, settings)

    kili.add_label(
        reference_id,
        question_id,
        _reference_label(marker="a2", text="Correction ouvrés suivante."),
        date="2026-08-05",
    )
    report = promote_batch(kili, reference_id, review_id, settings)

    assert report.reference_labels_consumed == 1
    assert (
        load_entries(kili, reference_id)[0].answers[1].text
        == "Correction ouvrés suivante."
    )


def test_corrected_sources_report_the_removed_ones(
    kili, settings, entry_with_three_answers
):
    reference_id, review_id, question_id = entry_with_three_answers
    kili.add_label(
        reference_id, question_id, _reference_label(sources="guide.pdf:5")
    )

    report = promote_batch(kili, reference_id, review_id, settings)

    assert report.removed_sources == [f"{question_id} : cg_auto.pdf:12"]


# --- règles pures ----------------------------------------------------
def _answer(identifier, text, origin="rag_valide"):
    return Answer(
        id=identifier,
        text=text,
        origine=origin,
        auteur="m.leroy",
        date="2026-07-18",
    )


def test_the_variant_cap(settings):
    entry = build_entry(
        QUESTION, [BUSINESS_ANSWER], [], "c.durand", "2026-03-11"
    )
    for index in range(6):
        added = add_variant(
            entry,
            text=f"Formulation numéro {index} totalement distincte "
            f"mot{index} autre{index} encore{index}",
            origin="rag_valide",
            author="m.leroy",
            date="2026-07-18",
            run_id=f"run_{index}",
            near_duplicate_threshold=settings.near_duplicate_threshold,
            cap=settings.variant_cap,
        )
        assert added or len(entry.answers) == settings.variant_cap
    assert len(entry.answers) == settings.variant_cap
    assert entry.answers[0].origine == "metier"


def test_selection_keeps_the_business_wording():
    answers = [
        _answer("a1", "alpha beta gamma", origin="metier"),
        _answer("a2", "alpha beta delta"),
        _answer("a3", "epsilon zeta eta"),
    ]
    kept = select_variants(answers, 2)
    assert [a.id for a in kept] == ["a1", "a3"]


def test_an_empty_variant_is_ignored(settings):
    entry = build_entry(
        QUESTION, [BUSINESS_ANSWER], [], "c.d", "2026-01-01"
    )
    assert not add_variant(
        entry,
        text="   ",
        origin="rag_valide",
        author="m.leroy",
        date="2026-07-18",
        run_id=None,
        near_duplicate_threshold=settings.near_duplicate_threshold,
        cap=settings.variant_cap,
    )


def test_replacing_an_answer_without_a_change():
    entry = build_entry(QUESTION, ["Texte."], [], "c.d", "2026-01-01")
    assert not replace_answer(
        entry, "a1", "Texte.", "m.leroy", "2026-07-18", 0.85
    )


def test_replacing_an_unknown_marker():
    entry = build_entry(QUESTION, ["Texte."], [], "c.d", "2026-01-01")
    with pytest.raises(UnknownAnswerMarkerError, match="a3"):
        replace_answer(
            entry, "a3", "Autre.", "m.leroy", "2026-07-18", 0.85
        )


def test_removing_the_last_answer_is_refused():
    entry = build_entry(QUESTION, ["Texte."], [], "c.d", "2026-01-01")
    removed, unknown = remove_answers(entry, ["a1"])
    assert removed == []
    assert unknown == []
    assert len(entry.answers) == 1


def test_removing_an_unknown_marker_is_reported():
    entry = build_entry(
        QUESTION, ["Un.", "Deux."], [], "c.d", "2026-01-01"
    )
    removed, unknown = remove_answers(entry, ["a2", "a9"])
    assert removed == ["Deux."]
    assert unknown == ["a9"]


def test_renumbering_after_a_removal():
    entry = build_entry(
        QUESTION, ["Un.", "Deux.", "Trois."], [], "c.d", "2026-01-01"
    )
    remove_answers(entry, ["a2"])
    assert [a.id for a in entry.answers] == ["a1", "a2"]
    assert [a.text for a in entry.answers] == ["Un.", "Trois."]


def test_tolerant_source_parsing():
    sources, unreadable = parse_sources(
        "cg_auto.pdf:12, guide.pdf, autre.pdf:page, , cg_hab.pdf:3"
    )
    assert [(s.doc_id, s.page) for s in sources] == [
        ("cg_auto.pdf", 12),
        ("guide.pdf", None),
        ("cg_hab.pdf", 3),
    ]
    assert unreadable == ["autre.pdf:page"]


def test_several_pages_of_the_same_document():
    sources, unreadable = parse_sources("doc1.pdf:p12, p14, p31")
    assert [(s.doc_id, s.page) for s in sources] == [
        ("doc1.pdf", 12),
        ("doc1.pdf", 14),
        ("doc1.pdf", 31),
    ]
    assert unreadable == []


def test_multiple_pages_then_a_document_change():
    sources, _ = parse_sources("doc1.pdf:p12, p14, autre.pdf:2, p7")
    assert [(s.doc_id, s.page) for s in sources] == [
        ("doc1.pdf", 12),
        ("doc1.pdf", 14),
        ("autre.pdf", 2),
        ("autre.pdf", 7),
    ]


def test_a_standalone_page_without_a_document_is_unreadable():
    sources, unreadable = parse_sources("p12, doc.pdf:3")
    assert [(s.doc_id, s.page) for s in sources] == [("doc.pdf", 3)]
    assert unreadable == ["p12"]
