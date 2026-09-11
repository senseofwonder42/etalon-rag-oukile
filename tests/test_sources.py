from rag_referentiel.schemas import Source
from rag_referentiel.sources import (
    display_metadata,
    document_url,
    format_sources,
    group_by_document,
    parse_sources,
)

TEMPLATE = "https://sp.exemple.fr/docs/{doc_id}#page={page}"


def pages(text):
    parsed, _ = parse_sources(text)
    return [(s.doc_id, s.page) for s in parsed]


def test_canonical_format():
    assert pages("cg_auto.pdf:12 14, guide.pdf:3") == [
        ("cg_auto.pdf", 12),
        ("cg_auto.pdf", 14),
        ("guide.pdf", 3),
    ]


def test_a_single_page_needs_no_prefix():
    assert pages("cg_auto.pdf:12") == [("cg_auto.pdf", 12)]


def test_a_document_without_a_page():
    assert pages("guide.pdf") == [("guide.pdf", None)]


def test_page_prefixes_are_tolerated():
    assert (
        pages("doc.pdf:p12 P14")
        == pages("doc.pdf:page 12 page 14")
        == pages("doc.pdf:p. 12 / p. 14")
        == [("doc.pdf", 12), ("doc.pdf", 14)]
    )


def test_a_page_range_is_expanded():
    assert pages("doc.pdf:12-14") == [
        ("doc.pdf", 12),
        ("doc.pdf", 13),
        ("doc.pdf", 14),
    ]


def test_an_absurd_range_is_reported_not_expanded():
    parsed, unreadable = parse_sources("doc.pdf:1-9999")
    assert [(s.doc_id, s.page) for s in parsed] == [("doc.pdf", None)]
    assert unreadable == ["doc.pdf:1-9999"]


def test_a_lone_page_carries_on_with_the_last_document():
    # C'est l'ancien format : il continue de fonctionner.
    assert pages("doc.pdf:12, 14, p31") == [
        ("doc.pdf", 12),
        ("doc.pdf", 14),
        ("doc.pdf", 31),
    ]


def test_a_lone_page_without_any_document_is_unreadable():
    parsed, unreadable = parse_sources("14, doc.pdf:3")
    assert [(s.doc_id, s.page) for s in parsed] == [("doc.pdf", 3)]
    assert unreadable == ["14"]


def test_decoration_and_spacing_are_repaired():
    assert pages("«doc.pdf : 12» ; (autre.pdf:3).") == [
        ("doc.pdf", 12),
        ("autre.pdf", 3),
    ]


def test_duplicates_are_dropped():
    assert pages("doc.pdf:12 12, doc.pdf:12") == [("doc.pdf", 12)]


def test_an_unreadable_page_is_reported_without_failing_the_batch():
    parsed, unreadable = parse_sources("doc.pdf:page, doc2.pdf:12")
    assert ("doc2.pdf", 12) in [(s.doc_id, s.page) for s in parsed]
    assert unreadable == ["doc.pdf:page"]


def test_an_empty_input():
    assert parse_sources("") == ([], [])
    assert parse_sources("  ,  ; ") == ([], [])


def test_formatting_groups_the_pages_of_a_document():
    sources = [
        Source(doc_id="cg_auto.pdf", page=12),
        Source(doc_id="cg_auto.pdf", page=14),
        Source(doc_id="guide.pdf", page=3),
    ]
    assert format_sources(sources) == "cg_auto.pdf:12 14, guide.pdf:3"


def test_formatting_a_document_without_a_page():
    assert format_sources([Source(doc_id="guide.pdf")]) == "guide.pdf"


def test_formatting_an_empty_list():
    assert format_sources([]) == ""


def test_formatting_then_parsing_is_stable():
    typed = "cg_auto.pdf:12 14 31, guide.pdf:3, autre.pdf"
    parsed, unreadable = parse_sources(typed)
    assert unreadable == []
    assert format_sources(parsed) == typed


def test_grouping_keeps_the_order_and_drops_duplicate_pages():
    sources = [
        Source(doc_id="cg.pdf", page=12),
        Source(doc_id="guide.pdf", page=3),
        Source(doc_id="cg.pdf", page=14),
        Source(doc_id="cg.pdf", page=12),
        Source(doc_id="annexe.pdf"),
    ]
    assert group_by_document(sources) == [
        ("cg.pdf", [12, 14]),
        ("guide.pdf", [3]),
        ("annexe.pdf", []),
    ]


def test_a_document_url_carries_the_page_anchor():
    assert (
        document_url(TEMPLATE, "cg_auto.pdf", 12)
        == "https://sp.exemple.fr/docs/cg_auto.pdf#page=12"
    )


def test_a_document_without_a_page_drops_the_anchor():
    assert (
        document_url(TEMPLATE, "cg_auto.pdf", None)
        == "https://sp.exemple.fr/docs/cg_auto.pdf"
    )


def test_a_document_name_is_url_encoded():
    assert "cg%20auto.pdf" in document_url(TEMPLATE, "cg auto.pdf", 3)


def test_no_template_means_no_url():
    assert document_url(None, "cg_auto.pdf", 12) is None
    assert document_url("", "cg_auto.pdf", 12) is None


def test_an_unusable_template_is_reported_not_raised():
    assert document_url("https://x/{inconnu}", "cg.pdf", 1) is None


def test_the_url_metadata_key_needs_a_single_document():
    one = [Source(doc_id="cg.pdf", page=12), Source(doc_id="cg.pdf", page=14)]
    assert display_metadata(one, TEMPLATE) == {
        "url": "https://sp.exemple.fr/docs/cg.pdf#page=12"
    }
    two = [Source(doc_id="cg.pdf", page=12), Source(doc_id="guide.pdf")]
    assert display_metadata(two, TEMPLATE) == {}
    assert display_metadata(one, None) == {}


def test_a_real_document_name_round_trips():
    typed = (
        "DCON_ConditionsGénérales_MRH_202605.pdf:22 23 24, "
        "DCON_DIPA_MRH_202605.pdf:1"
    )
    parsed, unreadable = parse_sources(typed)
    assert unreadable == []
    assert format_sources(parsed) == typed


def test_an_unaccented_document_name_is_left_as_is_in_its_url():
    url = document_url(TEMPLATE, "DCON_ConditionsGénérales_MRH_202605.pdf", 5)
    assert url == "https://sp.exemple.fr/docs/DCON_ConditionsGénérales_MRH_202605.pdf#page=5"
    assert "%" not in url


def test_an_accented_document_name_is_percent_encoded():
    # C'est le codage normal d'un « é » dans une URL, pas une corruption :
    # le navigateur le décode, SharePoint l'accepte.
    url = document_url(TEMPLATE, "Avenant_Résiliation_2026.pdf", 1)
    assert "R%C3%A9siliation" in url
