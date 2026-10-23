from backend.app.analysis.change_points import binary_segmentation, detect_change_points_combined


def test_change_points_detect_shift() -> None:
    series = [0.0] * 20 + [5.0] * 20
    cps = binary_segmentation(series, min_segment_length=5, max_change_points=5, penalty=1.0)
    assert 20 in cps


def test_combined() -> None:
    series = [0.0] * 20 + [5.0] * 20
    cps = detect_change_points_combined(series, min_segment_length=5)
    assert 20 in cps
