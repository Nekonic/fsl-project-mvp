from domain.baseline import percentile, top_share


def test_percentile_counts_ties_half_and_reads_the_direction_of_the_side():
    samples = [1.0, 2.0, 2.0, 4.0]

    assert percentile(2.0, samples, higher_is_better=True) == 50.0
    assert percentile(2.0, samples, higher_is_better=False) == 50.0
    assert percentile(4.0, samples, higher_is_better=True) == 87.5
    assert top_share(0.0, samples, "defence") == 0.0
    assert top_share(0.0, samples, "attack") == 100.0
