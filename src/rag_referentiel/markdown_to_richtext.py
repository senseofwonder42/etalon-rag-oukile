"""Conversion du markdown produit par la RAG en rich text Kili.

Le chemin est celui du convertisseur récursif publié par Kili dans le
notebook `recipes/import_text_assets.ipynb` : markdown -> HTML
(`markdown-it-py`) -> arbre de nœuds. Une règle est ajoutée : `strong`,
`em` et `code` en ligne deviennent des **marques** sur le nœud texte, et
non des éléments — Kili n'accepte pas ces types d'élément.

Sous-ensemble couvert : titres `h1`-`h4`, paragraphes, `ul` / `ol` / `li`,
`blockquote`, tableaux, gras, italique, code en ligne. Les autres
constructions ont un repli documenté (voir le README) et rien ne lève
d'exception : au pire le contenu retombe sur un paragraphe de texte brut.
"""

from dataclasses import dataclass, field
from html.parser import HTMLParser

from loguru import logger
from markdown_it import MarkdownIt

from .richtext import GenerateurIds, noeud_element, noeud_texte

#: Balises HTML rendues telles quelles comme éléments Kili.
BLOCS = frozenset(
    {
        "blockquote",
        "h1",
        "h2",
        "h3",
        "h4",
        "li",
        "ol",
        "p",
        "table",
        "tbody",
        "td",
        "thead",
        "tr",
        "ul",
    }
)

#: Balises en ligne converties en marques sur le nœud texte.
MARQUES = {
    "strong": "bold",
    "b": "bold",
    "em": "italic",
    "i": "italic",
    "code": "code",
    "u": "underline",
    "ins": "underline",
}

#: Balises sans contenu.
BALISES_VIDES = frozenset({"br", "hr", "img", "wbr"})

_TITRES_REPLIES = {"h5": "h4", "h6": "h4"}


@dataclass
class _Element:
    """Nœud d'un arbre HTML intermédiaire."""

    tag: str
    attributs: dict[str, str] = field(default_factory=dict)
    enfants: list["_Element | str"] = field(default_factory=list)


class _ConstructeurArbre(HTMLParser):
    """Assemble un arbre `_Element` à partir d'un flux HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.racine = _Element("racine")
        self._pile: list[_Element] = [self.racine]

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """Ouvre un élément (voir `html.parser`)."""
        element = _Element(tag, {k: v or "" for k, v in attrs})
        self._pile[-1].enfants.append(element)
        if tag not in BALISES_VIDES:
            self._pile.append(element)

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        """Traite une balise auto-fermante (voir `html.parser`)."""
        element = _Element(tag, {k: v or "" for k, v in attrs})
        self._pile[-1].enfants.append(element)

    def handle_endtag(self, tag: str) -> None:
        """Ferme un élément (voir `html.parser`)."""
        for indice in range(len(self._pile) - 1, 0, -1):
            if self._pile[indice].tag == tag:
                del self._pile[indice:]
                return

    def handle_data(self, data: str) -> None:
        """Ajoute un fragment de texte (voir `html.parser`)."""
        self._pile[-1].enfants.append(data)


def _analyser_html(html: str) -> _Element:
    """Construit l'arbre HTML intermédiaire.

    Args:
        html: Fragment HTML produit par `markdown-it-py`.

    Returns:
        La racine de l'arbre.
    """
    constructeur = _ConstructeurArbre()
    constructeur.feed(html)
    constructeur.close()
    return constructeur.racine


def _texte_brut(noeud: "_Element | str") -> str:
    """Concatène tout le texte d'un sous-arbre.

    Args:
        noeud: Élément ou fragment de texte.

    Returns:
        Le texte, sans balisage.
    """
    if isinstance(noeud, str):
        return noeud
    return "".join(_texte_brut(enfant) for enfant in noeud.enfants)


def _convertir_en_ligne(
    noeuds: list["_Element | str"],
    generateur: GenerateurIds,
    marques: frozenset[str],
) -> list[dict]:
    """Convertit une suite de nœuds en nœuds texte.

    Args:
        noeuds: Enfants d'un élément, en contexte de ligne.
        generateur: Générateur d'identifiants du document.
        marques: Marques héritées des éléments englobants.

    Returns:
        La liste des nœuds texte produits.
    """
    resultat: list[dict] = []
    for noeud in noeuds:
        if isinstance(noeud, str):
            if noeud:
                resultat.append(noeud_texte(noeud, generateur, marques))
        elif noeud.tag in MARQUES:
            resultat.extend(
                _convertir_en_ligne(
                    noeud.enfants, generateur, marques | {MARQUES[noeud.tag]}
                )
            )
        elif noeud.tag == "a":
            resultat.extend(
                _convertir_en_ligne(noeud.enfants, generateur, marques)
            )
            url = noeud.attributs.get("href", "")
            if url:
                resultat.append(
                    noeud_texte(f" ({url})", generateur, marques)
                )
        elif noeud.tag == "img":
            texte = noeud.attributs.get("alt") or "[image]"
            resultat.append(noeud_texte(texte, generateur, marques))
        elif noeud.tag == "br":
            resultat.append(noeud_texte("\n", generateur, marques))
        else:
            # Balise en ligne inconnue : on garde son texte.
            resultat.extend(
                _convertir_en_ligne(noeud.enfants, generateur, marques)
            )
    return resultat


def _convertir_bloc_de_code(
    element: _Element, generateur: GenerateurIds
) -> list[dict]:
    """Replie un bloc de code en paragraphes marqués `code`.

    Args:
        element: Élément `pre`.
        generateur: Générateur d'identifiants du document.

    Returns:
        Un paragraphe par ligne de code.
    """
    lignes = _texte_brut(element).rstrip("\n").split("\n")
    return [
        noeud_element(
            "p",
            [noeud_texte(ligne, generateur, {"code"})],
            generateur,
            {"backgroundColor": "#f5f5f5"},
        )
        for ligne in lignes
    ]


def _convertir_blocs(
    noeuds: list["_Element | str"],
    generateur: GenerateurIds,
    marques: frozenset[str],
) -> list[dict]:
    """Convertit une suite de nœuds en contexte de bloc.

    Les suites de contenu en ligne rencontrées entre deux blocs sont
    regroupées dans un paragraphe.

    Args:
        noeuds: Enfants d'un élément, en contexte de bloc.
        generateur: Générateur d'identifiants du document.
        marques: Marques héritées des éléments englobants.

    Returns:
        La liste des nœuds de bloc produits.
    """
    resultat: list[dict] = []
    tampon: list["_Element | str"] = []

    def vider_tampon() -> None:
        if not tampon:
            return
        textes = _convertir_en_ligne(tampon, generateur, marques)
        tampon.clear()
        if any(noeud["text"].strip() for noeud in textes):
            resultat.append(noeud_element("p", textes, generateur))

    for noeud in noeuds:
        est_bloc = isinstance(noeud, _Element) and (
            noeud.tag in BLOCS
            or noeud.tag in _TITRES_REPLIES
            or noeud.tag in {"pre", "hr", "th", "div"}
        )
        if not est_bloc:
            tampon.append(noeud)
            continue
        vider_tampon()
        resultat.extend(_convertir_element(noeud, generateur, marques))

    vider_tampon()
    return resultat


def _convertir_element(
    element: _Element,
    generateur: GenerateurIds,
    marques: frozenset[str],
) -> list[dict]:
    """Convertit un élément de bloc.

    Args:
        element: Élément HTML à convertir.
        generateur: Générateur d'identifiants du document.
        marques: Marques héritées des éléments englobants.

    Returns:
        La liste des nœuds Kili produits pour cet élément.
    """
    tag = _TITRES_REPLIES.get(element.tag, element.tag)

    if tag == "pre":
        return _convertir_bloc_de_code(element, generateur)

    if tag == "hr":
        return [
            noeud_element(
                "p", [noeud_texte("———", generateur)], generateur
            )
        ]

    if tag == "th":
        # Kili ne connaît pas `th` : on le rend comme un `td` en gras.
        return [
            noeud_element(
                "td",
                _convertir_en_ligne(
                    element.enfants, generateur, marques | {"bold"}
                ),
                generateur,
                {"backgroundColor": "#eeeeee"},
            )
        ]

    if tag in {"p", "h1", "h2", "h3", "h4", "td"}:
        return [
            noeud_element(
                tag,
                _convertir_en_ligne(element.enfants, generateur, marques),
                generateur,
            )
        ]

    if tag in {"ul", "ol", "table", "thead", "tbody", "tr", "li"}:
        return [
            noeud_element(
                tag,
                _convertir_blocs(element.enfants, generateur, marques)
                if tag != "li"
                else _convertir_contenu_li(element, generateur, marques),
                generateur,
            )
        ]

    if tag == "blockquote":
        return [
            noeud_element(
                "blockquote",
                _convertir_blocs(element.enfants, generateur, marques),
                generateur,
                {"borderLeft": "3px solid #9e9e9e", "padding": "4px 8px"},
            )
        ]

    # Construction inconnue : repli sur son contenu, en contexte de bloc.
    logger.debug("Balise non couverte, repli en texte brut : {}", element.tag)
    return _convertir_blocs(element.enfants, generateur, marques)


def _convertir_contenu_li(
    element: _Element,
    generateur: GenerateurIds,
    marques: frozenset[str],
) -> list[dict]:
    """Convertit le contenu d'un `li`.

    Un `li` dit « serré » ne contient que du texte, un `li` « lâche »
    contient des paragraphes et parfois une sous-liste.

    Args:
        element: Élément `li`.
        generateur: Générateur d'identifiants du document.
        marques: Marques héritées des éléments englobants.

    Returns:
        Les enfants du `li` : nœuds texte, paragraphes ou sous-listes.
    """
    contient_bloc = any(
        isinstance(enfant, _Element)
        and (enfant.tag in BLOCS or enfant.tag in {"pre", "div"})
        for enfant in element.enfants
    )
    if contient_bloc:
        return _convertir_blocs(element.enfants, generateur, marques)
    return _convertir_en_ligne(element.enfants, generateur, marques)


def markdown_vers_richtext(
    markdown: str, generateur: GenerateurIds
) -> list[dict]:
    """Convertit du markdown en nœuds de bloc rich text Kili.

    Args:
        markdown: Texte markdown produit par la RAG.
        generateur: Générateur d'identifiants du document courant, partagé
            avec le reste du rendu pour garantir l'unicité des `id`.

    Returns:
        La liste des nœuds de bloc. Toujours au moins un nœud : un
        markdown vide ou illisible retombe sur un paragraphe.
    """
    if not markdown.strip():
        return [noeud_element("p", [], generateur)]

    try:
        html = MarkdownIt("commonmark").enable("table").render(markdown)
        blocs = _convertir_blocs(
            _analyser_html(html).enfants, generateur, frozenset()
        )
    except Exception as erreur:  # noqa: BLE001 - repli volontaire
        logger.warning(
            "Markdown illisible, repli sur du texte brut : {}", erreur
        )
        blocs = []

    if not blocs:
        return [
            noeud_element(
                "p", [noeud_texte(markdown.strip(), generateur)], generateur
            )
        ]
    return blocs
