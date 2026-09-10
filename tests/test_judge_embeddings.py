import httpx
import pytest

from rag_referentiel.embeddings import (
    JinaEmbeddings,
    ModelUnavailableError,
)
from rag_referentiel.judge import LexicalJudge, _parse_verdict

REFERENCE = "Le délai de déclaration est de cinq jours ouvrés."


def test_lexical_judge_finds_a_compliant_answer():
    verdict = LexicalJudge(0.5).judge(
        "Quel délai ?",
        "Le délai de déclaration est de cinq jours ouvrés au maximum.",
        [REFERENCE],
    )
    assert verdict.conforme
    assert verdict.confiance > 0.5


def test_lexical_judge_finds_a_non_compliant_answer():
    verdict = LexicalJudge(0.6).judge(
        "Quel délai ?",
        "La franchise s'élève à cent cinquante euros.",
        [REFERENCE],
    )
    assert not verdict.conforme


def test_lexical_judge_keeps_the_best_of_the_wordings():
    verdict = LexicalJudge(0.6).judge(
        "Quel délai ?",
        REFERENCE,
        ["Une formulation sans rapport.", REFERENCE],
    )
    assert verdict.conforme


def test_lexical_judge_without_any_reference():
    verdict = LexicalJudge().judge("Quel délai ?", "Peu importe.", [])
    assert not verdict.conforme
    assert verdict.confiance == 0.0


def test_reading_a_json_verdict():
    verdict = _parse_verdict(
        'Voici : {"conforme": true, "confiance": 0.8, "motif": "ok"}'
    )
    assert verdict.conforme
    assert verdict.confiance == 0.8


def test_an_unreadable_verdict_sends_the_case_to_review():
    verdict = _parse_verdict("je ne sais pas répondre")
    assert not verdict.conforme
    assert verdict.confiance == 0.0


def _backend(response: httpx.Response, model="jina-embeddings-v5-nano"):
    transport = httpx.MockTransport(lambda request: response)
    return JinaEmbeddings(
        api_key="factice",
        model=model,
        base_url="https://api.exemple.fr/v1",
        client=httpx.Client(transport=transport),
    )


def test_an_available_model():
    backend = _backend(
        httpx.Response(
            200, json={"data": [{"id": "jina-embeddings-v5-nano"}]}
        )
    )
    backend.check_model_available()


def test_a_missing_model_fails_with_a_clear_message():
    backend = _backend(
        httpx.Response(200, json={"data": [{"id": "autre-modele"}]})
    )
    with pytest.raises(ModelUnavailableError, match="autre-modele"):
        backend.check_model_available()


def test_an_unreachable_service_fails_with_a_clear_message():
    backend = _backend(httpx.Response(503, text="indisponible"))
    with pytest.raises(ModelUnavailableError, match="503"):
        backend.check_model_available()
