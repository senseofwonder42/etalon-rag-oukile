"""Building blocks of the rich text format of Kili TEXT assets.

A rich text asset is a tree of nodes:

- an **element node** carries `children` and a `type` taken from
  `ALLOWED_ELEMENTS`;
- a **text node** carries `text` and an `id` that must be unique across
  the whole document, optionally with marks (`bold`, `italic`, `code`,
  `underline`).

Both accept CSS styles (`backgroundColor`, `color`, `padding`, …). The
SDK validates nothing: it serializes the tree and uploads it.
"""

ALLOWED_ELEMENTS = frozenset(
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

ALLOWED_MARKS = frozenset({"bold", "italic", "code", "underline"})


class IdGenerator:
    """Deterministic generator of text node identifiers.

    A single generator must be used for a whole document: text node ids
    have to be unique within it. The counter being deterministic, two
    renderings of the same data produce exactly the same tree, which is
    what lets the tests compare outputs.
    """

    def __init__(self, prefix: str = "n") -> None:
        """Initialize the generator.

        Args:
            prefix: Prefix of the produced identifiers.
        """
        self._prefix = prefix
        self._counter = 0

    def next_id(self) -> str:
        """Produce the next identifier.

        Returns:
            An identifier shaped as `n1`, `n2`, …
        """
        self._counter += 1
        return f"{self._prefix}{self._counter}"


def text_node(
    text: str,
    generator: IdGenerator,
    marks: frozenset[str] | set[str] | None = None,
    styles: dict[str, str] | None = None,
) -> dict:
    """Build a text node.

    Args:
        text: Textual content of the node.
        generator: Id generator of the current document.
        marks: Marks to apply, taken from `ALLOWED_MARKS`.
        styles: Extra CSS styles.

    Returns:
        The text node, ready to be serialized.

    Raises:
        ValueError: If an unknown mark is requested.
    """
    node: dict = {"id": generator.next_id(), "text": text}
    for mark in sorted(marks or ()):
        if mark not in ALLOWED_MARKS:
            raise ValueError(f"Marque inconnue : {mark}")
        node[mark] = True
    node.update(styles or {})
    return node


def element_node(
    element_type: str,
    children: list[dict],
    generator: IdGenerator,
    styles: dict[str, str] | None = None,
) -> dict:
    """Build an element node.

    Args:
        element_type: Element type, taken from `ALLOWED_ELEMENTS`.
        children: Child nodes; an empty text node is appended when the
            list is empty, an element without children having nothing to
            render.
        generator: Id generator of the current document.
        styles: Extra CSS styles.

    Returns:
        The element node, ready to be serialized.

    Raises:
        ValueError: If the element type is not supported by Kili.
    """
    if element_type not in ALLOWED_ELEMENTS:
        raise ValueError(f"Type d'élément inconnu : {element_type}")
    content = children or [text_node("", generator)]
    node: dict = {"type": element_type, "children": content}
    node.update(styles or {})
    return node


def document(
    children: list[dict], styles: dict[str, str] | None = None
) -> list[dict]:
    """Wrap block nodes into the root of a rich text document.

    Args:
        children: Top level nodes of the document.
        styles: CSS styles applied to the root.

    Returns:
        The complete `json_content`, as expected by Kili.
    """
    root: dict = {"children": children}
    root.update(styles or {})
    return [root]
