import pytest

from backend.app.analysis.features import (
    cumulative_return,
    direction_consistency,
    simple_returns,
)


def test_simple_returns() -> None:
    closes = [100.0, 110.0, 99.0]
    returns = simple_returns(closes)
    assert returns[0] is None
    assert returns[1] == pytest.approx(0.1)
    assert returns[2] == pytest.approx(-0.1)


def test_cumulative_and_consistency() -> None:
    returns = [None, 0.1, 0.1, -0.05, 0.02]
    cr = cumulative_return(returns, 2)
    assert cr[2] == pytest.approx(0.21)
    dc = direction_consistency(returns, 2)
    assert dc[2] == pytest.approx(1.0)
