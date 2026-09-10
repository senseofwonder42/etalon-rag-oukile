"""Briques de base du format rich text des assets TEXT de Kili.

Un asset rich text est un arbre de nœuds :

- un **nœud élément** porte `children` et un `type` parmi
  `ELEMENTS_AUTORISES` ;
- un **nœud texte** porte `text` et un `id` unique dans tout le document,
  éventuellement assorti de marques (`bold`, `italic`, `code`,
  `underline`).

Les deux acceptent des styles CSS (`backgroundColor`, `color`, `padding`…).
Le SDK ne valide rien : il sérialise l'arbre et le téléverse.
"""

ELEMENTS_AUTORISES = frozenset(
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

MARQUES_AUTORISEES = frozenset({"bold", "italic", "code", "underline"})


class GenerateurIds:
    """Générateur déterministe d'identifiants de nœuds texte.

    Un même générateur doit être utilisé pour tout un document : les `id`
    des nœuds texte doivent y être uniques. Le compteur étant déterministe,
    deux rendus des mêmes données produisent exactement le même arbre, ce
    qui permet de les comparer dans les tests.
    """

    def __init__(self, prefixe: str = "n") -> None:
        """Initialise le générateur.

        Args:
            prefixe: Préfixe des identifiants produits.
        """
        self._prefixe = prefixe
        self._compteur = 0

    def suivant(self) -> str:
        """Produit l'identifiant suivant.

        Returns:
            Un identifiant de la forme `n1`, `n2`, …
        """
        self._compteur += 1
        return f"{self._prefixe}{self._compteur}"


def noeud_texte(
    texte: str,
    generateur: GenerateurIds,
    marques: frozenset[str] | set[str] | None = None,
    styles: dict[str, str] | None = None,
) -> dict:
    """Construit un nœud texte.

    Args:
        texte: Contenu textuel du nœud.
        generateur: Générateur d'identifiants du document courant.
        marques: Marques à appliquer, parmi `MARQUES_AUTORISEES`.
        styles: Styles CSS supplémentaires.

    Returns:
        Le nœud texte, prêt à être sérialisé.

    Raises:
        ValueError: Si une marque inconnue est demandée.
    """
    noeud: dict = {"id": generateur.suivant(), "text": texte}
    for marque in sorted(marques or ()):
        if marque not in MARQUES_AUTORISEES:
            raise ValueError(f"Marque inconnue : {marque}")
        noeud[marque] = True
    noeud.update(styles or {})
    return noeud


def noeud_element(
    type_: str,
    enfants: list[dict],
    generateur: GenerateurIds,
    styles: dict[str, str] | None = None,
) -> dict:
    """Construit un nœud élément.

    Args:
        type_: Type de l'élément, parmi `ELEMENTS_AUTORISES`.
        enfants: Nœuds enfants ; un nœud texte vide est ajouté si la liste
            est vide, un élément sans enfant n'ayant rien à rendre.
        generateur: Générateur d'identifiants du document courant.
        styles: Styles CSS supplémentaires.

    Returns:
        Le nœud élément, prêt à être sérialisé.

    Raises:
        ValueError: Si le type d'élément n'est pas supporté par Kili.
    """
    if type_ not in ELEMENTS_AUTORISES:
        raise ValueError(f"Type d'élément inconnu : {type_}")
    contenu = enfants or [noeud_texte("", generateur)]
    noeud: dict = {"type": type_, "children": contenu}
    noeud.update(styles or {})
    return noeud


def document(
    enfants: list[dict], styles: dict[str, str] | None = None
) -> list[dict]:
    """Enveloppe des nœuds de bloc dans la racine d'un document rich text.

    Args:
        enfants: Nœuds de premier niveau du document.
        styles: Styles CSS appliqués à la racine.

    Returns:
        Le `json_content` complet, tel qu'attendu par Kili.
    """
    racine: dict = {"children": enfants}
    racine.update(styles or {})
    return [racine]
