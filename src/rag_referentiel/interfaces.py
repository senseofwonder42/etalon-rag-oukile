"""Les deux `json_interface` Kili, en projets TEXT.

Rappel de contrainte : la version 2.142.1 du SDK ne connaît aucun type de
projet LLM. Les jobs sont donc uniquement des `CLASSIFICATION` et des
`TRANSCRIPTION`, et aucune clé `level` n'apparaît (elle est propre aux
projets LLM, absents de cette version).
"""

FORMAT_SOURCES = "doc.pdf:12, autre.pdf:3"
#: Plusieurs pages d'un même document : répéter la page seule, préfixée
#: par « p », après le document.
FORMAT_SOURCES_MULTIPAGE = "doc.pdf:p12, p14, autre.pdf:3"
#: Repères des formulations, tels qu'affichés sur la carte. Le plafond de
#: variantes étant de 5 et les repères renumérotés à chaque écriture, la
#: liste est finie et stable.
REPERES_FORMULATIONS = ("a1", "a2", "a3", "a4", "a5")


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


def _job_cases_a_cocher(
    instruction: str, categories: dict[str, str], requis: bool
) -> dict:
    """Construit un job de classification à choix multiple.

    Args:
        instruction: Consigne affichée à l'annotateur.
        categories: Correspondance code de catégorie -> libellé affiché.
        requis: Si le job doit être rempli pour pouvoir valider.

    Returns:
        Le dictionnaire de job attendu par Kili.
    """
    job = _job_radio(instruction, categories, requis)
    job["content"]["input"] = "checkbox"
    return job


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
        "FORMULATION_CIBLE": _job_radio(
            instruction=(
                "Pour corriger une formulation existante, choisir son "
                "repère tel qu'il apparaît sur la carte, puis écrire le "
                "texte corrigé ci-dessous. Laisser vide pour ajouter une "
                "nouvelle formulation."
            ),
            categories={
                repere: repere for repere in REPERES_FORMULATIONS
            },
            requis=False,
        ),
        "REPONSE_VALIDEE": _job_transcription(
            instruction=(
                "Texte de la formulation : elle remplace la formulation "
                "désignée ci-dessus, ou s'ajoute aux formulations "
                "existantes si aucun repère n'est choisi."
            ),
            requis=False,
        ),
        "FORMULATIONS_A_RETIRER": _job_cases_a_cocher(
            instruction=(
                "Repères des formulations à retirer du référentiel "
                "(plusieurs choix possibles)."
            ),
            categories={
                repere: repere for repere in REPERES_FORMULATIONS
            },
            requis=False,
        ),
        "SOURCES_CORRIGEES": _job_transcription(
            instruction=(
                "Liste corrigée des sources, qui **remplace** la liste "
                f"actuelle. Format « {FORMAT_SOURCES} » ; plusieurs pages "
                f"d'un même document : « {FORMAT_SOURCES_MULTIPAGE} ». "
                "Laisser vide si rien à changer."
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
                "Liste corrigée des sources, qui **remplace** la liste "
                f"citée. Format « {FORMAT_SOURCES} » ; plusieurs pages "
                f"d'un même document : « {FORMAT_SOURCES_MULTIPAGE} »."
            ),
            requis=False,
        ),
    }
}
