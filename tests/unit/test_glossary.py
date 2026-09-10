"""The packet-terminology glossary: shipped data plus its search.

No I/O, no event loop -- see `kissterm/glossary.py`'s module docstring for
why this is a hardcoded tuple rather than a TOML-backed loader like
`kissterm/nodes/`.
"""

from __future__ import annotations

from kissterm import glossary


def test_terms_are_shipped():
    assert glossary.TERMS, "no glossary terms shipped"


def test_every_term_has_a_name_and_definition():
    for term in glossary.TERMS:
        assert term.name.strip(), "a glossary term has no name"
        assert term.definition.strip(), f"{term.name!r} has no definition"


def test_no_duplicate_terms():
    names = [t.name for t in glossary.TERMS]
    assert len(names) == len(set(names)), "a glossary term name is duplicated"


def test_empty_search_returns_everything():
    assert glossary.search("") == glossary.TERMS
    assert glossary.search("   ") == glossary.TERMS


def test_search_matches_name_case_insensitively():
    results = glossary.search("kiss")
    assert any(t.name == "KISS" for t in results)


def test_search_matches_inside_a_definition_too():
    # "checksum" appears in the Frame term's definition (of FCS) but is not
    # itself a term name -- proves the match is not name-only.
    results = glossary.search("checksum")
    assert results
    assert all("checksum" not in t.name.lower() for t in results)
    assert any("checksum" in t.definition.lower() for t in results)


def test_search_with_no_match_returns_nothing():
    assert glossary.search("this term does not exist anywhere") == ()
