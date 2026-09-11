"""The two Kili `json_interface` definitions, for TEXT projects.

Constraint reminder: version 2.142.1 of the SDK knows no LLM project
type. Jobs are therefore only `CLASSIFICATION` and `TRANSCRIPTION`, and
no `level` key appears — that key belongs to LLM projects, absent from
this version.

Job names, category codes and every displayed string stay in French: they
are the interface the business team reads.
"""

from .rendering import answer_label

#: Format de saisie des sources : un document par fragment, ses pages
#: après le deux-points, séparées par des espaces.
SOURCES_FORMAT = "doc.pdf:12 14, autre.pdf:3"
#: Repères des formulations, tels qu'affichés sur la carte. Le plafond de
#: variantes étant de 5 et les repères renumérotés à chaque écriture, la
#: liste est finie et stable.
ANSWER_MARKERS = ("a1", "a2", "a3", "a4", "a5")


def _answer_categories() -> dict[str, str]:
    """Build the answer categories, labelled as they are on the card.

    Returns:
        A mapping of marker to displayed label, `a2` -> `Réponse 2`.
    """
    return {marker: answer_label(marker) for marker in ANSWER_MARKERS}


def _radio_job(
    instruction: str, categories: dict[str, str], required: bool
) -> dict:
    """Build a single-choice classification job.

    Args:
        instruction: Guidance displayed to the annotator.
        categories: Mapping of category code to displayed label.
        required: Whether the job must be filled to submit.

    Returns:
        The job dictionary expected by Kili.
    """
    return {
        "mlTask": "CLASSIFICATION",
        "instruction": instruction,
        "required": 1 if required else 0,
        "isChild": False,
        "content": {
            "categories": {
                code: {"name": label, "children": []}
                for code, label in categories.items()
            },
            "input": "radio",
        },
    }


def _checkbox_job(
    instruction: str, categories: dict[str, str], required: bool
) -> dict:
    """Build a multiple-choice classification job.

    Args:
        instruction: Guidance displayed to the annotator.
        categories: Mapping of category code to displayed label.
        required: Whether the job must be filled to submit.

    Returns:
        The job dictionary expected by Kili.
    """
    job = _radio_job(instruction, categories, required)
    job["content"]["input"] = "checkbox"
    return job


def _transcription_job(instruction: str, required: bool) -> dict:
    """Build a free text transcription job.

    Args:
        instruction: Guidance displayed to the annotator.
        required: Whether the job must be filled to submit.

    Returns:
        The job dictionary expected by Kili.
    """
    return {
        "mlTask": "TRANSCRIPTION",
        "instruction": instruction,
        "required": 1 if required else 0,
        "isChild": False,
        "content": {"input": "textField"},
    }


REFERENCE_INTERFACE: dict = {
    "jobs": {
        "ENTREE_TOUJOURS_VALIDE": _radio_job(
            instruction=(
                "Cette entrée du référentiel est-elle toujours valide au "
                "regard des documents actuels ?"
            ),
            categories={"OUI": "Oui", "NON": "Non"},
            required=True,
        ),
        "FORMULATION_CIBLE": _radio_job(
            instruction=(
                "Pour corriger une formulation existante, choisir son "
                "numéro tel qu'il apparaît sur la carte, puis écrire le "
                "texte corrigé ci-dessous. Laisser vide pour ajouter une "
                "nouvelle formulation."
            ),
            categories=_answer_categories(),
            required=False,
        ),
        "REPONSE_VALIDEE": _transcription_job(
            instruction=(
                "Texte de la formulation : elle remplace la formulation "
                "désignée ci-dessus, ou s'ajoute aux formulations "
                "existantes si aucun repère n'est choisi."
            ),
            required=False,
        ),
        "FORMULATIONS_A_RETIRER": _checkbox_job(
            instruction=(
                "Numéros des formulations à retirer du référentiel "
                "(plusieurs choix possibles)."
            ),
            categories=_answer_categories(),
            required=False,
        ),
        "SOURCES_CORRIGEES": _transcription_job(
            instruction=(
                "Liste corrigée des sources, qui **remplace** la liste "
                f"actuelle. Format « {SOURCES_FORMAT} » : un document par "
                "élément, ses pages après le deux-points, séparées par des "
                "espaces. La liste actuelle est rappelée en bas de la "
                "carte, prête à copier-coller. Laisser vide si rien à "
                "changer."
            ),
            required=False,
        ),
    }
}

REVIEW_INTERFACE: dict = {
    "jobs": {
        "MEME_QUESTION": _radio_job(
            instruction=(
                "À remplir uniquement si le motif de mise en revue est "
                "« APPARIEMENT_INCERTAIN » : la question posée est-elle bien "
                "la même que la question du référentiel proposée en bas de "
                "la carte ?"
            ),
            categories={"OUI": "Oui", "NON": "Non"},
            required=False,
        ),
        "CANDIDATE_CORRECTE": _radio_job(
            instruction="La réponse générée est-elle correcte ?",
            categories={
                "OUI": "Oui",
                "PRESQUE": "Presque",
                "NON": "Non",
            },
            required=True,
        ),
        "VERSION_CORRIGEE": _transcription_job(
            instruction=(
                "Si « Presque » : écrire ici la bonne formulation de la "
                "réponse."
            ),
            required=False,
        ),
        "SOURCES_PERTINENTES": _radio_job(
            instruction=(
                "Les sources citées soutiennent-elles la réponse ?"
            ),
            categories={
                "OUI": "Oui",
                "PARTIEL": "Partiellement",
                "NON": "Non",
            },
            required=True,
        ),
        "SOURCES_CORRIGEES": _transcription_job(
            instruction=(
                "Liste corrigée des sources, qui **remplace** la liste "
                f"citée. Format « {SOURCES_FORMAT} » : un document par "
                "élément, ses pages après le deux-points, séparées par des "
                "espaces. La liste citée est rappelée en bas de la carte, "
                "prête à copier-coller."
            ),
            required=False,
        ),
    }
}
