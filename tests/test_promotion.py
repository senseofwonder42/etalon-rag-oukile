import pytest

from rag_referentiel.config import Parametres
from rag_referentiel.referentiel import (
    ajouter_variante,
    charger_entrees,
    creer_entree,
    creer_projet,
    importer_entrees,
    parser_sources,
    promouvoir_lot,
    selectionner_variantes,
)
from rag_referentiel.revue import (
    calculer_identifiants,
    creer_cas,
)
from rag_referentiel.revue import (
    creer_projet as creer_projet_revue,
)
from rag_referentiel.schemas import Answer, CasRevue, Source, Verdict

QUESTION = "Quel est le délai de déclaration d'un sinistre auto ?"
REPONSE_METIER = "Le délai est de cinq jours ouvrés après le sinistre."


@pytest.fixture
def config():
    return Parametres(
        kili_api_key="factice",
        seuil_quasi_doublon=0.85,
        plafond_variantes=5,
    )


@pytest.fixture
def projets(kili, config):
    id_a = creer_projet(kili, "Référentiel")
    entree = creer_entree(
        question=QUESTION,
        textes=[REPONSE_METIER],
        sources=[Source(doc_id="cg_auto.pdf", page=12)],
        auteur="c.durand",
        date="2026-03-11",
    )
    importer_entrees(kili, id_a, [entree], config.taille_max_metadata)
    id_b = creer_projet_revue(kili, "Revue")
    return id_a, id_b, entree.question_id


def deposer_cas(kili, id_b, config, **surcharges):
    cas = CasRevue(
        **{
            "question_id": surcharges.pop("question_id"),
            "run_id": "run_42",
            "motif": "DIVERGENCE",
            "question": QUESTION,
            "candidate_answer": "Vous avez cinq jours ouvrés.",
            "sources": [Source(doc_id="cg_auto.pdf", page=12)],
            "verdict_juge": Verdict(
                conforme=False, confiance=0.4, motif="test"
            ),
            "score_appariement": 0.9,
            **surcharges,
        }
    )
    identifiants = calculer_identifiants([cas])
    creer_cas(
        kili, id_b, [cas], identifiants, {}, {}, config.taille_max_metadata
    )
    return identifiants[0]


def test_verdict_oui_ajoute_une_variante(kili, config, projets):
    id_a, id_b, question_id = projets
    external_id = deposer_cas(kili, id_b, config, question_id=question_id)
    kili.ajouter_label(
        id_b,
        external_id,
        {
            "CANDIDATE_CORRECTE": {"categories": [{"name": "OUI"}]},
            "SOURCES_PERTINENTES": {"categories": [{"name": "OUI"}]},
        },
        auteur="m.leroy@exemple.fr",
    )

    rapport = promouvoir_lot(kili, id_a, id_b, config)

    assert rapport.promus == 1
    assert rapport.variantes_ajoutees == 1
    entree = charger_entrees(kili, id_a)[0]
    assert len(entree.answers) == 2
    assert entree.answers[1].origine == "rag_valide"
    assert entree.answers[1].auteur == "m.leroy@exemple.fr"
    assert entree.answers[1].run_id == "run_42"
    assert entree.version == 2
    assert kili.metadata(id_b, external_id)["statut_revue"] == "PROMU"


def test_verdict_presque_promeut_la_version_corrigee(kili, config, projets):
    id_a, id_b, question_id = projets
    external_id = deposer_cas(kili, id_b, config, question_id=question_id)
    kili.ajouter_label(
        id_b,
        external_id,
        {
            "CANDIDATE_CORRECTE": {"categories": [{"name": "PRESQUE"}]},
            "VERSION_CORRIGEE": {
                "text": "Cinq jours ouvrés, hors vol et hors catastrophe."
            },
            "SOURCES_PERTINENTES": {"categories": [{"name": "OUI"}]},
        },
    )

    promouvoir_lot(kili, id_a, id_b, config)

    entree = charger_entrees(kili, id_a)[0]
    assert entree.answers[1].origine == "rag_corrige"
    assert "hors vol" in entree.answers[1].text


def test_verdict_presque_sans_correction_n_ecrit_rien(kili, config, projets):
    id_a, id_b, question_id = projets
    external_id = deposer_cas(kili, id_b, config, question_id=question_id)
    kili.ajouter_label(
        id_b,
        external_id,
        {
            "CANDIDATE_CORRECTE": {"categories": [{"name": "PRESQUE"}]},
            "SOURCES_PERTINENTES": {"categories": [{"name": "NON"}]},
        },
    )

    rapport = promouvoir_lot(kili, id_a, id_b, config)

    assert rapport.rejetes == 1
    assert len(charger_entrees(kili, id_a)[0].answers) == 1
    assert kili.metadata(id_b, external_id)["statut_revue"] == "REJETE"


def test_verdict_non_n_ecrit_rien(kili, config, projets):
    id_a, id_b, question_id = projets
    external_id = deposer_cas(kili, id_b, config, question_id=question_id)
    kili.ajouter_label(
        id_b,
        external_id,
        {
            "CANDIDATE_CORRECTE": {"categories": [{"name": "NON"}]},
            "SOURCES_PERTINENTES": {"categories": [{"name": "NON"}]},
        },
    )

    rapport = promouvoir_lot(kili, id_a, id_b, config)

    entree = charger_entrees(kili, id_a)[0]
    assert rapport.rejetes == 1
    assert len(entree.answers) == 1
    assert entree.version == 1
    assert kili.metadata(id_b, external_id)["statut_revue"] == "REJETE"


def test_meme_question_non_cree_une_nouvelle_entree(kili, config, projets):
    id_a, id_b, _ = projets
    external_id = deposer_cas(
        kili,
        id_b,
        config,
        question_id="q_nouvelle_000",
        motif="APPARIEMENT_INCERTAIN",
        question="Quel délai pour déclarer un vol de véhicule ?",
        question_id_candidat="q_existante",
    )
    kili.ajouter_label(
        id_b,
        external_id,
        {
            "MEME_QUESTION": {"categories": [{"name": "NON"}]},
            "CANDIDATE_CORRECTE": {"categories": [{"name": "OUI"}]},
            "SOURCES_PERTINENTES": {"categories": [{"name": "OUI"}]},
        },
    )

    rapport = promouvoir_lot(kili, id_a, id_b, config)

    assert rapport.nouvelles_entrees == 1
    questions = {e.question for e in charger_entrees(kili, id_a)}
    assert "Quel délai pour déclarer un vol de véhicule ?" in questions


def test_cas_incertain_sans_reponse_reste_en_attente(kili, config, projets):
    id_a, id_b, _ = projets
    external_id = deposer_cas(
        kili,
        id_b,
        config,
        question_id="q_nouvelle_000",
        motif="APPARIEMENT_INCERTAIN",
        question_id_candidat="q_existante",
    )
    kili.ajouter_label(
        id_b,
        external_id,
        {"CANDIDATE_CORRECTE": {"categories": [{"name": "OUI"}]}},
    )

    rapport = promouvoir_lot(kili, id_a, id_b, config)

    assert rapport.ignores == 1
    assert kili.metadata(id_b, external_id)["statut_revue"] == "EN_ATTENTE"


def test_promotion_idempotente(kili, config, projets):
    id_a, id_b, question_id = projets
    external_id = deposer_cas(kili, id_b, config, question_id=question_id)
    kili.ajouter_label(
        id_b,
        external_id,
        {
            "CANDIDATE_CORRECTE": {"categories": [{"name": "OUI"}]},
            "SOURCES_PERTINENTES": {"categories": [{"name": "OUI"}]},
        },
    )

    promouvoir_lot(kili, id_a, id_b, config)
    apres_un = charger_entrees(kili, id_a)[0]
    rapport = promouvoir_lot(kili, id_a, id_b, config)
    apres_deux = charger_entrees(kili, id_a)[0]

    assert rapport.cas_lus == 0
    assert apres_deux.model_dump() == apres_un.model_dump()


def test_variante_identique_rejetee_comme_quasi_doublon(
    kili, config, projets
):
    id_a, id_b, question_id = projets
    external_id = deposer_cas(
        kili,
        id_b,
        config,
        question_id=question_id,
        candidate_answer=REPONSE_METIER,
    )
    kili.ajouter_label(
        id_b,
        external_id,
        {
            "CANDIDATE_CORRECTE": {"categories": [{"name": "OUI"}]},
            "SOURCES_PERTINENTES": {"categories": [{"name": "OUI"}]},
        },
    )

    rapport = promouvoir_lot(kili, id_a, id_b, config)

    entree = charger_entrees(kili, id_a)[0]
    assert rapport.variantes_ajoutees == 0
    assert len(entree.answers) == 1
    assert entree.version == 1


def test_sources_corrigees_remplacent_les_sources(kili, config, projets):
    id_a, id_b, question_id = projets
    external_id = deposer_cas(kili, id_b, config, question_id=question_id)
    kili.ajouter_label(
        id_b,
        external_id,
        {
            "CANDIDATE_CORRECTE": {"categories": [{"name": "OUI"}]},
            "SOURCES_PERTINENTES": {"categories": [{"name": "PARTIEL"}]},
            "SOURCES_CORRIGEES": {"text": "cg_auto.pdf:14, guide.pdf:3"},
        },
    )

    promouvoir_lot(kili, id_a, id_b, config)

    entree = charger_entrees(kili, id_a)[0]
    assert [(s.doc_id, s.page) for s in entree.sources] == [
        ("cg_auto.pdf", 14),
        ("guide.pdf", 3),
    ]


def test_desaccord_juge_metier_compte(kili, config, projets):
    id_a, id_b, question_id = projets
    external_id = deposer_cas(kili, id_b, config, question_id=question_id)
    kili.ajouter_label(
        id_b,
        external_id,
        {
            "CANDIDATE_CORRECTE": {"categories": [{"name": "OUI"}]},
            "SOURCES_PERTINENTES": {"categories": [{"name": "OUI"}]},
        },
    )

    rapport = promouvoir_lot(kili, id_a, id_b, config)

    assert rapport.desaccords_juge_metier == 1


def test_entree_toujours_valide_repasse_l_entree_en_actif(
    kili, config, projets
):
    id_a, id_b, question_id = projets
    metadata = kili.metadata(id_a, question_id)
    metadata["statut"] = "A_REVERIFIER"
    kili.ajouter_label(
        id_a,
        question_id,
        {"ENTREE_TOUJOURS_VALIDE": {"categories": [{"name": "OUI"}]}},
        date="2026-08-01",
    )

    rapport = promouvoir_lot(kili, id_a, id_b, config)

    entree = charger_entrees(kili, id_a)[0]
    assert rapport.entrees_revalidees == 1
    assert entree.statut == "ACTIF"
    assert entree.derniere_verification == "2026-08-01"

    # Rejouer ne doit plus rien changer.
    avant = entree.model_dump()
    promouvoir_lot(kili, id_a, id_b, config)
    assert charger_entrees(kili, id_a)[0].model_dump() == avant


def test_entree_toujours_valide_non_archive(kili, config, projets):
    id_a, id_b, question_id = projets
    kili.ajouter_label(
        id_a,
        question_id,
        {"ENTREE_TOUJOURS_VALIDE": {"categories": [{"name": "NON"}]}},
    )

    rapport = promouvoir_lot(kili, id_a, id_b, config)

    assert rapport.entrees_archivees == 1
    assert charger_entrees(kili, id_a)[0].statut == "ARCHIVE"


# --- règles pures ----------------------------------------------------
def _reponse(identifiant, texte, origine="rag_valide"):
    return Answer(
        id=identifiant,
        text=texte,
        origine=origine,
        auteur="m.leroy",
        date="2026-07-18",
    )


def test_plafond_de_variantes(config):
    entree = creer_entree(
        QUESTION,
        [REPONSE_METIER],
        [],
        "c.durand",
        "2026-03-11",
    )
    for indice in range(6):
        ajoutee = ajouter_variante(
            entree,
            texte=f"Formulation numéro {indice} totalement distincte "
            f"mot{indice} autre{indice} encore{indice}",
            origine="rag_valide",
            auteur="m.leroy",
            date="2026-07-18",
            run_id=f"run_{indice}",
            seuil_quasi_doublon=config.seuil_quasi_doublon,
            plafond=config.plafond_variantes,
        )
        assert ajoutee or len(entree.answers) == config.plafond_variantes
    assert len(entree.answers) == config.plafond_variantes
    assert entree.answers[0].origine == "metier"


def test_selection_conserve_la_formulation_metier():
    reponses = [
        _reponse("a1", "alpha beta gamma", origine="metier"),
        _reponse("a2", "alpha beta delta"),
        _reponse("a3", "epsilon zeta eta"),
    ]
    retenues = selectionner_variantes(reponses, 2)
    assert [r.id for r in retenues] == ["a1", "a3"]


def test_variante_vide_ignoree(config):
    entree = creer_entree(QUESTION, [REPONSE_METIER], [], "c.d", "2026-01-01")
    assert not ajouter_variante(
        entree,
        texte="   ",
        origine="rag_valide",
        auteur="m.leroy",
        date="2026-07-18",
        run_id=None,
        seuil_quasi_doublon=config.seuil_quasi_doublon,
        plafond=config.plafond_variantes,
    )


def test_parser_sources_tolerant():
    sources, illisibles = parser_sources(
        "cg_auto.pdf:12, guide.pdf, autre.pdf:page, , cg_hab.pdf:3"
    )
    assert [(s.doc_id, s.page) for s in sources] == [
        ("cg_auto.pdf", 12),
        ("guide.pdf", None),
        ("cg_hab.pdf", 3),
    ]
    assert illisibles == ["autre.pdf:page"]


def test_la_piste_d_audit_n_est_pas_relue_comme_un_arbitrage(
    kili, config, projets
):
    id_a, id_b, question_id = projets
    external_id = deposer_cas(kili, id_b, config, question_id=question_id)
    kili.ajouter_label(
        id_b,
        external_id,
        {
            "CANDIDATE_CORRECTE": {"categories": [{"name": "OUI"}]},
            "SOURCES_PERTINENTES": {"categories": [{"name": "OUI"}]},
        },
    )
    promouvoir_lot(kili, id_a, id_b, config)

    labels = kili.donnees[id_a][question_id]["labels"]
    assert labels and labels[-1]["labelType"] == "INFERENCE"
    assert labels[-1]["jsonResponse"]["REPONSE_VALIDEE"]["text"]
