import pytest
from pydantic import ValidationError

from rag_referentiel.schemas import (
    Answer,
    ReferenceEntry,
    ReviewCase,
    Source,
    Verdict,
)
from rag_referentiel.storage import (
    is_size_error,
    metadata_size,
    prepare_payload,
    shrink_metadata,
    write_with_fallback,
)


def entry():
    return ReferenceEntry(
        question_id="q_abc",
        question="Quel est le délai ?",
        answers=[
            Answer(
                id="a1",
                text="Cinq jours ouvrés " * 50,
                origine="metier",
                auteur="c.durand",
                date="2026-03-11",
            )
        ],
        sources=[Source(doc_id="cg.pdf", page=12)],
    )


def test_default_status_and_allowed_values():
    assert entry().statut == "ACTIF"
    with pytest.raises(ValidationError):
        ReferenceEntry(question_id="q", question="?", statut="INCONNU")


def test_origin_is_constrained():
    with pytest.raises(ValidationError):
        Answer(
            id="a1",
            text="x",
            origine="contre_exemple",
            auteur="a",
            date="2026-01-01",
        )


def test_source_without_a_page():
    source = Source(doc_id="cg.pdf")
    assert source.page is None
    assert source.label() == "cg.pdf"
    assert Source(doc_id="cg.pdf", page=3).label() == "cg.pdf:3"


def test_a_decomposed_accent_in_a_document_name_is_recomposed():
    import unicodedata

    composed = "Avenant_Résiliation_2026.pdf"
    decomposed = unicodedata.normalize("NFD", composed)
    assert decomposed != composed
    assert Source(doc_id=decomposed).doc_id == composed
    assert Source(doc_id=f"  {composed} ").doc_id == composed


def test_verdict_confidence_is_bounded():
    with pytest.raises(ValidationError):
        Verdict(conforme=True, confiance=1.5, motif="x")


def test_review_case_reason_is_constrained():
    with pytest.raises(ValidationError):
        ReviewCase(
            question_id="q",
            run_id="r",
            motif="AUTRE",
            question="?",
            candidate_answer="x",
        )


def test_payload_below_the_threshold_stays_complete():
    payload = prepare_payload(
        entry().model_dump(), [{"children": []}], 10**6
    )
    assert payload.fallback is False
    assert payload.json_metadata["answers"][0]["text"]


def test_payload_above_the_threshold_is_shrunk():
    metadata = entry().model_dump()
    payload = prepare_payload(metadata, [{"children": []}], 200)
    assert payload.fallback is True
    assert "text" not in payload.json_metadata["answers"][0]
    assert payload.json_metadata["repli_texte"] is True
    assert payload.json_metadata["question"] == metadata["question"]
    assert metadata_size(payload.json_metadata) < metadata_size(metadata)


def test_shrinking_drops_the_candidate_answer():
    shrunk = shrink_metadata(
        {"question_id": "q", "candidate_answer": "x" * 100}
    )
    assert "candidate_answer" not in shrunk
    assert shrunk["repli_texte"] is True


def test_size_error_detection():
    assert is_size_error(RuntimeError("Payload too large"))
    assert not is_size_error(RuntimeError("Not found"))


def test_write_is_replayed_with_shrunk_metadata():
    attempts = []

    def write(payload):
        attempts.append(payload)
        if not payload.fallback:
            raise RuntimeError("request entity too large")
        return "écrit"

    result = write_with_fallback(
        write, entry().model_dump(), [{"children": []}], 10**6
    )
    assert result == "écrit"
    assert [a.fallback for a in attempts] == [False, True]


def test_an_error_unrelated_to_size_is_propagated():
    def write(payload):
        del payload
        raise RuntimeError("authentication failed")

    with pytest.raises(RuntimeError, match="authentication"):
        write_with_fallback(
            write, entry().model_dump(), [{"children": []}], 10**6
        )
