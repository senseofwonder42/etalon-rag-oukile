from rag_referentiel.rendering import (
    render_reference_asset,
    render_review_asset,
)
from rag_referentiel.schemas import (
    Answer,
    ReferenceEntry,
    ReviewCase,
    Source,
    Verdict,
)


def nodes(document):
    """Parcourt l'arbre en profondeur, dans l'ordre du document."""
    found = []
    stack = list(reversed(document))
    while stack:
        node = stack.pop()
        found.append(node)
        stack.extend(reversed(node.get("children", [])))
    return found


def entry():
    return ReferenceEntry(
        question_id="q_abc",
        question="Quel est le délai ?",
        version=3,
        answers=[
            Answer(
                id="a1",
                text="Cinq jours **ouvrés**.",
                origine="metier",
                auteur="c.durand",
                date="2026-03-11",
            )
        ],
        sources=[
            Source(doc_id="cg_auto.pdf", page=12),
            Source(doc_id="cg_auto.pdf", page=14),
        ],
    )


def case(reason="DIVERGENCE"):
    return ReviewCase(
        question_id="q_abc",
        run_id="run_42",
        motif=reason,
        question="Quel est le délai ?",
        candidate_answer="Vous disposez de **5 jours ouvrés**.",
        sources=[Source(doc_id="cg_auto.pdf", page=12)],
        verdict_juge=Verdict(
            conforme=False, confiance=0.31, motif="chiffre divergent"
        ),
        question_id_candidat="q_candidat",
    )


def test_reference_card_structure():
    document = render_reference_asset(entry())
    kinds = [n.get("type") for n in nodes(document) if "type" in n]
    assert "h1" in kinds
    assert "table" in kinds
    content = " ".join(n["text"] for n in nodes(document) if "text" in n)
    assert "Quel est le délai ?" in content
    assert "c.durand" in content


def test_the_answer_number_heads_its_wording():
    document = render_reference_asset(entry())
    kinds = [
        (n.get("type"), n["children"][0].get("text"))
        for n in nodes(document)
        if n.get("type") == "h3"
    ]
    assert ("h3", "Réponse 1") in kinds
    content = " ".join(n["text"] for n in nodes(document) if "text" in n)
    assert "origine : metier" in content


def test_the_sources_table_holds_one_row_per_document():
    document = render_reference_asset(entry())
    rows = [n for n in nodes(document) if n.get("type") == "tr"]
    # Une ligne d'en-tête, une seule ligne pour les deux pages du même
    # document.
    assert len(rows) == 2
    cells = [
        c["children"][0]["text"] for c in rows[1]["children"]
    ]
    assert cells == ["cg_auto.pdf", "12, 14"]


def test_a_document_without_a_page_shows_a_dash():
    entry_without_page = entry()
    entry_without_page.sources = [Source(doc_id="annexe.pdf")]
    document = render_reference_asset(entry_without_page)
    rows = [n for n in nodes(document) if n.get("type") == "tr"]
    assert [
        c["children"][0]["text"] for c in rows[1]["children"]
    ] == ["annexe.pdf", "—"]


def test_sources_are_repeated_in_the_input_format():
    document = render_reference_asset(entry())
    content = " ".join(n["text"] for n in nodes(document) if "text" in n)
    assert "cg_auto.pdf:12 14" in content
    assert "copier-coller" in content


def test_a_new_question_hides_the_validated_wordings_section():
    document = render_review_asset(case("NOUVELLE_QUESTION"), [])
    content = " ".join(n["text"] for n in nodes(document) if "text" in n)
    assert "Formulations déjà validées" not in content
    assert "Réponse générée à arbitrer" in content


def _headings(document):
    return [
        n["children"][0].get("text")
        for n in nodes(document)
        if n.get("type") == "h2"
    ]


def test_a_matched_case_also_shows_the_reference_question():
    document = render_review_asset(
        case("DIVERGENCE"),
        [entry().answers[0]],
        candidate_question="Quel est le délai de déclaration ?",
    )
    headings = _headings(document)
    assert "Question du référentiel appariée" in headings
    content = " ".join(n["text"] for n in nodes(document) if "text" in n)
    assert "Quel est le délai de déclaration ?" in content


def test_a_reference_question_identical_to_the_asked_one_is_not_repeated():
    matched = case("DIVERGENCE")
    document = render_review_asset(
        matched,
        [entry().answers[0]],
        candidate_question=matched.question,
    )
    headings = _headings(document)
    assert "Question du référentiel appariée" not in headings
    assert "Formulations déjà validées" in headings


def test_the_answer_to_arbitrate_sits_in_the_right_column():
    document = render_review_asset(case(), [entry().answers[0]])
    candidate = [
        n
        for n in nodes(document)
        if n.get("backgroundColor") == "#fff3e0"
    ]
    validated = [
        n
        for n in nodes(document)
        if n.get("backgroundColor") == "#e8f5e9"
    ]
    assert candidate and all(n["margin"] == "0 0 0 35%" for n in candidate)
    assert validated and all("margin" not in n for n in validated)
    heading = next(
        n
        for n in nodes(document)
        if n.get("type") == "h2"
        and n["children"][0]["text"] == "Réponse générée à arbitrer"
    )
    assert heading["textAlign"] == "right"


def test_the_proposed_question_comes_just_above_the_wordings():
    document = render_review_asset(
        case("APPARIEMENT_INCERTAIN"),
        [entry().answers[0]],
        candidate_question="Une autre question ?",
    )
    headings = _headings(document)
    assert headings.index("Question du référentiel proposée") < headings.index(
        "Formulations validées pour cette question"
    )


def test_review_card_never_shows_the_judge_verdict():
    document = render_review_asset(case(), [entry().answers[0]])
    content = " ".join(n["text"] for n in nodes(document) if "text" in n)
    assert "chiffre divergent" not in content
    assert "0.31" not in content
    assert "conforme" not in content.lower()


def test_review_card_colours_the_answers():
    document = render_review_asset(case(), [entry().answers[0]])
    backgrounds = {
        n["backgroundColor"]
        for n in nodes(document)
        if "backgroundColor" in n
    }
    assert "#e8f5e9" in backgrounds
    assert "#fff3e0" in backgrounds


def test_review_card_shows_the_candidate_question_when_uncertain():
    document = render_review_asset(
        case("APPARIEMENT_INCERTAIN"),
        [],
        candidate_question="Une autre question ?",
    )
    content = " ".join(n["text"] for n in nodes(document) if "text" in n)
    assert "Une autre question ?" in content


def test_identifiers_are_unique_in_each_rendering():
    for document in (
        render_reference_asset(entry()),
        render_review_asset(case(), [entry().answers[0]]),
    ):
        identifiers = [n["id"] for n in nodes(document) if "id" in n]
        assert len(identifiers) == len(set(identifiers))


def test_rendering_is_deterministic():
    assert render_reference_asset(entry()) == render_reference_asset(entry())
