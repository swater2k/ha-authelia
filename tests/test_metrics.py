"""Tests für Parser und Authelia-Modell."""

import math
from pathlib import Path

import pytest

from custom_components.authelia.metrics import (
    AutheliaMetrics,
    MetricsParseError,
    estimate_quantile,
    normalize_name,
    parse_prometheus_text,
)

FIXTURE = (Path(__file__).parent / "fixtures" / "metrics_sample.txt").read_text()


@pytest.fixture
def metrics() -> AutheliaMetrics:
    return AutheliaMetrics.from_text(FIXTURE)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("authelia_authn", "authn"),
        ("authelia_authn_total", "authn"),
        ("authelia_authn_duration_seconds", "authn_duration"),
        ("go_goroutines", "go_goroutines"),
        ("go_memstats_alloc_bytes_total", "go_memstats_alloc_bytes_total"),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


def test_detects_authelia(metrics: AutheliaMetrics) -> None:
    assert metrics.has_authelia_metrics


def test_counters(metrics: AutheliaMetrics) -> None:
    assert metrics.value("authn", success="true") == 42
    assert metrics.value("authn", success="false") == 9
    assert metrics.value("authn", banned="true") == 2
    assert metrics.value("authn_second_factor", success="true", type="totp") == 30
    assert metrics.value("authn_second_factor", type="duo") == 0  # Familie da, Label nicht
    assert metrics.value("authz", code="401") == 35
    assert metrics.value("request") == 992
    assert metrics.value("does_not_exist") is None
    assert metrics.value("go_goroutines") == 23


def test_label_values(metrics: AutheliaMetrics) -> None:
    assert metrics.label_values("authz", "code") == {"200", "302", "401", "403"}


def test_histogram(metrics: AutheliaMetrics) -> None:
    hist = metrics.histogram("authn_duration")
    assert hist is not None
    assert hist.count == 51
    assert hist.sum == pytest.approx(28.7)
    assert hist.buckets[-1] == (math.inf, 51)
    ok = metrics.histogram("authn_duration", success="true")
    assert ok.average == pytest.approx(17.5 / 42)
    p50 = ok.quantile(0.5)
    assert 0.25 < p50 < 0.5
    # Histogramm-Familie liefert bei value() die Anzahl
    assert metrics.value("authn_duration", success="false") == 9


def test_histogram_minus_and_reset(metrics: AutheliaMetrics) -> None:
    newer = metrics.histogram("authn_duration")
    older = AutheliaMetrics.from_text(
        FIXTURE.replace('_count{success="true"} 42', '_count{success="true"} 40')
    ).histogram("authn_duration")
    diff = newer.minus(older)
    assert diff is not None and diff.count == 2
    assert older.minus(newer) is None  # Reset erkannt


def test_total_and_seconds_suffixes() -> None:
    text = """
# TYPE authelia_authn_total counter
authelia_authn_total{success="true",banned="false"} 5
# TYPE authelia_authn_duration_seconds histogram
authelia_authn_duration_seconds_bucket{success="true",le="+Inf"} 5
authelia_authn_duration_seconds_sum{success="true"} 1
authelia_authn_duration_seconds_count{success="true"} 5
"""
    m = AutheliaMetrics.from_text(text)
    assert m.value("authn", success="true") == 5
    assert m.histogram("authn_duration").count == 5


def test_counter_without_type_and_total_suffix() -> None:
    # Moderne Exposition: TYPE-Name ohne _total, Sample mit _total
    text = '# TYPE authelia_authz counter\nauthelia_authz_total{code="200"} 3\n'
    m = AutheliaMetrics.from_text(text)
    assert m.value("authz", code="200") == 3


def test_label_escaping_and_timestamp() -> None:
    fams = parse_prometheus_text('x{a="q\\"uo,te",b="n\\\\"} 1.5 1700000000000\n')
    sample = fams["x"].samples[0]
    assert sample.label("a") == 'q"uo,te'
    assert sample.label("b") == "n\\"
    assert sample.value == 1.5


@pytest.mark.parametrize("bad", ["", "# only comments\n", "<html>nope</html>"])
def test_invalid(bad: str) -> None:
    with pytest.raises(MetricsParseError):
        parse_prometheus_text(bad)


def test_quantile_edge_cases() -> None:
    assert estimate_quantile((), 0.5) is None
    assert estimate_quantile(((1.0, 0.0), (math.inf, 0.0)), 0.5) is None
    # alles im +Inf-Bucket -> letzte bekannte Grenze
    assert estimate_quantile(((1.0, 0.0), (math.inf, 4.0)), 0.9) == 1.0


REAL = (Path(__file__).parent / "fixtures" / "metrics_real_4.39.27.txt").read_text()


def test_real_4_39_27() -> None:
    m = AutheliaMetrics.from_text(REAL)
    assert m.has_authelia_metrics
    assert m.value("authn", success="false") == 1
    assert m.value("authn", success="true") == 1
    assert m.value("authn_second_factor", success="true", type="totp") == 1
    assert m.value("request") == 68
    assert m.value("request", code="401") == 1
    assert not m.has("authz")  # erst nach erstem Forward-Auth-Request
    assert m.histogram("authn_duration", success="true").sum == pytest.approx(0.234908778)
    # keine Kollision Gauge vs. Counter
    assert m.value("go_memstats_alloc_bytes") == pytest.approx(1.7053876e08)
    assert m.value("go_memstats_alloc_bytes_total") == pytest.approx(2.13816488e08)
    assert m.value("process_start_time_seconds") == pytest.approx(1.78963538643e09)
    assert m.value("go_gc_duration_seconds") == 8  # Summary -> _count
    assert m.label_values("go_info", "version") == {"go1.27.1"}
