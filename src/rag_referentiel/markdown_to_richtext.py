"""Conversion of the RAG markdown into Kili rich text.

The path is the one of the recursive converter published by Kili in the
`recipes/import_text_assets.ipynb` notebook: markdown -> HTML
(`markdown-it-py`) -> node tree. One rule is added: inline `strong`, `em`
and `code` become **marks** on the text node rather than elements — Kili
does not accept those element types.

Covered subset: `h1`-`h4` headings, paragraphs, `ul` / `ol` / `li`,
`blockquote`, tables, bold, italic, inline code. Everything else has a
documented fallback (see the README) and nothing raises: at worst the
content ends up as a plain text paragraph.
"""

from dataclasses import dataclass, field
from html.parser import HTMLParser

from loguru import logger
from markdown_it import MarkdownIt

from .richtext import IdGenerator, element_node, text_node

#: Balises HTML rendues telles quelles comme éléments Kili.
BLOCKS = frozenset(
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
MARKS = {
    "strong": "bold",
    "b": "bold",
    "em": "italic",
    "i": "italic",
    "code": "code",
    "u": "underline",
    "ins": "underline",
}

#: Balises sans contenu.
VOID_TAGS = frozenset({"br", "hr", "img", "wbr"})

_HEADING_FALLBACKS = {"h5": "h4", "h6": "h4"}


@dataclass
class _Element:
    """Node of the intermediate HTML tree."""

    tag: str
    attributes: dict[str, str] = field(default_factory=dict)
    children: list["_Element | str"] = field(default_factory=list)


class _TreeBuilder(HTMLParser):
    """Assembles an `_Element` tree from an HTML stream."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Element("racine")
        self._stack: list[_Element] = [self.root]

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """Open an element (see `html.parser`)."""
        element = _Element(tag, {k: v or "" for k, v in attrs})
        self._stack[-1].children.append(element)
        if tag not in VOID_TAGS:
            self._stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        """Handle a self-closing tag (see `html.parser`)."""
        element = _Element(tag, {k: v or "" for k, v in attrs})
        self._stack[-1].children.append(element)

    def handle_endtag(self, tag: str) -> None:
        """Close an element (see `html.parser`)."""
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        """Append a text fragment (see `html.parser`)."""
        self._stack[-1].children.append(data)


def _parse_html(html: str) -> _Element:
    """Build the intermediate HTML tree.

    Args:
        html: HTML fragment produced by `markdown-it-py`.

    Returns:
        The root of the tree.
    """
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


def _plain_text(node: "_Element | str") -> str:
    """Concatenate all the text of a subtree.

    Args:
        node: Element or text fragment.

    Returns:
        The text, without markup.
    """
    if isinstance(node, str):
        return node
    return "".join(_plain_text(child) for child in node.children)


def _convert_inline(
    nodes: list["_Element | str"],
    generator: IdGenerator,
    marks: frozenset[str],
) -> list[dict]:
    """Convert a sequence of nodes into text nodes.

    Args:
        nodes: Children of an element, in inline context.
        generator: Id generator of the document.
        marks: Marks inherited from the enclosing elements.

    Returns:
        The produced text nodes.
    """
    result: list[dict] = []
    for node in nodes:
        if isinstance(node, str):
            if node:
                result.append(text_node(node, generator, marks))
        elif node.tag in MARKS:
            result.extend(
                _convert_inline(
                    node.children, generator, marks | {MARKS[node.tag]}
                )
            )
        elif node.tag == "a":
            result.extend(_convert_inline(node.children, generator, marks))
            url = node.attributes.get("href", "")
            if url:
                result.append(text_node(f" ({url})", generator, marks))
        elif node.tag == "img":
            label = node.attributes.get("alt") or "[image]"
            result.append(text_node(label, generator, marks))
        elif node.tag == "br":
            result.append(text_node("\n", generator, marks))
        else:
            # Balise en ligne inconnue : on garde son texte.
            result.extend(_convert_inline(node.children, generator, marks))
    return result


def _convert_code_block(
    element: _Element, generator: IdGenerator
) -> list[dict]:
    """Fall back on `code`-marked paragraphs for a code block.

    Args:
        element: The `pre` element.
        generator: Id generator of the document.

    Returns:
        One paragraph per line of code.
    """
    lines = _plain_text(element).rstrip("\n").split("\n")
    return [
        element_node(
            "p",
            [text_node(line, generator, {"code"})],
            generator,
            {"backgroundColor": "#f5f5f5"},
        )
        for line in lines
    ]


def _convert_blocks(
    nodes: list["_Element | str"],
    generator: IdGenerator,
    marks: frozenset[str],
) -> list[dict]:
    """Convert a sequence of nodes in block context.

    Runs of inline content found between two blocks are grouped into a
    paragraph.

    Args:
        nodes: Children of an element, in block context.
        generator: Id generator of the document.
        marks: Marks inherited from the enclosing elements.

    Returns:
        The produced block nodes.
    """
    result: list[dict] = []
    buffer: list["_Element | str"] = []

    def flush_buffer() -> None:
        if not buffer:
            return
        texts = _convert_inline(buffer, generator, marks)
        buffer.clear()
        if any(node["text"].strip() for node in texts):
            result.append(element_node("p", texts, generator))

    for node in nodes:
        is_block = isinstance(node, _Element) and (
            node.tag in BLOCKS
            or node.tag in _HEADING_FALLBACKS
            or node.tag in {"pre", "hr", "th", "div"}
        )
        if not is_block:
            buffer.append(node)
            continue
        flush_buffer()
        result.extend(_convert_element(node, generator, marks))

    flush_buffer()
    return result


def _convert_element(
    element: _Element,
    generator: IdGenerator,
    marks: frozenset[str],
) -> list[dict]:
    """Convert a block element.

    Args:
        element: HTML element to convert.
        generator: Id generator of the document.
        marks: Marks inherited from the enclosing elements.

    Returns:
        The Kili nodes produced for this element.
    """
    tag = _HEADING_FALLBACKS.get(element.tag, element.tag)

    if tag == "pre":
        return _convert_code_block(element, generator)

    if tag == "hr":
        return [
            element_node("p", [text_node("———", generator)], generator)
        ]

    if tag == "th":
        # Kili ne connaît pas `th` : on le rend comme un `td` en gras.
        return [
            element_node(
                "td",
                _convert_inline(
                    element.children, generator, marks | {"bold"}
                ),
                generator,
                {"backgroundColor": "#eeeeee"},
            )
        ]

    if tag in {"p", "h1", "h2", "h3", "h4", "td"}:
        return [
            element_node(
                tag,
                _convert_inline(element.children, generator, marks),
                generator,
            )
        ]

    if tag in {"ul", "ol", "table", "thead", "tbody", "tr", "li"}:
        return [
            element_node(
                tag,
                _convert_blocks(element.children, generator, marks)
                if tag != "li"
                else _convert_list_item(element, generator, marks),
                generator,
            )
        ]

    if tag == "blockquote":
        return [
            element_node(
                "blockquote",
                _convert_blocks(element.children, generator, marks),
                generator,
                {"borderLeft": "3px solid #9e9e9e", "padding": "4px 8px"},
            )
        ]

    # Construction inconnue : repli sur son contenu, en contexte de bloc.
    logger.debug("Balise non couverte, repli en texte brut : {}", element.tag)
    return _convert_blocks(element.children, generator, marks)


def _convert_list_item(
    element: _Element,
    generator: IdGenerator,
    marks: frozenset[str],
) -> list[dict]:
    """Convert the content of a `li`.

    A tight `li` holds text only, a loose one holds paragraphs and
    sometimes a nested list.

    Args:
        element: The `li` element.
        generator: Id generator of the document.
        marks: Marks inherited from the enclosing elements.

    Returns:
        The children of the `li`: text nodes, paragraphs or sublists.
    """
    holds_block = any(
        isinstance(child, _Element)
        and (child.tag in BLOCKS or child.tag in {"pre", "div"})
        for child in element.children
    )
    if holds_block:
        return _convert_blocks(element.children, generator, marks)
    return _convert_inline(element.children, generator, marks)


def markdown_to_richtext(
    markdown: str, generator: IdGenerator
) -> list[dict]:
    """Convert markdown into Kili rich text block nodes.

    Args:
        markdown: Markdown text produced by the RAG.
        generator: Id generator of the current document, shared with the
            rest of the rendering to keep ids unique.

    Returns:
        The block nodes. Always at least one node: empty or unreadable
        markdown falls back on a paragraph.
    """
    if not markdown.strip():
        return [element_node("p", [], generator)]

    try:
        html = MarkdownIt("commonmark").enable("table").render(markdown)
        blocks = _convert_blocks(
            _parse_html(html).children, generator, frozenset()
        )
    except Exception as error:  # noqa: BLE001 - repli volontaire
        logger.warning(
            "Markdown illisible, repli sur du texte brut : {}", error
        )
        blocks = []

    if not blocks:
        return [
            element_node(
                "p", [text_node(markdown.strip(), generator)], generator
            )
        ]
    return blocks
