import math

import pytest

from backend.app.analysis.model_research import (
    align_probability_columns,
    apply_temperature_scaler,
    classification_metrics,
    fit_temperature_scaler,
)


def _negative_log_likelihood(
    probabilities: list[list[float]], labels: list[float], classes: list[float]
) -> float:
    positions = {label: index for index, label in enumerate(classes)}
    return sum(
        -math.log(max(1e-12, row[positions[label]]))
        for row, label in zip(probabilities, labels, strict=True)
    ) / len(labels)


def test_temperature_scaler_reduces_calibration_sample_log_loss() -> None:
    classes = [-1.0, 0.0, 1.0]
    labels = [-1.0, 0.0, 1.0, -1.0, 0.0, 1.0, -1.0, 0.0, 1.0]
    probabilities = [
        [0.90, 0.05, 0.05],
        [0.05, 0.90, 0.05],
        [0.05, 0.05, 0.90],
        [0.90, 0.05, 0.05],
        [0.05, 0.90, 0.05],
        [0.05, 0.05, 0.90],
        [0.90, 0.05, 0.05],
        [0.05, 0.90, 0.05],
        [0.05, 0.05, 0.90],
    ]
    overconfident = [
        [0.98, 0.01, 0.01] if i % 3 == 0 else row
        for i, row in enumerate(probabilities)
    ]
    temperature = fit_temperature_scaler(overconfident, labels, classes)
    calibrated = apply_temperature_scaler(overconfident, temperature)

    assert temperature > 0.0
    assert _negative_log_likelihood(calibrated, labels, classes) <= _negative_log_likelihood(

        overconfident, labels, classes
    )


def test_probability_columns_align_to_declared_target_classes() -> None:
    aligned = align_probability_columns(
        [[0.75, 0.25], [0.2, 0.8]],
        source_classes=[-1.0, 1.0],
        target_classes=[-1.0, 0.0, 1.0],
    )

    assert aligned == [[0.75, 0.0, 0.25], [0.2, 0.0, 0.8]]


def test_multiclass_metrics_include_probability_calibration_metrics() -> None:
    metrics = classification_metrics(
        [-1.0, 0.0, 1.0],
        [-1.0, 0.0, 1.0],
        [[0.8, 0.1, 0.1], [0.1, 0.8, 0.1], [0.1, 0.1, 0.8]],
        class_labels=[-1.0, 0.0, 1.0],
    )

    assert metrics["brier_score"] is not None
    assert metrics["log_loss"] is not None
    assert metrics["expected_calibration_error"] is not None
    assert metrics["roc_auc"] is None


def test_temperature_scaler_rejects_probability_shape_mismatch() -> None:
    with pytest.raises(ValueError, match="dimensions"):
        fit_temperature_scaler([[0.5, 0.5]], [1.0], classes=[-1.0, 0.0, 1.0])
