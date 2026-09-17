"""Parser für das Prometheus-Textformat und Authelia-Metrik-Modell.

Bewusst ohne externe Abhängigkeiten (kein prometheus_client) und ohne
Home-Assistant-Imports, damit das Modul isoliert testbar bleibt.

Namens-Normalisierung: Authelia registriert seine Metriken mit dem Prefix
``authelia_``. Ob Counter ein ``_total``- und Histogramme ein ``_seconds``-
Suffix tragen, hängt von Version und Exposition ab. Deshalb werden alle
Familien auf einen Basisnamen normalisiert (z. B. ``authelia_authn_total`` ->
``authn``), sodass der restliche Code davon unabhängig ist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

PREFIX = "authelia_"
_HISTOGRAM_SUFFIXES = ("_bucket", "_sum", "_count")
_SUMMARY_SUFFIXES = ("_sum", "_count")


class MetricsParseError(ValueError):
    """Die Antwort ist kein gültiges Prometheus-Textformat."""


Labels = tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class Sample:
    """Ein einzelner Messwert."""

    name: str
    labels: Labels
    value: float

    def label(self, key: str) -> str | None:
        """Wert eines Labels oder None."""
        for k, v in self.labels:
            if k == key:
                return v
        return None

    def matches(self, filters: dict[str, str]) -> bool:
        """True, wenn alle Label-Filter zutreffen."""
        return all(self.label(k) == v for k, v in filters.items())


@dataclass(slots=True)
class MetricFamily:
    """Eine Metrik-Familie (alle Samples eines Namens inkl. Suffixe)."""

    name: str
    type: str = "untyped"
    help: str = ""
    samples: list[Sample] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Low-Level-Parser
# --------------------------------------------------------------------------- #


def _parse_value(raw: str) -> float:
    match raw:
        case "+Inf" | "Inf":
            return math.inf
        case "-Inf":
            return -math.inf
        case "NaN":
            return math.nan
    try:
        return float(raw)
    except ValueError as err:
        raise MetricsParseError(f"Ungültiger Wert: {raw!r}") from err


def _parse_labels(text: str, pos: int, line: str) -> tuple[Labels, int]:
    """Parst ``{a="b",c="d"}`` ab ``pos`` (zeigt auf ``{``)."""
    labels: list[tuple[str, str]] = []
    pos += 1
    length = len(text)
    while True:
        while pos < length and text[pos] in " ,":
            pos += 1
        if pos >= length:
            raise MetricsParseError(f"Label-Block nicht geschlossen: {line!r}")
        if text[pos] == "}":
            return tuple(labels), pos + 1
        eq = text.find("=", pos)
        if eq == -1:
            raise MetricsParseError(f"Label ohne '=': {line!r}")
        key = text[pos:eq].strip()
        pos = eq + 1
        if pos >= length or text[pos] != '"':
            raise MetricsParseError(f"Label-Wert ohne Anführungszeichen: {line!r}")
        pos += 1
        value_chars: list[str] = []
        while True:
            if pos >= length:
                raise MetricsParseError(f"Label-Wert nicht geschlossen: {line!r}")
            char = text[pos]
            if char == "\\" and pos + 1 < length:
                nxt = text[pos + 1]
                value_chars.append({"n": "\n", '"': '"', "\\": "\\"}.get(nxt, nxt))
                pos += 2
                continue
            if char == '"':
                pos += 1
                break
            value_chars.append(char)
            pos += 1
        labels.append((key, "".join(value_chars)))


def _parse_sample_line(line: str) -> Sample:
    brace = line.find("{")
    space = line.find(" ")
    if brace != -1 and (space == -1 or brace < space):
        name = line[:brace]
        labels, pos = _parse_labels(line, brace, line)
        rest = line[pos:].split()
    else:
        parts = line.split()
        name, labels, rest = parts[0], (), parts[1:]
    if not rest:
        raise MetricsParseError(f"Sample ohne Wert: {line!r}")
    # optionaler Timestamp (rest[1]) wird ignoriert
    return Sample(name=name, labels=labels, value=_parse_value(rest[0]))


def parse_prometheus_text(text: str) -> dict[str, MetricFamily]:
    """Parst Prometheus-Text in Familien, Schlüssel = Original-Familienname."""
    families: dict[str, MetricFamily] = {}

    def family_for(sample_name: str) -> MetricFamily:
        if sample_name in families:
            return families[sample_name]
        for suffix in (*_HISTOGRAM_SUFFIXES, "_total", "_created"):
            if sample_name.endswith(suffix):
                base = sample_name[: -len(suffix)]
                fam = families.get(base)
                if fam is not None and fam.type in ("histogram", "summary", "counter"):
                    return fam
        fam = MetricFamily(name=sample_name)
        families[sample_name] = fam
        return fam

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            parts = line.split(None, 3)
            if len(parts) >= 3 and parts[1] in ("TYPE", "HELP"):
                fam = families.setdefault(parts[2], MetricFamily(name=parts[2]))
                if parts[1] == "TYPE" and len(parts) == 4:
                    fam.type = parts[3].strip()
                elif parts[1] == "HELP":
                    fam.help = parts[3] if len(parts) == 4 else ""
            continue
        sample = _parse_sample_line(line)
        family_for(sample.name).samples.append(sample)

    if not any(f.samples for f in families.values()):
        raise MetricsParseError("Keine Samples in der Antwort gefunden")
    return families


# --------------------------------------------------------------------------- #
# Authelia-Modell
# --------------------------------------------------------------------------- #


def normalize_name(name: str) -> str:
    """``authelia_authn_duration_seconds`` -> ``authn_duration``.

    Nur ``authelia_``-Familien werden normalisiert. Fremde Familien
    (``go_*``, ``process_*``) behalten ihren Namen, sonst kollidiert z. B.
    ``go_memstats_alloc_bytes_total`` mit ``go_memstats_alloc_bytes``.
    """
    if not name.startswith(PREFIX):
        return name
    name = name[len(PREFIX) :]
    for suffix in ("_total", "_seconds"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


@dataclass(frozen=True, slots=True)
class Histogram:
    """Kumulatives Histogramm (seit Authelia-Start)."""

    buckets: tuple[tuple[float, float], ...]  # (le, kumulative Anzahl), sortiert
    sum: float
    count: float

    @property
    def average(self) -> float | None:
        """Mittelwert oder None ohne Beobachtungen."""
        return self.sum / self.count if self.count else None

    def quantile(self, q: float) -> float | None:
        """Quantil-Schätzung wie PromQL ``histogram_quantile``."""
        return estimate_quantile(self.buckets, q)

    def minus(self, older: Histogram) -> Histogram | None:
        """Differenz zu einem älteren Stand; None bei Reset."""
        if self.count < older.count:
            return None
        old = dict(older.buckets)
        buckets = tuple((le, cnt - old.get(le, 0.0)) for le, cnt in self.buckets)
        return Histogram(buckets, self.sum - older.sum, self.count - older.count)


def estimate_quantile(
    buckets: tuple[tuple[float, float], ...], q: float
) -> float | None:
    """Lineare Interpolation innerhalb des Ziel-Buckets."""
    if not buckets:
        return None
    total = buckets[-1][1]
    if total <= 0:
        return None
    rank = q * total
    prev_le, prev_count = 0.0, 0.0
    for le, count in buckets:
        if count >= rank:
            if math.isinf(le):
                return prev_le  # obere Grenze unbekannt
            if count == prev_count:
                return le
            return prev_le + (le - prev_le) * (rank - prev_count) / (count - prev_count)
        prev_le, prev_count = le, count
    return prev_le


class AutheliaMetrics:
    """Normalisierte Sicht auf einen /metrics-Abruf."""

    def __init__(self, families: dict[str, MetricFamily]) -> None:
        self._families: dict[str, MetricFamily] = {}
        self.raw_family_names = sorted(families)
        for fam in families.values():
            if fam.samples:
                self._families[normalize_name(fam.name)] = fam

    @classmethod
    def from_text(cls, text: str) -> AutheliaMetrics:
        return cls(parse_prometheus_text(text))

    # -- Allgemein ---------------------------------------------------------- #

    @property
    def has_authelia_metrics(self) -> bool:
        """True, wenn mindestens eine ``authelia_``-Familie vorhanden ist."""
        return any(n.startswith(PREFIX) for n in self.raw_family_names)

    def has(self, name: str) -> bool:
        return name in self._families

    def family(self, name: str) -> MetricFamily | None:
        return self._families.get(name)

    def label_values(self, name: str, label: str) -> set[str]:
        """Alle vorkommenden Werte eines Labels."""
        fam = self._families.get(name)
        if fam is None:
            return set()
        return {v for s in fam.samples if (v := s.label(label)) is not None}

    # -- Counter / Gauge ---------------------------------------------------- #

    def value(self, name: str, **filters: str) -> float | None:
        """Summe aller passenden Samples; None wenn Familie fehlt.

        Fehlt die Familie komplett -> None (Metrik nicht exponiert).
        Existiert sie, aber kein Label passt -> 0.0 (noch kein Ereignis).
        Für Histogramm-Familien wird ``_count`` summiert.
        """
        fam = self._families.get(name)
        if fam is None:
            return None
        total = 0.0
        for sample in fam.samples:
            if fam.type in ("histogram", "summary") and not sample.name.endswith("_count"):
                continue
            if sample.name.endswith("_created"):
                continue
            if sample.matches(filters):
                total += sample.value
        return total

    # -- Histogramme -------------------------------------------------------- #

    def histogram(self, name: str, **filters: str) -> Histogram | None:
        """Aggregiertes Histogramm über alle passenden Label-Kombinationen."""
        fam = self._families.get(name)
        if fam is None:
            return None
        buckets: dict[float, float] = {}
        total_sum = 0.0
        total_count = 0.0
        found = False
        for sample in fam.samples:
            if not sample.matches(filters):
                continue
            if sample.name.endswith("_bucket"):
                le_raw = sample.label("le")
                if le_raw is None:
                    continue
                le = _parse_value(le_raw)
                buckets[le] = buckets.get(le, 0.0) + sample.value
                found = True
            elif sample.name.endswith("_sum"):
                total_sum += sample.value
                found = True
            elif sample.name.endswith("_count"):
                total_count += sample.value
                found = True
        if not found:
            return Histogram((), 0.0, 0.0)
        return Histogram(tuple(sorted(buckets.items())), total_sum, total_count)
