import pytest

from triagelab.hashing import canonical_json, stable_hash


def test_key_order_does_not_change_hash() -> None:
    assert stable_hash({"a": 1, "b": [1, 2]}) == stable_hash({"b": [1, 2], "a": 1})


def test_list_order_does_change_hash() -> None:
    assert stable_hash([1, 2]) != stable_hash([2, 1])


def test_unicode_is_kept_verbatim() -> None:
    assert canonical_json({"t": "日本語"}) == '{"t":"日本語"}'


def test_nan_is_rejected() -> None:
    with pytest.raises(ValueError, match="JSON compliant"):
        stable_hash({"x": float("nan")})
