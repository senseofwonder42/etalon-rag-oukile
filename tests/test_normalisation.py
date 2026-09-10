import pytest

from rag_referentiel.normalisation import (
    calculer_external_id_revue,
    calculer_question_id,
    normaliser_question,
    tokeniser,
)


def test_normalisation_supprime_accents_casse_et_ponctuation():
    assert normaliser_question("Quel DÉLAI, déjà ?") == "quel delai deja"


def test_normalisation_reduit_les_espaces():
    assert normaliser_question("  a\t b\n\nc  ") == "a b c"


def test_normalisation_question_vide():
    assert normaliser_question("  ?? !! ") == ""


def test_question_id_stable_entre_formulations_equivalentes():
    gauche = calculer_question_id("Quel est le délai ?")
    droite = calculer_question_id("quel est le delai")
    assert gauche == droite
    assert gauche.startswith("q_")
    assert len(gauche) == len("q_") + 12


def test_question_id_differe_entre_questions_differentes():
    assert calculer_question_id("délai auto") != calculer_question_id(
        "délai habitation"
    )


def test_question_id_refuse_une_question_vide():
    with pytest.raises(ValueError, match="vide"):
        calculer_question_id("   ...   ")


def test_external_id_revue():
    assert (
        calculer_external_id_revue("q_abc", "run_42") == "q_abc__run_42"
    )


def test_tokeniser():
    assert tokeniser("Délai, déjà !") == ["delai", "deja"]
    assert tokeniser("  ") == []
