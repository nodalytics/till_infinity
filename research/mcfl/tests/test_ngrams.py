from __future__ import annotations

from collections import Counter

from mcfl.ngrams import cond_kl, kl, next_counts, next_probs, ngrams


def test_counts_on_a_known_sequence():
    s = [["A", "B", "A", "B", "C"], ["A", "B"]]  # n-grams do not span series
    assert ngrams(s, 1) == Counter({("A",): 3, ("B",): 3, ("C",): 1})
    assert ngrams(s, 2) == Counter({("A", "B"): 3, ("B", "A"): 1, ("B", "C"): 1})
    assert ngrams(s, 3) == Counter({("A", "B", "A"): 1, ("B", "A", "B"): 1, ("A", "B", "C"): 1})
    assert ngrams(s, 4) == Counter({("A", "B", "A", "B"): 1, ("B", "A", "B", "C"): 1})
    p = next_probs(s, 1)
    assert p[("A",)] == {"B": 1.0}
    assert p[("B",)] == {"A": 0.5, "C": 0.5}
    assert next_probs(s, 2)[("A", "B")] == {"A": 0.5, "C": 0.5}


def test_kl():
    a = Counter({"x": 10, "y": 10})
    assert kl(a, a) == 0.0
    assert kl(Counter({"x": 20}), a, alpha=0.0) == 1.0  # all mass on x against a fair split: 1 bit
    assert kl(Counter({"x": 20}), a) > 0
    d = next_counts([["A", "B", "A", "B"]], 1)
    assert cond_kl(d, d) == 0.0
