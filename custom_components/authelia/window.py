"""Rollierende Zeitfenster über Prometheus-Counter.

Authelia-Counter zählen seit dem Prozessstart. Startet Authelia neu, fallen
sie auf 0 zurück. Der Tracker bildet daraus eine *virtuell monotone* Reihe
(Offset wird bei jedem Reset um den letzten Wert erhöht) und kann damit
beliebige Fenster-Deltas ("fehlgeschlagene Logins in den letzten 5 Minuten")
berechnen – auch über Neustarts hinweg.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .metrics import Histogram


@dataclass(slots=True)
class CounterWindow:
    """Hält (Zeitstempel, monotoner Wert)-Paare für ein maximales Fenster."""

    max_age: float
    _points: deque[tuple[float, float]] = field(default_factory=deque)
    _offset: float = 0.0
    _last_raw: float | None = None
    resets: int = 0

    def add(self, timestamp: float, raw_value: float) -> None:
        """Neuen Rohwert (seit Prozessstart) einspeisen."""
        if self._last_raw is not None and raw_value < self._last_raw:
            # Counter-Reset (Authelia-Neustart)
            self._offset += self._last_raw
            self.resets += 1
        self._last_raw = raw_value
        self._points.append((timestamp, self._offset + raw_value))
        self._prune(timestamp)

    def _prune(self, now: float) -> None:
        # Einen Punkt älter als max_age behalten, damit das volle Fenster
        # als Basis dient.
        while len(self._points) >= 2 and self._points[1][0] <= now - self.max_age:
            self._points.popleft()

    def delta(self, window: float, now: float) -> float | None:
        """Zuwachs innerhalb der letzten ``window`` Sekunden.

        None, solange noch keine zwei Messpunkte existieren.
        Ist die Historie kürzer als das Fenster, wird ab dem ältesten
        vorhandenen Punkt gerechnet (Wert wächst also nach dem HA-Start an).
        """
        if len(self._points) < 2:
            return None
        latest = self._points[-1][1]
        base = self._points[0][1]
        cutoff = now - window
        for ts, value in self._points:
            if ts <= cutoff:
                base = value
            else:
                break
        return max(latest - base, 0.0)

    @property
    def covered_seconds(self) -> float:
        """Wie viel Historie tatsächlich vorliegt."""
        if len(self._points) < 2:
            return 0.0
        return self._points[-1][0] - self._points[0][0]


class HistogramWindow:
    """Hält Histogramm-Stände, um Kennzahlen über ein Zeitfenster zu bilden.

    Beispiel: durchschnittliche Anmeldedauer der letzten Stunde statt seit
    dem Authelia-Start. Bei einem Reset (Neustart) wird die Historie verworfen.
    """

    def __init__(self, max_age: float) -> None:
        self.max_age = max_age
        self._points: deque[tuple[float, Histogram]] = deque()

    def add(self, timestamp: float, hist: Histogram) -> None:
        if self._points and hist.count < self._points[-1][1].count:
            self._points.clear()
        self._points.append((timestamp, hist))
        while len(self._points) >= 2 and self._points[1][0] <= timestamp - self.max_age:
            self._points.popleft()

    def over(self, window: float, now: float) -> Histogram | None:
        """Differenz-Histogramm für die letzten ``window`` Sekunden."""
        if len(self._points) < 2:
            return None
        latest = self._points[-1][1]
        base = self._points[0][1]
        for ts, hist in self._points:
            if ts <= now - window:
                base = hist
            else:
                break
        return latest.minus(base)
