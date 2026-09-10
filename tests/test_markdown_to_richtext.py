from rag_referentiel.markdown_to_richtext import markdown_to_richtext
from rag_referentiel.richtext import IdGenerator


def convert(markdown):
    return markdown_to_richtext(markdown, IdGenerator())


def types(blocks):
    return [block["type"] for block in blocks]


def texts(node):
    if "text" in node:
        return [node]
    result = []
    for child in node.get("children", []):
        result.extend(texts(child))
    return result


def test_headings_h1_to_h4():
    blocks = convert("# un\n\n## deux\n\n### trois\n\n#### quatre")
    assert types(blocks) == ["h1", "h2", "h3", "h4"]


def test_headings_beyond_h4_fall_back_on_h4():
    assert types(convert("##### cinq")) == ["h4"]


def test_paragraph_and_inline_marks():
    blocks = convert("Du **gras**, de l'*italique* et du `code`.")
    assert types(blocks) == ["p"]
    marks = {
        node["text"]: {
            key for key in ("bold", "italic", "code") if node.get(key)
        }
        for node in texts(blocks[0])
    }
    assert marks["gras"] == {"bold"}
    assert marks["italique"] == {"italic"}
    assert marks["code"] == {"code"}


def test_marks_never_become_elements():
    blocks = convert("**gras**")
    assert types(blocks) == ["p"]
    assert all("type" not in node for node in blocks[0]["children"])


def test_bullet_and_numbered_lists():
    blocks = convert("- un\n- deux\n\n1. a\n2. b")
    assert types(blocks) == ["ul", "ol"]
    assert types(blocks[0]["children"]) == ["li", "li"]


def test_blockquote():
    blocks = convert("> une citation")
    assert types(blocks) == ["blockquote"]
    assert blocks[0]["borderLeft"]


def test_table_renders_th_as_bold_td():
    blocks = convert("| A | B |\n| --- | --- |\n| 1 | 2 |")
    assert types(blocks) == ["table"]
    head, body = blocks[0]["children"]
    assert head["type"] == "thead"
    cells = head["children"][0]["children"]
    assert types(cells) == ["td", "td"]
    assert cells[0]["children"][0]["bold"] is True
    assert types(body["children"][0]["children"]) == ["td", "td"]


def test_code_block_falls_back_on_code_paragraphs():
    blocks = convert("```\nx = 1\ny = 2\n```")
    assert types(blocks) == ["p", "p"]
    assert all(block["children"][0]["code"] for block in blocks)


def test_link_keeps_its_text_and_appends_the_url():
    blocks = convert("Voir [le guide](https://exemple.fr/guide).")
    content = "".join(node["text"] for node in texts(blocks[0]))
    assert "le guide" in content
    assert "(https://exemple.fr/guide)" in content


def test_image_falls_back_on_its_alternative_text():
    blocks = convert("![un schéma](img.png)")
    assert "un schéma" in "".join(
        node["text"] for node in texts(blocks[0])
    )


def test_unknown_construct_falls_back_without_raising():
    blocks = convert("<section><span>texte brut</span></section>")
    assert types(blocks) == ["p"]
    assert "texte brut" in "".join(
        node["text"] for node in texts(blocks[0])
    )


def test_empty_markdown_yields_a_paragraph():
    assert types(convert("   ")) == ["p"]


def test_malformed_markdown_does_not_raise():
    blocks = convert("| a | b\n| --- \n**gras non fermé")
    assert blocks
    assert all("type" in block for block in blocks)


def test_identifiers_are_unique_across_the_whole_document():
    markdown = (
        "# Titre\n\ntexte **gras**\n\n- un\n- deux\n\n"
        "| A | B |\n| --- | --- |\n| 1 | 2 |\n\n> citation"
    )
    blocks = convert(markdown)
    identifiers = [n["id"] for block in blocks for n in texts(block)]
    assert len(identifiers) == len(set(identifiers))


def test_a_shared_generator_keeps_identifiers_unique():
    generator = IdGenerator()
    left = markdown_to_richtext("# a", generator)
    right = markdown_to_richtext("# b", generator)
    ids = [n["id"] for block in left + right for n in texts(block)]
    assert len(ids) == len(set(ids))


def test_conversion_is_deterministic():
    assert convert("# Titre\n\ntexte") == convert("# Titre\n\ntexte")
