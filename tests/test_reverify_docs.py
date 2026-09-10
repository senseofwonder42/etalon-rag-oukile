import json

import pytest
import reverify_docs

from rag_referentiel.config import Parametres
from rag_referentiel.referentiel import (
    charger_entrees,
    creer_entree,
    creer_projet,
    importer_entrees,
)
from rag_referentiel.schemas import Source

VERSIONS = {
    "cg_auto.pdf": "sha1:aaa",
    "cg_hab.pdf": "sha1:bbb",
}


@pytest.fixture
def config():
    return Parametres(kili_api_key="factice")


@pytest.fixture
def projet(kili, config):
    entrees = [
        creer_entree(
            "Délai de déclaration auto ?",
            ["Cinq jours."],
            [Source(doc_id="cg_auto.pdf", page=12, doc_version="sha1:aaa")],
            "c.durand",
            "2026-03-11",
        ),
        creer_entree(
            "Résiliation habitation ?",
            ["Un mois de préavis."],
            [Source(doc_id="cg_hab.pdf", page=40, doc_version="sha1:vieux")],
            "c.durand",
            "2026-03-11",
        ),
        creer_entree(
            "Vol de vélo ?",
            ["Couvert au domicile."],
            [Source(doc_id="cg_hab.pdf", doc_version="sha1:bbb")],
            "c.durand",
            "2026-03-11",
        ),
    ]
    id_a = creer_projet(kili, "Référentiel")
    importer_entrees(kili, id_a, entrees, config.taille_max_metadata)
    return id_a, entrees


def test_entrees_derivantes(projet):
    _, entrees = projet
    derives = reverify_docs.entrees_derivantes(entrees, VERSIONS)
    assert len(derives) == 1
    assert derives[0]["question"] == "Résiliation habitation ?"
    assert derives[0]["sources_derivantes"][0]["version_courante"] == (
        "sha1:bbb"
    )


def test_entrees_impactees_par_document(projet):
    _, entrees = projet
    impactees = reverify_docs.entrees_impactees(
        entrees, ["cg_hab.pdf"], None
    )
    assert {e.question for e in impactees} == {
        "Résiliation habitation ?",
        "Vol de vélo ?",
    }


def test_entrees_impactees_par_intervalle_de_pages(projet):
    _, entrees = projet
    impactees = reverify_docs.entrees_impactees(
        entrees, ["cg_hab.pdf"], (10, 20)
    )
    # La source sans page reste retenue, l'intervalle ne peut l'écarter.
    assert {e.question for e in impactees} == {"Vol de vélo ?"}


def test_analyser_pages():
    assert reverify_docs.analyser_pages("10-20") == (10, 20)
    assert reverify_docs.analyser_pages(None) is None
    with pytest.raises(ValueError, match="illisible"):
        reverify_docs.analyser_pages("dix-vingt")
    with pytest.raises(ValueError, match="inversé"):
        reverify_docs.analyser_pages("20-10")


def _lancer(monkeypatch, kili, config, arguments):
    monkeypatch.setattr(reverify_docs, "parametres", lambda: config)
    monkeypatch.setattr(reverify_docs, "creer_client", lambda _: kili)
    monkeypatch.setattr("sys.argv", ["reverify_docs.py", *arguments])
    reverify_docs.main()


def test_dry_run_ne_modifie_rien(monkeypatch, kili, config, projet):
    id_a, _ = projet
    avant = [e.model_dump() for e in charger_entrees(kili, id_a)]

    _lancer(
        monkeypatch,
        kili,
        config,
        [
            "--projet-referentiel",
            id_a,
            "--declencher",
            "--doc",
            "cg_hab.pdf",
            "--dry-run",
        ],
    )

    assert [e.model_dump() for e in charger_entrees(kili, id_a)] == avant
    assert kili.appels == []


def test_declenchement_met_en_reverification(
    monkeypatch, kili, config, projet
):
    id_a, _ = projet

    _lancer(
        monkeypatch,
        kili,
        config,
        [
            "--projet-referentiel",
            id_a,
            "--declencher",
            "--doc",
            "cg_hab.pdf",
        ],
    )

    par_question = {
        e.question: e for e in charger_entrees(kili, id_a)
    }
    assert par_question["Résiliation habitation ?"].statut == "A_REVERIFIER"
    assert par_question["Résiliation habitation ?"].version == 2
    assert par_question["Délai de déclaration auto ?"].statut == "ACTIF"
    assert kili.appels and kili.appels[0][0] == "send_back_to_queue"
    assert all(
        asset["priority"] == reverify_docs.PRIORITE_REVERIFICATION
        for asset in kili.assets(id_a)
        if asset["jsonMetadata"]["statut"] == "A_REVERIFIER"
    )


def test_rapport_de_derive_ecrit_un_json(
    monkeypatch, kili, config, projet, tmp_path
):
    id_a, _ = projet
    versions = tmp_path / "versions.json"
    versions.write_text(json.dumps(VERSIONS), encoding="utf-8")
    sortie = tmp_path / "derive.json"

    _lancer(
        monkeypatch,
        kili,
        config,
        [
            "--projet-referentiel",
            id_a,
            "--rapport",
            "--versions",
            str(versions),
            "--sortie",
            str(sortie),
        ],
    )

    contenu = json.loads(sortie.read_text(encoding="utf-8"))
    assert contenu["entrees_examinees"] == 3
    assert len(contenu["entrees_derivantes"]) == 1
