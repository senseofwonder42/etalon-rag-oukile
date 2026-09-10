from rag_referentiel.markdown_to_richtext import markdown_vers_richtext
from rag_referentiel.richtext import GenerateurIds


def convertir(markdown):
    return markdown_vers_richtext(markdown, GenerateurIds())


def types(blocs):
    return [bloc["type"] for bloc in blocs]


def textes(noeud):
    if "text" in noeud:
        return [noeud]
    resultat = []
    for enfant in noeud.get("children", []):
        resultat.extend(textes(enfant))
    return resultat


def test_titres_h1_a_h4():
    blocs = convertir("# un\n\n## deux\n\n### trois\n\n#### quatre")
    assert types(blocs) == ["h1", "h2", "h3", "h4"]


def test_titres_au_dela_de_h4_replient_sur_h4():
    assert types(convertir("##### cinq")) == ["h4"]


def test_paragraphe_et_marques_en_ligne():
    blocs = convertir("Du **gras**, de l'*italique* et du `code`.")
    assert types(blocs) == ["p"]
    marques = {
        noeud["text"]: {
            cle for cle in ("bold", "italic", "code") if noeud.get(cle)
        }
        for noeud in textes(blocs[0])
    }
    assert marques["gras"] == {"bold"}
    assert marques["italique"] == {"italic"}
    assert marques["code"] == {"code"}


def test_les_marques_ne_deviennent_jamais_des_elements():
    blocs = convertir("**gras**")
    assert types(blocs) == ["p"]
    assert all("type" not in n for n in blocs[0]["children"])


def test_liste_a_puces_et_numerotee():
    blocs = convertir("- un\n- deux\n\n1. a\n2. b")
    assert types(blocs) == ["ul", "ol"]
    assert types(blocs[0]["children"]) == ["li", "li"]


def test_citation():
    blocs = convertir("> une citation")
    assert types(blocs) == ["blockquote"]
    assert blocs[0]["borderLeft"]


def test_tableau_rend_th_en_td_gras():
    blocs = convertir("| A | B |\n| --- | --- |\n| 1 | 2 |")
    assert types(blocs) == ["table"]
    entete, corps = blocs[0]["children"]
    assert entete["type"] == "thead"
    cellules = entete["children"][0]["children"]
    assert types(cellules) == ["td", "td"]
    assert cellules[0]["children"][0]["bold"] is True
    assert types(corps["children"][0]["children"]) == ["td", "td"]


def test_bloc_de_code_replie_en_paragraphes_code():
    blocs = convertir("```\nx = 1\ny = 2\n```")
    assert types(blocs) == ["p", "p"]
    assert all(bloc["children"][0]["code"] for bloc in blocs)


def test_lien_conserve_le_texte_et_ajoute_url():
    blocs = convertir("Voir [le guide](https://exemple.fr/guide).")
    contenu = "".join(n["text"] for n in textes(blocs[0]))
    assert "le guide" in contenu
    assert "(https://exemple.fr/guide)" in contenu


def test_image_replie_sur_son_texte_alternatif():
    blocs = convertir("![un schéma](img.png)")
    assert "un schéma" in "".join(n["text"] for n in textes(blocs[0]))


def test_construction_inconnue_replie_sans_lever():
    blocs = convertir("<section><span>texte brut</span></section>")
    assert types(blocs) == ["p"]
    assert "texte brut" in "".join(n["text"] for n in textes(blocs[0]))


def test_markdown_vide_donne_un_paragraphe():
    blocs = convertir("   ")
    assert types(blocs) == ["p"]


def test_markdown_malforme_ne_leve_pas():
    blocs = convertir("| a | b\n| --- \n**gras non fermé")
    assert blocs
    assert all("type" in bloc for bloc in blocs)


def test_identifiants_uniques_dans_tout_le_document():
    markdown = (
        "# Titre\n\ntexte **gras**\n\n- un\n- deux\n\n"
        "| A | B |\n| --- | --- |\n| 1 | 2 |\n\n> citation"
    )
    blocs = convertir(markdown)
    identifiants = [n["id"] for bloc in blocs for n in textes(bloc)]
    assert len(identifiants) == len(set(identifiants))


def test_generateur_partage_garde_les_identifiants_uniques():
    generateur = GenerateurIds()
    gauche = markdown_vers_richtext("# a", generateur)
    droite = markdown_vers_richtext("# b", generateur)
    ids = [n["id"] for bloc in gauche + droite for n in textes(bloc)]
    assert len(ids) == len(set(ids))


def test_conversion_deterministe():
    assert convertir("# Titre\n\ntexte") == convertir("# Titre\n\ntexte")
