from rag_referentiel.rendering import (
    rendu_asset_referentiel,
    rendu_asset_revue,
)
from rag_referentiel.schemas import (
    Answer,
    CasRevue,
    EntreeReferentiel,
    Source,
    Verdict,
)


def noeuds(document):
    pile = list(document)
    while pile:
        noeud = pile.pop()
        yield noeud
        pile.extend(noeud.get("children", []))


def entree():
    return EntreeReferentiel(
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


def cas(motif="DIVERGENCE"):
    return CasRevue(
        question_id="q_abc",
        run_id="run_42",
        motif=motif,
        question="Quel est le délai ?",
        candidate_answer="Vous disposez de **5 jours ouvrés**.",
        sources=[Source(doc_id="cg_auto.pdf", page=12)],
        verdict_juge=Verdict(
            conforme=False, confiance=0.31, motif="chiffre divergent"
        ),
        question_id_candidat="q_candidat",
    )


def test_rendu_referentiel_structure():
    document = rendu_asset_referentiel(entree())
    types = [n.get("type") for n in noeuds(document) if "type" in n]
    assert "h1" in types
    assert "table" in types
    contenu = " ".join(n["text"] for n in noeuds(document) if "text" in n)
    assert "Quel est le délai ?" in contenu
    assert "c.durand" in contenu


def test_rendu_revue_n_affiche_jamais_le_verdict_du_juge():
    document = rendu_asset_revue(cas(), [entree().answers[0]])
    contenu = " ".join(n["text"] for n in noeuds(document) if "text" in n)
    assert "chiffre divergent" not in contenu
    assert "0.31" not in contenu
    assert "conforme" not in contenu.lower()


def test_rendu_revue_colore_les_reponses():
    document = rendu_asset_revue(cas(), [entree().answers[0]])
    fonds = {
        n["backgroundColor"]
        for n in noeuds(document)
        if "backgroundColor" in n
    }
    assert "#e8f5e9" in fonds
    assert "#fff3e0" in fonds


def test_rendu_revue_affiche_la_question_candidate_si_incertain():
    document = rendu_asset_revue(
        cas("APPARIEMENT_INCERTAIN"),
        [],
        question_candidate="Une autre question ?",
    )
    contenu = " ".join(n["text"] for n in noeuds(document) if "text" in n)
    assert "Une autre question ?" in contenu


def test_identifiants_uniques_dans_chaque_rendu():
    for document in (
        rendu_asset_referentiel(entree()),
        rendu_asset_revue(cas(), [entree().answers[0]]),
    ):
        identifiants = [n["id"] for n in noeuds(document) if "id" in n]
        assert len(identifiants) == len(set(identifiants))


def test_rendu_deterministe():
    assert rendu_asset_referentiel(entree()) == rendu_asset_referentiel(
        entree()
    )
