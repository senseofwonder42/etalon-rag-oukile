"""Génère les jeux de données factices de `data/samples/`.

Aucune donnée réelle, aucun nom de personne existant. Les occurrences de
production mélangent volontairement des questions identiques à
l'existant, des reformulations, des questions inédites, et des réponses
correctes, presque correctes ou fausses.
"""

import argparse
import json
from pathlib import Path

from loguru import logger

DOSSIER_DEFAUT = Path("data/samples")

CG_AUTO = "cg_auto_2024.pdf"
CG_HAB = "cg_habitation_2024.pdf"
GUIDE = "guide_sinistres_2025.pdf"
AVENANT = "avenant_bris_glace_2024.pdf"

VERSIONS = {
    CG_AUTO: "sha1:9f3c1a2b7d40",
    CG_HAB: "sha1:41d8ec5590aa",
    GUIDE: "sha1:0b7742c3e118",
    AVENANT: "sha1:c62f5a90d331",
}


def _source(doc_id: str, page: int) -> dict:
    """Construit une source factice.

    Args:
        doc_id: Nom du document.
        page: Numéro de page.

    Returns:
        La source, avec la version courante du document.
    """
    return {
        "doc_id": doc_id,
        "page": page,
        "doc_version": VERSIONS[doc_id],
    }


REFERENTIEL = [
    {
        "question": (
            "Quel est le délai de déclaration d'un sinistre auto ?"
        ),
        "answers": [
            "Vous devez déclarer un sinistre auto dans un délai de "
            "**5 jours ouvrés** à compter du jour où vous en avez eu "
            "connaissance.",
            "Le délai de déclaration d'un sinistre automobile est de "
            "**5 jours ouvrés** après la survenance du sinistre.",
        ],
        "sources": [_source(CG_AUTO, 12)],
    },
    {
        "question": "Quel est le délai de déclaration d'un vol de véhicule ?",
        "answers": [
            "En cas de vol du véhicule, la déclaration doit être faite "
            "sous **2 jours ouvrés**, après dépôt de plainte auprès des "
            "services de police ou de gendarmerie.",
        ],
        "sources": [_source(CG_AUTO, 14), _source(GUIDE, 3)],
    },
    {
        "question": "Comment déclarer un dégât des eaux dans mon logement ?",
        "answers": [
            "Déclarez le dégât des eaux dans les **5 jours ouvrés** :\n\n"
            "- coupez l'arrivée d'eau et limitez l'aggravation ;\n"
            "- remplissez un constat amiable dégât des eaux avec le "
            "voisin concerné ;\n"
            "- transmettez photos et factures des biens endommagés.",
            "Le dégât des eaux se déclare sous **5 jours ouvrés**, avec "
            "un constat amiable si un tiers est impliqué et les "
            "justificatifs des dommages.",
        ],
        "sources": [_source(CG_HAB, 22), _source(GUIDE, 7)],
    },
    {
        "question": "Quelle est la franchise en cas de bris de glace ?",
        "answers": [
            "La franchise bris de glace est de **90 euros** pour un "
            "remplacement et *nulle* en cas de simple réparation d'impact.",
        ],
        "sources": [_source(AVENANT, 2)],
    },
    {
        "question": "Mon contrat auto couvre-t-il le prêt de volant ?",
        "answers": [
            "Le prêt de volant est couvert pour tout conducteur titulaire "
            "du permis depuis plus de **3 ans**. Une franchise majorée de "
            "**200 euros** s'applique en cas de sinistre responsable.",
            "Oui, un conducteur occasionnel est garanti s'il détient le "
            "permis depuis au moins **3 ans** ; la franchise est alors "
            "majorée de **200 euros** si vous êtes responsable.",
        ],
        "sources": [_source(CG_AUTO, 31)],
    },
    {
        "question": (
            "Que couvre la garantie responsabilité civile habitation ?"
        ),
        "answers": [
            "La responsabilité civile habitation couvre les dommages "
            "**corporels et matériels** causés à des tiers par vous, les "
            "personnes vivant sous votre toit et vos animaux domestiques.",
        ],
        "sources": [_source(CG_HAB, 5)],
    },
    {
        "question": "Comment résilier mon contrat d'assurance habitation ?",
        "answers": [
            "Après **un an** de contrat, la résiliation est possible à "
            "tout moment, sans frais ni justificatif, avec un préavis "
            "d'**un mois**. La demande se fait par lettre recommandée ou "
            "par voie électronique.",
            "Passé la première année, vous résiliez quand vous voulez : "
            "*préavis d'un mois*, par lettre recommandée ou en ligne, sans "
            "avoir à motiver la demande.",
            "La résiliation infra-annuelle s'applique dès la deuxième "
            "année : **un mois de préavis**, sans frais.",
        ],
        "sources": [_source(CG_HAB, 40)],
    },
    {
        "question": "Suis-je couvert en cas de catastrophe naturelle ?",
        "answers": [
            "La garantie catastrophe naturelle joue après publication de "
            "l'arrêté au *Journal officiel*. Vous disposez alors de "
            "**30 jours** pour déclarer, avec une franchise légale de "
            "**380 euros**.",
        ],
        "sources": [_source(CG_HAB, 28), _source(GUIDE, 11)],
    },
    {
        "question": (
            "Quels documents fournir après un accident avec constat "
            "amiable ?"
        ),
        "answers": [
            "Transmettez :\n\n"
            "- le **constat amiable** signé par les deux conducteurs ;\n"
            "- la copie du permis et de la carte grise ;\n"
            "- les photos des dommages et, le cas échéant, le procès-"
            "verbal des forces de l'ordre.",
        ],
        "sources": [_source(GUIDE, 5), _source(CG_AUTO, 18)],
    },
    {
        "question": (
            "Le vol de vélo est-il couvert par l'assurance habitation ?"
        ),
        "answers": [
            "Le vol de vélo est couvert **à l'intérieur du logement** et "
            "dans ses dépendances fermées. Hors du domicile, il faut "
            "l'option *mobilité douce*, plafonnée à **1 500 euros**.",
        ],
        "sources": [_source(CG_HAB, 33)],
    },
    {
        "question": (
            "Quel est le délai d'indemnisation après un sinistre auto ?"
        ),
        "answers": [
            "L'indemnisation intervient dans un délai de **30 jours** "
            "après accord sur le montant, ou après remise du rapport "
            "d'expertise.",
        ],
        "sources": [_source(CG_AUTO, 46)],
    },
    {
        "question": (
            "Ma franchise s'applique-t-elle en cas d'accident non "
            "responsable ?"
        ),
        "answers": [
            "Si vous n'êtes **pas responsable** et que le tiers est "
            "identifié, aucune franchise ne reste à votre charge.",
            "Aucune franchise n'est retenue lorsque votre responsabilité "
            "n'est pas engagée et que l'auteur des dommages est identifié.",
        ],
        "sources": [_source(CG_AUTO, 21)],
    },
]


RUN_PROD = [
    # --- Question identique, réponse conforme ---------------------------
    {
        "run_id": "run_101",
        "timestamp": "2026-07-18T09:12:00Z",
        "question": "Quel est le délai de déclaration d'un sinistre auto ?",
        "answer_markdown": (
            "Vous devez déclarer un sinistre auto dans un délai de "
            "**5 jours ouvrés** à compter du jour où vous en avez eu "
            "connaissance."
        ),
        "sources": [_source(CG_AUTO, 12)],
    },
    # --- Même run, même question : deux occurrences appariées pareil ----
    {
        "run_id": "run_101",
        "timestamp": "2026-07-18T09:14:00Z",
        "question": "Quel est le délai de déclaration d'un sinistre auto ?",
        "answer_markdown": (
            "Le délai est de **5 jours ouvrés** après la survenance du "
            "sinistre automobile."
        ),
        "sources": [_source(CG_AUTO, 12)],
    },
    # --- Reformulations -------------------------------------------------
    {
        "run_id": "run_102",
        "timestamp": "2026-07-18T09:20:00Z",
        "question": (
            "Sous quel délai dois-je déclarer un accident de voiture ?"
        ),
        "answer_markdown": (
            "Le délai de déclaration d'un sinistre automobile est de "
            "**5 jours ouvrés** après la survenance du sinistre."
        ),
        "sources": [_source(CG_AUTO, 12)],
    },
    {
        "run_id": "run_103",
        "timestamp": "2026-07-18T09:31:00Z",
        "question": "En combien de temps faut-il déclarer un vol de voiture ?",
        "answer_markdown": (
            "En cas de vol du véhicule, la déclaration doit être faite "
            "sous **5 jours ouvrés** après le dépôt de plainte."
        ),
        "sources": [_source(CG_AUTO, 14)],
    },
    {
        "run_id": "run_104",
        "timestamp": "2026-07-18T09:44:00Z",
        "question": "Comment faire pour résilier mon assurance habitation ?",
        "answer_markdown": (
            "Passé la première année, vous résiliez quand vous voulez :\n\n"
            "- *préavis d'un mois* ;\n"
            "- par lettre recommandée ou en ligne ;\n"
            "- **sans frais** ni justificatif."
        ),
        "sources": [_source(CG_HAB, 40)],
    },
    {
        "run_id": "run_105",
        "timestamp": "2026-07-18T09:58:00Z",
        "question": "Un dégât des eaux, comment je le déclare ?",
        "answer_markdown": (
            "Le dégât des eaux se déclare sous **5 jours ouvrés**, avec "
            "un constat amiable si un tiers est impliqué et les "
            "justificatifs des dommages."
        ),
        "sources": [_source(CG_HAB, 22)],
    },
    {
        "run_id": "run_106",
        "timestamp": "2026-07-18T10:05:00Z",
        "question": "Le prêt de volant est-il garanti par mon contrat ?",
        "answer_markdown": (
            "Oui, un conducteur occasionnel est garanti s'il détient le "
            "permis depuis au moins **2 ans** ; la franchise est alors "
            "majorée de **200 euros** si vous êtes responsable."
        ),
        "sources": [_source(CG_AUTO, 31)],
    },
    # --- Réponses presque correctes ou fausses --------------------------
    {
        "run_id": "run_107",
        "timestamp": "2026-07-18T10:17:00Z",
        "question": "Quelle est la franchise en cas de bris de glace ?",
        "answer_markdown": (
            "La franchise bris de glace s'élève à **150 euros**, quelle "
            "que soit la nature de l'intervention."
        ),
        "sources": [_source(AVENANT, 2)],
    },
    {
        "run_id": "run_108",
        "timestamp": "2026-07-18T10:22:00Z",
        "question": "Suis-je couvert en cas de catastrophe naturelle ?",
        "answer_markdown": (
            "La garantie catastrophe naturelle joue dès la survenance de "
            "l'événement, *sans arrêté*, et **sans franchise**."
        ),
        "sources": [_source(CG_HAB, 28)],
    },
    {
        "run_id": "run_109",
        "timestamp": "2026-07-18T10:30:00Z",
        "question": (
            "Ma franchise s'applique-t-elle en cas d'accident non "
            "responsable ?"
        ),
        "answer_markdown": (
            "Si vous n'êtes **pas responsable** et que le tiers est "
            "identifié, aucune franchise ne reste à votre charge."
        ),
        "sources": [_source(CG_AUTO, 21)],
    },
    {
        "run_id": "run_110",
        "timestamp": "2026-07-18T10:41:00Z",
        "question": "Le vol de mon vélo est-il pris en charge ?",
        "answer_markdown": (
            "Le vol de vélo est couvert **partout**, sans plafond ni "
            "option particulière."
        ),
        "sources": [_source(CG_HAB, 33)],
    },
    # --- Questions inédites ---------------------------------------------
    {
        "run_id": "run_111",
        "timestamp": "2026-07-18T10:52:00Z",
        "question": "Comment ajouter un conducteur secondaire à mon contrat ?",
        "answer_markdown": (
            "Pour ajouter un conducteur secondaire :\n\n"
            "1. transmettez son permis et son relevé d'information ;\n"
            "2. un **avenant** est émis sous 48 heures ;\n"
            "3. la cotisation est *recalculée* au prorata."
        ),
        "sources": [_source(CG_AUTO, 9)],
    },
    {
        "run_id": "run_112",
        "timestamp": "2026-07-18T11:03:00Z",
        "question": "Mon assurance habitation couvre-t-elle le télétravail ?",
        "answer_markdown": (
            "Le matériel professionnel utilisé à domicile est couvert "
            "jusqu'à **2 000 euros**, à condition d'avoir déclaré "
            "l'activité de télétravail."
        ),
        "sources": [_source(CG_HAB, 17)],
    },
    {
        "run_id": "run_113",
        "timestamp": "2026-07-18T11:12:00Z",
        "question": (
            "Que faire si mon expert n'est pas d'accord avec le devis ?"
        ),
        "answer_markdown": (
            "Vous pouvez demander une **contre-expertise** à vos frais, "
            "puis une *tierce expertise* si le désaccord persiste."
        ),
        "sources": [_source(GUIDE, 19)],
    },
    # --- Question tronquée : cas limite ---------------------------------
    {
        "run_id": "run_114",
        "timestamp": "2026-07-18T11:20:00Z",
        "question": "   ",
        "answer_markdown": "Réponse sans question exploitable.",
        "sources": [],
    },
]


def ecrire_jsonl(chemin: Path, lignes: list[dict]) -> None:
    """Écrit des enregistrements au format JSONL.

    Args:
        chemin: Fichier de destination.
        lignes: Enregistrements à écrire.
    """
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("w", encoding="utf-8") as fichier:
        for ligne in lignes:
            fichier.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    logger.info("{} lignes écrites dans {}", len(lignes), chemin)


def main() -> None:
    """Point d'entrée du générateur."""
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--dossier",
        type=Path,
        default=DOSSIER_DEFAUT,
        help="Dossier de destination des fichiers JSONL.",
    )
    arguments = analyseur.parse_args()
    ecrire_jsonl(
        arguments.dossier / "referentiel_initial.jsonl", REFERENTIEL
    )
    ecrire_jsonl(arguments.dossier / "run_prod.jsonl", RUN_PROD)


if __name__ == "__main__":
    main()
