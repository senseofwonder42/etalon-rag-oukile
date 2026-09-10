"""Les deux `json_interface` Kili, en projets TEXT.

Rappel de contrainte : la version 2.142.1 du SDK ne connaît aucun type de
projet LLM. Les jobs sont donc uniquement des `CLASSIFICATION` et des
`TRANSCRIPTION`, et aucune clé `level` n'apparaît (elle est propre aux
projets LLM, absents de cette version).
"""

FORMAT_SOURCES = "doc.pdf:12, autre.pdf:3"


def _job_radio(
    instruction: str, categories: dict[str, str], requis: bool
) -> dict:
    """Construit un job de classification à choix unique.

    Args:
        instruction: Consigne affichée à l'annotateur.
        categories: Correspondance code de catégorie -> libellé affiché.
        requis: Si le job doit être rempli pour pouvoir valider.

    Returns:
        Le dictionnaire de job attendu par Kili.
    """
    return {
        "mlTask": "CLASSIFICATION",
        "instruction": instruction,
        "required": 1 if requis else 0,
        "isChild": False,
        "content": {
            "categories": {
                code: {"name": libelle, "children": []}
                for code, libelle in categories.items()
            },
            "input": "radio",
        },
    }


def _job_transcription(instruction: str, requis: bool) -> dict:
    """Construit un job de transcription texte libre.

    Args:
        instruction: Consigne affichée à l'annotateur.
        requis: Si le job doit être rempli pour pouvoir valider.

    Returns:
        Le dictionnaire de job attendu par Kili.
    """
    return {
        "mlTask": "TRANSCRIPTION",
        "instruction": instruction,
        "required": 1 if requis else 0,
        "isChild": False,
        "content": {"input": "textField"},
    }


INTERFACE_REFERENTIEL: dict = {
    "jobs": {
        "ENTREE_TOUJOURS_VALIDE": _job_radio(
            instruction=(
                "Cette entrée du référentiel est-elle toujours valide au "
                "regard des documents actuels ?"
            ),
            categories={"OUI": "Oui", "NON": "Non"},
            requis=True,
        ),
        "REPONSE_VALIDEE": _job_transcription(
            instruction=(
                "Ajouter ou corriger une formulation validée de la réponse "
                "(laisser vide si rien à changer)."
            ),
            requis=False,
        ),
        "SOURCES_CORRIGEES": _job_transcription(
            instruction=(
                "Sources corrigées, au format "
                f"« {FORMAT_SOURCES} » (laisser vide si rien à changer)."
            ),
            requis=False,
        ),
    }
}

INTERFACE_REVUE: dict = {
    "jobs": {
        "MEME_QUESTION": _job_radio(
            instruction=(
                "À remplir uniquement si le motif de mise en revue est "
                "« APPARIEMENT_INCERTAIN » : la question posée est-elle bien "
                "la même que la question du référentiel proposée en bas de "
                "la carte ?"
            ),
            categories={"OUI": "Oui", "NON": "Non"},
            requis=False,
        ),
        "CANDIDATE_CORRECTE": _job_radio(
            instruction="La réponse générée est-elle correcte ?",
            categories={
                "OUI": "Oui",
                "PRESQUE": "Presque",
                "NON": "Non",
            },
            requis=True,
        ),
        "VERSION_CORRIGEE": _job_transcription(
            instruction=(
                "Si « Presque » : écrire ici la bonne formulation de la "
                "réponse."
            ),
            requis=False,
        ),
        "SOURCES_PERTINENTES": _job_radio(
            instruction=(
                "Les sources citées soutiennent-elles la réponse ?"
            ),
            categories={
                "OUI": "Oui",
                "PARTIEL": "Partiellement",
                "NON": "Non",
            },
            requis=True,
        ),
        "SOURCES_CORRIGEES": _job_transcription(
            instruction=(
                "Sources corrigées, au format "
                f"« {FORMAT_SOURCES} » (laisser vide si rien à changer)."
            ),
            requis=False,
        ),
    }
}
