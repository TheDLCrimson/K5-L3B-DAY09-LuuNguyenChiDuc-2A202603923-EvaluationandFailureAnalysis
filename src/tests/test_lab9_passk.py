"""M6: properties of pass@k and pass^k beyond the public vectors in tests/test_lab9_advanced.py."""
import math

import pytest

pytestmark = pytest.mark.student


@pytest.fixture(scope="module")
def stats():
    from lab9 import stats

    return stats


@pytest.mark.parametrize("n,c", [(5, 0), (5, 1), (5, 3), (5, 5), (10, 4)])
def test_ordering_pass_hat_k_le_pass_at_1_le_pass_at_k(stats, n, c):
    for k in range(1, n + 1):
        assert stats.pass_hat_k(n, c, k) <= stats.pass_at_k(n, c, 1) + 1e-12
        assert stats.pass_at_k(n, c, 1) <= stats.pass_at_k(n, c, k) + 1e-12


def test_k_equals_one_is_the_pass_rate(stats):
    assert stats.pass_at_k(5, 3, 1) == pytest.approx(0.6)
    assert stats.pass_hat_k(5, 3, 1) == pytest.approx(0.6)


def test_k_equals_n_is_all_or_nothing(stats):
    assert stats.pass_hat_k(5, 5, 5) == 1.0
    assert stats.pass_hat_k(5, 4, 5) == 0.0        # one failing seed in five zeroes pass^5
    assert stats.pass_at_k(5, 1, 5) == 1.0         # one passing seed in five is enough for pass@5
    assert stats.pass_at_k(5, 0, 5) == 0.0


def test_matches_the_definition_by_enumeration(stats):
    from itertools import combinations

    n, c, k = 6, 4, 3
    trials = [True] * c + [False] * (n - c)
    draws = list(combinations(range(n), k))
    any_pass = sum(any(trials[i] for i in d) for d in draws) / len(draws)
    all_pass = sum(all(trials[i] for i in d) for d in draws) / len(draws)
    assert math.isclose(stats.pass_at_k(n, c, k), any_pass)
    assert math.isclose(stats.pass_hat_k(n, c, k), all_pass)


@pytest.mark.parametrize("args", [(5, 6, 1), (5, 2, 0), (3, 1, 4), (5, -1, 2), (0, 0, 1)])
def test_invalid_samples_are_rejected(stats, args):
    for fn in (stats.pass_at_k, stats.pass_hat_k):
        with pytest.raises(ValueError):
            fn(*args)
