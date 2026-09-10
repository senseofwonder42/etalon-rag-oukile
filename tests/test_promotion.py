import pytest

from rag_referentiel.config import Parametres
from rag_referentiel.referentiel import (
    CibleIntrouvableError,
    ajouter_variante,
    charger_entrees,
    creer_entree,
    creer_projet,
    importer_entrees,
    parser_sources,
    promouvoir_lot,
    remplacer_formulation,
    retirer_formulations,
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


# --- option A : correction ciblée d'une formulation -------------------
def _label_referentiel(**jobs):
    reponse = {"ENTREE_TOUJOURS_VALIDE": {"categories": [{"name": "OUI"}]}}
    if "cible" in jobs:
        reponse["FORMULATION_CIBLE"] = {
            "categories": [{"name": jobs["cible"]}]
        }
    if "texte" in jobs:
        reponse["REPONSE_VALIDEE"] = {"text": jobs["texte"]}
    if "retirer" in jobs:
        reponse["FORMULATIONS_A_RETIRER"] = {
            "categories": [{"name": r} for r in jobs["retirer"]]
        }
    if "sources" in jobs:
        reponse["SOURCES_CORRIGEES"] = {"text": jobs["sources"]}
    return reponse


@pytest.fixture
def entree_a_trois_formulations(kili, config):
    id_a = creer_projet(kili, "Référentiel")
    entree = creer_entree(
        question=QUESTION,
        textes=[
            "Le délai est de cinq jours ouvrés après le sinistre.",
            "Vous disposez de cinq jours ouvrés pour déclarer.",
            "La déclaration intervient sous cinq jours ouvrés.",
        ],
        sources=[Source(doc_id="cg_auto.pdf", page=12)],
        auteur="c.durand",
        date="2026-03-11",
    )
    importer_entrees(kili, id_a, [entree], config.taille_max_metadata)
    id_b = creer_projet_revue(kili, "Revue")
    return id_a, id_b, entree.question_id


def test_remplacement_cible_corrige_la_bonne_formulation(
    kili, config, entree_a_trois_formulations
):
    id_a, id_b, question_id = entree_a_trois_formulations
    kili.ajouter_label(
        id_a,
        question_id,
        _label_referentiel(
            cible="a2", texte="Vous disposez de cinq jours ouvrés pleins."
        ),
        auteur="c.durand@exemple.fr",
        date="2026-08-01",
    )

    rapport = promouvoir_lot(kili, id_a, id_b, config)

    entree = charger_entrees(kili, id_a)[0]
    assert rapport.formulations_remplacees == 1
    assert len(entree.answers) == 3
    assert entree.answers[1].id == "a2"
    assert entree.answers[1].text.endswith("cinq jours ouvrés pleins.")
    assert entree.answers[1].origine == "metier"
    assert entree.answers[1].auteur == "c.durand@exemple.fr"
    assert entree.answers[0].text.startswith("Le délai est de")
    assert entree.version == 2


def test_correction_legere_n_est_plus_perdue(
    kili, config, entree_a_trois_formulations
):
    id_a, id_b, question_id = entree_a_trois_formulations
    # Texte quasi identique à a2 : sans repère il serait écarté comme
    # quasi-doublon ; avec le repère, il remplace bien la formulation.
    kili.ajouter_label(
        id_a,
        question_id,
        _label_referentiel(
            cible="a2", texte="Vous disposez de cinq jours ouvrés pour agir."
        ),
    )

    promouvoir_lot(kili, id_a, id_b, config)

    entree = charger_entrees(kili, id_a)[0]
    assert entree.answers[1].text.endswith("pour agir.")


def test_sans_repere_le_texte_est_ajoute(
    kili, config, entree_a_trois_formulations
):
    id_a, id_b, question_id = entree_a_trois_formulations
    kili.ajouter_label(
        id_a,
        question_id,
        _label_referentiel(
            texte="Comptez cinq jours ouvrables, dimanche exclu, dès "
            "connaissance du fait générateur."
        ),
    )

    rapport = promouvoir_lot(kili, id_a, id_b, config)

    entree = charger_entrees(kili, id_a)[0]
    assert rapport.variantes_ajoutees == 1
    assert len(entree.answers) == 4
    assert entree.answers[3].id == "a4"


def test_repere_introuvable_signale_sans_planter(
    kili, config, entree_a_trois_formulations
):
    id_a, id_b, question_id = entree_a_trois_formulations
    kili.ajouter_label(
        id_a,
        question_id,
        _label_referentiel(cible="a5", texte="Un texte quelconque."),
    )

    rapport = promouvoir_lot(kili, id_a, id_b, config)

    assert rapport.formulations_remplacees == 0
    assert rapport.cibles_introuvables
    assert "a5" in rapport.cibles_introuvables[0]
    assert len(charger_entrees(kili, id_a)[0].answers) == 3


def test_retrait_multiple_et_renumerotation(
    kili, config, entree_a_trois_formulations
):
    id_a, id_b, question_id = entree_a_trois_formulations
    kili.ajouter_label(
        id_a, question_id, _label_referentiel(retirer=["a1", "a3"])
    )

    rapport = promouvoir_lot(kili, id_a, id_b, config)

    entree = charger_entrees(kili, id_a)[0]
    assert rapport.formulations_retirees == 2
    assert [r.id for r in entree.answers] == ["a1"]
    assert entree.answers[0].text.startswith("Vous disposez")


def test_deux_labels_successifs_sont_tous_consommes(
    kili, config, entree_a_trois_formulations
):
    id_a, id_b, question_id = entree_a_trois_formulations
    kili.ajouter_label(
        id_a,
        question_id,
        _label_referentiel(cible="a1", texte="Première correction ouvrés."),
        date="2026-08-01",
    )
    kili.ajouter_label(
        id_a,
        question_id,
        _label_referentiel(cible="a3", texte="Seconde correction ouvrés."),
        date="2026-08-02",
    )

    rapport = promouvoir_lot(kili, id_a, id_b, config)

    entree = charger_entrees(kili, id_a)[0]
    assert rapport.labels_referentiel_consommes == 2
    assert rapport.formulations_remplacees == 2
    assert entree.answers[0].text == "Première correction ouvrés."
    assert entree.answers[2].text == "Seconde correction ouvrés."
    assert entree.derniere_promotion.startswith("2026-08-02")


def test_le_filigrane_rend_la_campagne_idempotente(
    kili, config, entree_a_trois_formulations
):
    id_a, id_b, question_id = entree_a_trois_formulations
    kili.ajouter_label(
        id_a,
        question_id,
        _label_referentiel(cible="a2", texte="Une correction ouvrés."),
    )

    promouvoir_lot(kili, id_a, id_b, config)
    apres_un = charger_entrees(kili, id_a)[0].model_dump()
    rapport = promouvoir_lot(kili, id_a, id_b, config)

    assert rapport.labels_referentiel_consommes == 0
    assert charger_entrees(kili, id_a)[0].model_dump() == apres_un


def test_un_label_posterieur_au_filigrane_est_repris(
    kili, config, entree_a_trois_formulations
):
    id_a, id_b, question_id = entree_a_trois_formulations
    kili.ajouter_label(
        id_a,
        question_id,
        _label_referentiel(cible="a2", texte="Correction ouvrés initiale."),
        date="2026-08-01",
    )
    promouvoir_lot(kili, id_a, id_b, config)

    kili.ajouter_label(
        id_a,
        question_id,
        _label_referentiel(cible="a2", texte="Correction ouvrés suivante."),
        date="2026-08-05",
    )
    rapport = promouvoir_lot(kili, id_a, id_b, config)

    assert rapport.labels_referentiel_consommes == 1
    assert (
        charger_entrees(kili, id_a)[0].answers[1].text
        == "Correction ouvrés suivante."
    )


def test_sources_corrigees_signalent_les_sources_retirees(
    kili, config, entree_a_trois_formulations
):
    id_a, id_b, question_id = entree_a_trois_formulations
    kili.ajouter_label(
        id_a, question_id, _label_referentiel(sources="guide.pdf:5")
    )

    rapport = promouvoir_lot(kili, id_a, id_b, config)

    assert rapport.sources_retirees == [f"{question_id} : cg_auto.pdf:12"]


# --- règles pures : remplacement, retrait, sources multipages ---------
def test_remplacer_formulation_sans_changement():
    entree = creer_entree(QUESTION, ["Texte."], [], "c.d", "2026-01-01")
    assert not remplacer_formulation(
        entree, "a1", "Texte.", "m.leroy", "2026-07-18", 0.85
    )


def test_remplacer_formulation_cible_inconnue():
    entree = creer_entree(QUESTION, ["Texte."], [], "c.d", "2026-01-01")
    with pytest.raises(CibleIntrouvableError, match="a3"):
        remplacer_formulation(
            entree, "a3", "Autre.", "m.leroy", "2026-07-18", 0.85
        )


def test_retirer_la_derniere_formulation_est_refuse():
    entree = creer_entree(QUESTION, ["Texte."], [], "c.d", "2026-01-01")
    retires, introuvables = retirer_formulations(entree, ["a1"])
    assert retires == []
    assert introuvables == []
    assert len(entree.answers) == 1


def test_retirer_un_repere_inconnu_est_signale():
    entree = creer_entree(
        QUESTION, ["Un.", "Deux."], [], "c.d", "2026-01-01"
    )
    retires, introuvables = retirer_formulations(entree, ["a2", "a9"])
    assert retires == ["Deux."]
    assert introuvables == ["a9"]


def test_renumerotation_apres_retrait():
    entree = creer_entree(
        QUESTION, ["Un.", "Deux.", "Trois."], [], "c.d", "2026-01-01"
    )
    retirer_formulations(entree, ["a2"])
    assert [r.id for r in entree.answers] == ["a1", "a2"]
    assert [r.text for r in entree.answers] == ["Un.", "Trois."]


def test_sources_plusieurs_pages_d_un_meme_document():
    sources, illisibles = parser_sources("doc1.pdf:p12, p14, p31")
    assert [(s.doc_id, s.page) for s in sources] == [
        ("doc1.pdf", 12),
        ("doc1.pdf", 14),
        ("doc1.pdf", 31),
    ]
    assert illisibles == []


def test_sources_pages_multiples_puis_changement_de_document():
    sources, _ = parser_sources("doc1.pdf:p12, p14, autre.pdf:2, p7")
    assert [(s.doc_id, s.page) for s in sources] == [
        ("doc1.pdf", 12),
        ("doc1.pdf", 14),
        ("autre.pdf", 2),
        ("autre.pdf", 7),
    ]


def test_page_seule_sans_document_precedent_est_illisible():
    sources, illisibles = parser_sources("p12, doc.pdf:3")
    assert [(s.doc_id, s.page) for s in sources] == [("doc.pdf", 3)]
    assert illisibles == ["p12"]
