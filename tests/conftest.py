import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Turn `@pytest.mark.your_turn` into an xfail that only tolerates NotImplementedError.

    While a YOUR TURN stub is untouched, its tests xfail and CI stays green. Once you
    implement it, a wrong answer fails normally (AssertionError is not tolerated) and a
    right answer shows as XPASS. At that point, delete the marker.
    To see the raw failures: `uv run pytest -m your_turn --runxfail`.
    """
    for item in items:
        if item.get_closest_marker("your_turn"):
            item.add_marker(
                pytest.mark.xfail(
                    raises=NotImplementedError,
                    reason="YOUR TURN exercise not implemented yet",
                    strict=False,
                )
            )
