"""Parsing and formatting of the source lists typed by annotators.

Canonical format: one fragment per document, its pages listed after the
colon and separated by spaces.

    cg_auto_2024.pdf:12 14 31, guide_sinistres.pdf:3

A document is never repeated, and a page never appears on its own — which
removes the earlier ambiguity where a page had to be written `p12` when
standing alone and `12` right after its document.

Parsing stays deliberately tolerant: annotators type by hand, so the
usual slips are repaired rather than rejected (see `parse_sources`).
"""

import re

from loguru import logger

from .schemas import Source

#: Séparateurs entre deux documents.
_DOCUMENT_SEPARATORS = re.compile(r"[,;\n]")
#: Séparateurs entre deux pages d'un même document.
_PAGE_SEPARATORS = re.compile(r"[\s/+&]+")
#: Caractères décoratifs parfois collés autour d'une saisie.
_DECORATION = " \t«»\"'()[]{}.<>"
#: Une page seule : `12`, `p12`, `p. 12`, `page 12`.
_PAGE = re.compile(r"^(?:p(?:age)?s?\.?\s*)?(?P<page>\d{1,5})$", re.I)
#: Un intervalle de pages : `12-14`.
_PAGE_RANGE = re.compile(
    r"^(?:p(?:age)?s?\.?\s*)?(?P<first>\d{1,5})\s*[-–]\s*(?P<last>\d{1,5})$",
    re.I,
)
#: Garde-fou : un intervalle plus large est une faute de frappe.
MAX_RANGE_LENGTH = 50
#: « p. 12 » ou « page 12 » : on recolle le préfixe à son numéro avant de
#: découper sur les espaces, sinon le préfixe partirait seul.
_LOOSE_PAGE_PREFIX = re.compile(r"\bp(?:age)?s?\.?\s+(?=\d)", re.I)


def _clean(fragment: str) -> str:
    """Strip decoration and collapse whitespace in a typed fragment.

    Args:
        fragment: Raw fragment, as typed.

    Returns:
        The cleaned fragment, possibly empty.
    """
    return re.sub(r"\s+", " ", fragment.replace(" ", " ")).strip(
        _DECORATION
    )


def _parse_pages(text: str) -> tuple[list[int], list[str]]:
    """Parse the page list that follows a document.

    Args:
        text: What comes after the colon, for instance `12 14` or
            `p12-14`.

    Returns:
        The pair (page numbers, unreadable fragments).
    """
    pages: list[int] = []
    unreadable: list[str] = []
    for piece in _PAGE_SEPARATORS.split(_LOOSE_PAGE_PREFIX.sub("p", text)):
        cleaned = _clean(piece)
        if not cleaned:
            continue
        single = _PAGE.match(cleaned)
        if single:
            pages.append(int(single["page"]))
            continue
        span = _PAGE_RANGE.match(cleaned)
        if span:
            first, last = int(span["first"]), int(span["last"])
            if first <= last <= first + MAX_RANGE_LENGTH:
                pages.extend(range(first, last + 1))
                continue
            logger.warning(
                "Intervalle de pages ignoré, trop large ou inversé : {}",
                cleaned,
            )
        unreadable.append(cleaned)
    return pages, unreadable


def parse_sources(text: str) -> tuple[list[Source], list[str]]:
    """Parse a source list typed by an annotator.

    The canonical shape is `doc.pdf:12 14, autre.pdf:3`, but the parsing
    repairs the usual slips rather than rejecting them:

    - `p12`, `p. 12`, `page 12`, `P12` all mean page 12;
    - pages may be separated by spaces, `/`, `+` or `&`;
    - `12-14` is read as the page range 12, 13, 14, up to
      `MAX_RANGE_LENGTH` pages;
    - a fragment holding only a page number carries on with the last
      named document — `doc.pdf:12, 14` therefore works too;
    - decoration around a fragment (quotes, brackets, a trailing period)
      is dropped, and duplicates are removed.

    Anything left unreadable is reported and skipped rather than failing
    the whole batch.

    Args:
        text: What the annotator typed.

    Returns:
        The pair (parsed sources, unreadable fragments).
    """
    sources: list[Source] = []
    unreadable: list[str] = []
    seen: set[tuple[str, int | None]] = set()
    last_doc: str | None = None

    def keep(doc_id: str, page: int | None) -> None:
        if (doc_id, page) in seen:
            return
        seen.add((doc_id, page))
        sources.append(Source(doc_id=doc_id, page=page))

    for fragment in _DOCUMENT_SEPARATORS.split(text or ""):
        cleaned = _clean(fragment)
        if not cleaned:
            continue

        if ":" in cleaned:
            raw_doc, _, raw_pages = cleaned.partition(":")
            doc_id = _clean(raw_doc)
            if not doc_id:
                unreadable.append(cleaned)
                continue
            last_doc = doc_id
            pages, rejected = _parse_pages(raw_pages)
            unreadable.extend(
                f"{doc_id}:{piece}" for piece in rejected
            )
            if not pages:
                keep(doc_id, None)
            for page in pages:
                keep(doc_id, page)
            continue

        # Pas de deux-points : soit une page qui prolonge le document
        # précédent, soit un document cité sans page.
        pages, rejected = _parse_pages(cleaned)
        if pages and not rejected:
            if last_doc is None:
                unreadable.append(cleaned)
                continue
            for page in pages:
                keep(last_doc, page)
            continue
        last_doc = cleaned
        keep(cleaned, None)

    return sources, unreadable


def group_by_document(
    sources: list[Source],
) -> list[tuple[str, list[int]]]:
    """Group sources by document, keeping the order they were given in.

    Args:
        sources: Sources to group.

    Returns:
        One pair (document, pages) per document; the page list is empty
        when the document is cited without a page.
    """
    grouped: dict[str, list[int]] = {}
    for source in sources:
        pages = grouped.setdefault(source.doc_id, [])
        if source.page is not None and source.page not in pages:
            pages.append(source.page)
    return list(grouped.items())


def format_sources(sources: list[Source]) -> str:
    """Render sources in the canonical input format.

    Pages of one document are grouped, so the result can be pasted back
    into the `SOURCES_CORRIGEES` job and edited in place.

    Args:
        sources: Sources to render.

    Returns:
        A string such as `cg_auto.pdf:12 14, guide.pdf:3`; empty when
        there is no source.
    """
    return ", ".join(
        f"{doc_id}:{' '.join(str(p) for p in pages)}" if pages else doc_id
        for doc_id, pages in group_by_document(sources)
    )
