from __future__ import annotations

from backend.app.analysis.replay import (
    _bootstrap_improvement,
    _probability_backtest_overfitting,
    _white_reality_check,
)


def test_block_bootstrap_reports_paired_improvement_interval() -> None:
    result = _bootstrap_improvement([0.2] * 30, seed=7, replicates=100)

    assert result["status"] == "computed"
    assert result["mean_improvement"] == 0.2
    assert result["ci_95"] == [0.2, 0.2]
    assert result["p_value_one_sided"] < 0.02


def test_white_reality_check_accounts_for_multiple_model_candidates() -> None:
    result = _white_reality_check(
        {"candidate_a": [0.1] * 30, "candidate_b": [-0.1] * 30},
        seed=3,
        replicates=100,
    )

    assert result["status"] == "computed"
    assert result["models_tested"] == ["candidate_a", "candidate_b"]
    assert result["p_value"] < 0.02
    assert result["chronological_evaluation_remains_primary"] is True


def test_pbo_is_supplementary_and_detects_a_reversing_candidate() -> None:
    result = _probability_backtest_overfitting(
        {
            "first_half_winner": [0.1] * 40 + [0.9] * 40,
            "second_half_winner": [0.9] * 40 + [0.1] * 40,
        }
    )

    assert result["status"] == "computed"
    assert result["partitions"] == 70
    assert result["probability_of_backtest_overfitting"] > 0.45
    assert result["chronological_evaluation_remains_primary"] is True
