import pytest
from pydantic import ValidationError

from rag_referentiel.schemas import (
    Answer,
    CasRevue,
    EntreeReferentiel,
    Source,
    Verdict,
)
from rag_referentiel.storage import (
    alleger_metadata,
    ecrire_avec_repli,
    est_erreur_de_volume,
    preparer_charge,
    taille_metadata,
)


def entree():
    return EntreeReferentiel(
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


def test_statut_par_defaut_et_valeurs_admises():
    assert entree().statut == "ACTIF"
    with pytest.raises(ValidationError):
        EntreeReferentiel(
            question_id="q", question="?", statut="INCONNU"
        )


def test_origine_contrainte():
    with pytest.raises(ValidationError):
        Answer(
            id="a1",
            text="x",
            origine="contre_exemple",
            auteur="a",
            date="2026-01-01",
        )


def test_source_sans_page():
    source = Source(doc_id="cg.pdf")
    assert source.page is None
    assert source.libelle() == "cg.pdf"
    assert Source(doc_id="cg.pdf", page=3).libelle() == "cg.pdf:3"


def test_verdict_confiance_bornee():
    with pytest.raises(ValidationError):
        Verdict(conforme=True, confiance=1.5, motif="x")


def test_cas_revue_motif_contraint():
    with pytest.raises(ValidationError):
        CasRevue(
            question_id="q",
            run_id="r",
            motif="AUTRE",
            question="?",
            candidate_answer="x",
        )


def test_charge_sous_le_seuil_reste_complete():
    charge = preparer_charge(entree().model_dump(), [{"children": []}], 10**6)
    assert charge.repli is False
    assert charge.json_metadata["answers"][0]["text"]


def test_charge_au_dessus_du_seuil_est_allegee():
    metadata = entree().model_dump()
    charge = preparer_charge(metadata, [{"children": []}], 200)
    assert charge.repli is True
    assert "text" not in charge.json_metadata["answers"][0]
    assert charge.json_metadata["repli_texte"] is True
    assert charge.json_metadata["question"] == metadata["question"]
    assert taille_metadata(charge.json_metadata) < taille_metadata(metadata)


def test_alleger_retire_la_reponse_candidate():
    allegee = alleger_metadata(
        {"question_id": "q", "candidate_answer": "x" * 100}
    )
    assert "candidate_answer" not in allegee
    assert allegee["repli_texte"] is True


def test_est_erreur_de_volume():
    assert est_erreur_de_volume(RuntimeError("Payload too large"))
    assert not est_erreur_de_volume(RuntimeError("Not found"))


def test_ecriture_rejouee_avec_metadata_allegee():
    tentatives = []

    def ecriture(charge):
        tentatives.append(charge)
        if not charge.repli:
            raise RuntimeError("request entity too large")
        return "écrit"

    resultat = ecrire_avec_repli(
        ecriture, entree().model_dump(), [{"children": []}], 10**6
    )
    assert resultat == "écrit"
    assert [t.repli for t in tentatives] == [False, True]


def test_erreur_sans_rapport_avec_le_volume_est_propagee():
    def ecriture(charge):
        del charge
        raise RuntimeError("authentication failed")

    with pytest.raises(RuntimeError, match="authentication"):
        ecrire_avec_repli(
            ecriture, entree().model_dump(), [{"children": []}], 10**6
        )
