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
    stack = list(document)
    while stack:
        node = stack.pop()
        yield node
        stack.extend(node.get("children", []))


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
        sources=[Source(doc_id="cg_auto.pdf", page=12)],
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


def test_answer_markers_are_shown_on_the_card():
    document = render_reference_asset(entry())
    content = " ".join(n["text"] for n in nodes(document) if "text" in n)
    assert "a1 · origine : metier" in content


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
