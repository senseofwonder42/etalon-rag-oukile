import httpx
import pytest

from rag_referentiel.embeddings import (
    JinaEmbeddings,
    ModeleIndisponibleError,
)
from rag_referentiel.judge import JugeLexical, _lire_verdict

REFERENCE = "Le délai de déclaration est de cinq jours ouvrés."


def test_juge_lexical_conforme():
    verdict = JugeLexical(0.5).juger(
        "Quel délai ?",
        "Le délai de déclaration est de cinq jours ouvrés au maximum.",
        [REFERENCE],
    )
    assert verdict.conforme
    assert verdict.confiance > 0.5


def test_juge_lexical_non_conforme():
    verdict = JugeLexical(0.6).juger(
        "Quel délai ?",
        "La franchise s'élève à cent cinquante euros.",
        [REFERENCE],
    )
    assert not verdict.conforme


def test_juge_lexical_retient_la_meilleure_des_formulations():
    verdict = JugeLexical(0.6).juger(
        "Quel délai ?",
        REFERENCE,
        ["Une formulation sans rapport.", REFERENCE],
    )
    assert verdict.conforme


def test_juge_lexical_sans_reference():
    verdict = JugeLexical().juger("Quel délai ?", "Peu importe.", [])
    assert not verdict.conforme
    assert verdict.confiance == 0.0


def test_lecture_du_verdict_json():
    verdict = _lire_verdict(
        'Voici : {"conforme": true, "confiance": 0.8, "motif": "ok"}'
    )
    assert verdict.conforme
    assert verdict.confiance == 0.8


def test_verdict_illisible_envoie_en_revue():
    verdict = _lire_verdict("je ne sais pas répondre")
    assert not verdict.conforme
    assert verdict.confiance == 0.0


def _backend(reponse: httpx.Response, modele="jina-embeddings-v5-nano"):
    transport = httpx.MockTransport(lambda requete: reponse)
    return JinaEmbeddings(
        cle_api="factice",
        modele=modele,
        url_base="https://api.exemple.fr/v1",
        client=httpx.Client(transport=transport),
    )


def test_modele_disponible():
    backend = _backend(
        httpx.Response(200, json={"data": [{"id": "jina-embeddings-v5-nano"}]})
    )
    backend.verifier_modele()


def test_modele_absent_echoue_avec_un_message_clair():
    backend = _backend(
        httpx.Response(200, json={"data": [{"id": "autre-modele"}]})
    )
    with pytest.raises(ModeleIndisponibleError, match="autre-modele"):
        backend.verifier_modele()


def test_service_indisponible_echoue_avec_un_message_clair():
    backend = _backend(httpx.Response(503, text="indisponible"))
    with pytest.raises(ModeleIndisponibleError, match="503"):
        backend.verifier_modele()
