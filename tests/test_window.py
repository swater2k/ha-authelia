"""Tests für CounterWindow."""

from custom_components.authelia.window import CounterWindow


def test_needs_two_points() -> None:
    w = CounterWindow(max_age=3600)
    assert w.delta(300, now=0) is None
    w.add(0, 10)
    assert w.delta(300, now=0) is None


def test_window_delta() -> None:
    w = CounterWindow(max_age=3600)
    for t, v in [(0, 10), (60, 12), (120, 15), (400, 20)]:
        w.add(t, v)
    # Fenster 300 s ab now=400 -> Cutoff 100 -> Basis = letzter Punkt <= 100 (t=60)
    assert w.delta(300, now=400) == 20 - 12
    assert w.delta(3600, now=400) == 10      # kürzere Historie -> ab ältestem Punkt


def test_reset_handling() -> None:
    w = CounterWindow(max_age=3600)
    w.add(0, 100)
    w.add(60, 110)
    w.add(120, 3)  # Authelia-Neustart
    w.add(180, 5)
    assert w.resets == 1
    assert w.delta(3600, now=180) == 15  # 10 vor + 5 nach dem Neustart


def test_pruning_keeps_base_point() -> None:
    w = CounterWindow(max_age=100)
    for t in range(0, 1000, 10):
        w.add(t, t)
    assert w.covered_seconds <= 110
    assert w.delta(100, now=990) == 100
