"""Sonde le rendu rich text du serveur Kili avec un asset unique.

Importe un seul asset qui exerce tout le vocabulaire rich text : titres
`h1` à `h4`, gras, italique, code, souligné, listes, citation, tableau,
fonds de couleur et alignements. Sert à constater en cinq minutes ce que
l'instance rend réellement, avant de construire dessus.
"""

import argparse

from _commun import parametres
from loguru import logger

from rag_referentiel.client import creer_client
from rag_referentiel.interfaces import INTERFACE_REFERENTIEL
from rag_referentiel.richtext import (
    GenerateurIds,
    document,
    noeud_element,
    noeud_texte,
)

EXTERNAL_ID = "sonde_richtext"


def composer_sonde() -> list[dict]:
    """Compose l'asset de sonde.

    Returns:
        Le `json_content` de l'asset.
    """
    generateur = GenerateurIds()

    def paragraphe(
        enfants: list[dict], styles: dict[str, str] | None = None
    ) -> dict:
        return noeud_element("p", enfants, generateur, styles)

    def titre(niveau: str, texte: str) -> dict:
        return noeud_element(
            niveau, [noeud_texte(texte, generateur)], generateur
        )

    def cellule(texte: str, entete: bool = False) -> dict:
        return noeud_element(
            "td",
            [noeud_texte(texte, generateur, {"bold"} if entete else None)],
            generateur,
            {"backgroundColor": "#eeeeee"} if entete else None,
        )

    blocs = [
        titre("h1", "Sonde rich text — h1"),
        titre("h2", "Sous-titre — h2"),
        titre("h3", "Sous-titre — h3"),
        titre("h4", "Sous-titre — h4"),
        paragraphe(
            [
                noeud_texte("Normal, ", generateur),
                noeud_texte("gras", generateur, {"bold"}),
                noeud_texte(", ", generateur),
                noeud_texte("italique", generateur, {"italic"}),
                noeud_texte(", ", generateur),
                noeud_texte("code", generateur, {"code"}),
                noeud_texte(", ", generateur),
                noeud_texte("souligné", generateur, {"underline"}),
                noeud_texte(", ", generateur),
                noeud_texte(
                    "gras + italique", generateur, {"bold", "italic"}
                ),
                noeud_texte(".", generateur),
            ]
        ),
        paragraphe(
            [noeud_texte("Fond vert clair.", generateur)],
            {"backgroundColor": "#e8f5e9", "padding": "4px 8px"},
        ),
        paragraphe(
            [noeud_texte("Fond ambre.", generateur)],
            {"backgroundColor": "#fff3e0", "padding": "4px 8px"},
        ),
        paragraphe(
            [noeud_texte("Texte coloré et centré.", generateur)],
            {"color": "#c62828", "textAlign": "center"},
        ),
        paragraphe(
            [noeud_texte("Texte aligné à droite.", generateur)],
            {"textAlign": "right"},
        ),
        titre("h3", "Liste à puces"),
        noeud_element(
            "ul",
            [
                noeud_element(
                    "li", [noeud_texte("Premier point", generateur)],
                    generateur,
                ),
                noeud_element(
                    "li",
                    [
                        noeud_texte("Deuxième point en ", generateur),
                        noeud_texte("gras", generateur, {"bold"}),
                    ],
                    generateur,
                ),
            ],
            generateur,
        ),
        titre("h3", "Liste numérotée"),
        noeud_element(
            "ol",
            [
                noeud_element(
                    "li", [noeud_texte("Étape un", generateur)], generateur
                ),
                noeud_element(
                    "li", [noeud_texte("Étape deux", generateur)], generateur
                ),
            ],
            generateur,
        ),
        titre("h3", "Citation"),
        noeud_element(
            "blockquote",
            [paragraphe([noeud_texte("Une citation encadrée.", generateur)])],
            generateur,
            {"borderLeft": "3px solid #9e9e9e", "padding": "4px 8px"},
        ),
        titre("h3", "Tableau"),
        noeud_element(
            "table",
            [
                noeud_element(
                    "thead",
                    [
                        noeud_element(
                            "tr",
                            [
                                cellule("Document", True),
                                cellule("Page", True),
                            ],
                            generateur,
                        )
                    ],
                    generateur,
                ),
                noeud_element(
                    "tbody",
                    [
                        noeud_element(
                            "tr",
                            [
                                cellule("cg_auto_2024.pdf"),
                                cellule("12"),
                            ],
                            generateur,
                        ),
                        noeud_element(
                            "tr",
                            [
                                cellule("cg_habitation_2024.pdf"),
                                cellule("22"),
                            ],
                            generateur,
                        ),
                    ],
                    generateur,
                ),
            ],
            generateur,
        ),
    ]
    return document(blocs, {"maxWidth": "900px", "margin": "0 auto"})


def main() -> None:
    """Point d'entrée de la sonde."""
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--project-id",
        default=None,
        help="Projet TEXT existant ; créé si absent.",
    )
    arguments = analyseur.parse_args()

    config = parametres()
    kili = creer_client(config)
    project_id = arguments.project_id
    if project_id is None:
        project_id = kili.create_project(
            title="Sonde rich text",
            input_type="TEXT",
            json_interface=INTERFACE_REFERENTIEL,
            description="Vérification du rendu rich text côté serveur.",
        )["id"]
        logger.info("Projet de sonde créé : {}", project_id)

    kili.append_many_to_dataset(
        project_id=project_id,
        external_id_array=[EXTERNAL_ID],
        json_content_array=[composer_sonde()],
        json_metadata_array=[{"text": "Sonde du vocabulaire rich text."}],
    )
    print(f"Asset « {EXTERNAL_ID} » importé dans le projet {project_id}.")
    print(
        "Ouvrir l'asset et vérifier, dans l'ordre : niveaux de titre, "
        "marques\n(gras, italique, code, souligné), fonds de couleur, "
        "alignements,\nlistes, citation, tableau."
    )


if __name__ == "__main__":
    main()
