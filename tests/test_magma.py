import pytest

from magma_explorer.magma import Magma, TableParseError, parse_table, satisfies_677


def test_parse_simple_whitespace():
    assert parse_table("0 1\n1 0") == [[0, 1], [1, 0]]


def test_parse_comma_separated():
    assert parse_table("0,1\n1,0") == [[0, 1], [1, 0]]


def test_parse_mixed_separators():
    assert parse_table("0,1\n1 0") == [[0, 1], [1, 0]]


def test_parse_single_element():
    assert parse_table("0") == [[0]]


def test_parse_strips_blank_lines():
    assert parse_table("\n0 1\n\n1 0\n") == [[0, 1], [1, 0]]


def test_parse_expected_size_match():
    assert parse_table("0", expected_size=1) == [[0]]


def test_parse_empty_raises():
    with pytest.raises(TableParseError):
        parse_table("")
    with pytest.raises(TableParseError):
        parse_table("   \n   ")


def test_parse_non_square_raises():
    with pytest.raises(TableParseError):
        parse_table("0 1\n0")


def test_parse_out_of_range_value_raises():
    with pytest.raises(TableParseError):
        parse_table("0 2\n1 0")


def test_parse_negative_value_raises():
    with pytest.raises(TableParseError):
        parse_table("0 -1\n1 0")


def test_parse_non_integer_raises():
    with pytest.raises(TableParseError):
        parse_table("a b\nc d")


def test_parse_expected_size_mismatch_raises():
    with pytest.raises(TableParseError):
        parse_table("0", expected_size=2)


def test_trivial_size_one_satisfies_677():
    # Size-1 magmas trivially satisfy any equation.
    assert satisfies_677([[0]])


def test_zero_table_size_two_fails_677():
    # All entries map to 0; the equation breaks for (x=1, y=0).
    assert not satisfies_677([[0, 0], [0, 0]])


def _manifest_entry(**overrides):
    base = {
        "canonical_hash": "abc",
        "size": 5,
        "satisfies_255": True,
        "right_cancellative": False,
        "idempotent": True,
        "display_reorder": "0,1,2,3,4",
        "comment": "test",
        "submitted_at": "2026-04-23 20:56:20",
        "submitted_by": "claude",
        "url": "https://example.com/x.txt",
    }
    base.update(overrides)
    return base


def test_magma_from_manifest_entry():
    m = Magma.from_manifest_entry(_manifest_entry())
    assert m.canonical_hash == "abc"
    assert m.size == 5
    assert m.satisfies_255 is True
    assert m.right_cancellative is False
    assert m.idempotent is True
    assert m.display_reorder == "0,1,2,3,4"
    assert m.url == "https://example.com/x.txt"


def test_magma_from_manifest_entry_null_reorder():
    m = Magma.from_manifest_entry(_manifest_entry(display_reorder=None))
    assert m.display_reorder is None


def test_magma_from_manifest_entry_null_strings_coerce_to_empty():
    m = Magma.from_manifest_entry(
        _manifest_entry(comment=None, submitted_at=None, submitted_by=None)
    )
    assert m.comment == ""
    assert m.submitted_at == ""
    assert m.submitted_by == ""
