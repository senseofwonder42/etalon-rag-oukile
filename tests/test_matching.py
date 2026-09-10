import pytest

from rag_referentiel.embeddings import FakeEmbeddings, similarite_cosinus
from rag_referentiel.matching import (
    HybridMatcher,
    LexicalMatcher,
    decider,
    similarite_lexicale,
)
from rag_referentiel.schemas import EntreeReferentiel

QUESTIONS = [
    "Quel est le délai de déclaration d'un sinistre auto ?",
    "Comment résilier mon contrat d'assurance habitation ?",
    "Quelle est la franchise en cas de bris de glace ?",
]


def entrees():
    return [
        EntreeReferentiel(question_id=f"q_{i}", question=question)
        for i, question in enumerate(QUESTIONS)
    ]


def test_match_sur_question_identique():
    matcher = LexicalMatcher(entrees(), 0.72, 0.45)
    resultat = matcher.apparier(QUESTIONS[0])
    assert resultat.decision == "MATCH"
    assert resultat.question_id == "q_0"
    assert resultat.score == pytest.approx(1.0)


def test_nouvelle_sur_question_inedite():
    matcher = LexicalMatcher(entrees(), 0.72, 0.45)
    resultat = matcher.apparier("Comment ajouter un conducteur ?")
    assert resultat.decision == "NOUVELLE"
    assert resultat.question_id is None


def test_incertain_entre_les_deux_seuils():
    matcher = LexicalMatcher(entrees(), 0.72, 0.45)
    resultat = matcher.apparier("Comment résilier un contrat ?")
    assert resultat.decision == "INCERTAIN"
    assert 0.45 <= resultat.score < 0.72


def test_referentiel_vide_donne_nouvelle():
    matcher = LexicalMatcher([], 0.72, 0.45)
    resultat = matcher.apparier("Une question quelconque ?")
    assert resultat.decision == "NOUVELLE"
    assert resultat.score == 0.0


def test_question_vide_donne_nouvelle():
    matcher = LexicalMatcher(entrees(), 0.72, 0.45)
    assert matcher.apparier("  ").decision == "NOUVELLE"


@pytest.mark.parametrize(
    ("score", "attendu"),
    [
        (0.9, "MATCH"),
        (0.7, "MATCH"),
        (0.6999, "INCERTAIN"),
        (0.4, "INCERTAIN"),
        (0.3999, "NOUVELLE"),
    ],
)
def test_bornes_des_seuils(score, attendu):
    resultat = decider(
        entrees()[:1], [score], {"lexical": [score]}, 0.7, 0.4
    )
    assert resultat.decision == attendu


def test_hybride_combine_les_deux_scores():
    matcher = HybridMatcher(
        entrees(), FakeEmbeddings(), 0.72, 0.45, 0.4, 0.6
    )
    resultat = matcher.apparier(QUESTIONS[2])
    assert resultat.decision == "MATCH"
    assert set(resultat.scores) == {"lexical", "semantique"}
    attendu = (
        0.4 * resultat.scores["lexical"]
        + 0.6 * resultat.scores["semantique"]
    )
    assert resultat.score == pytest.approx(attendu, abs=1e-3)


def test_hybride_refuse_des_poids_nuls():
    with pytest.raises(ValueError, match="poids"):
        HybridMatcher(entrees(), FakeEmbeddings(), 0.7, 0.4, 0.0, 0.0)


def test_hybride_sur_referentiel_vide():
    matcher = HybridMatcher([], FakeEmbeddings(), 0.72, 0.45)
    assert matcher.apparier("Une question ?").decision == "NOUVELLE"


def test_fake_embeddings_deterministe():
    backend = FakeEmbeddings()
    assert backend.encoder(["délai auto"]) == backend.encoder(
        ["délai auto"]
    )
    proche = similarite_cosinus(
        backend.encoder(["délai de déclaration sinistre"])[0],
        backend.encoder(["délai de déclaration"])[0],
    )
    loin = similarite_cosinus(
        backend.encoder(["délai de déclaration sinistre"])[0],
        backend.encoder(["résiliation du contrat habitation"])[0],
    )
    assert proche > loin


def test_similarite_lexicale():
    assert similarite_lexicale("délai auto", "delai auto") == 1.0
    assert similarite_lexicale("délai auto", "") == 0.0
    assert 0.0 < similarite_lexicale("délai auto", "délai moto") < 1.0
