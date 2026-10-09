"""In-process latency registry (last 2000 samples per metric), thread-safe."""
from __future__ import annotations

import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Deque, Dict, Iterator

WINDOW = 2000


def _percentile(sorted_values, pct: float) -> float:
    """Nearest-rank percentile of an already sorted, non-empty list."""
    rank = max(1, int(-(-pct / 100.0 * len(sorted_values) // 1)))  # ceil
    return sorted_values[min(rank, len(sorted_values)) - 1]


class MetricsRegistry:
    def __init__(self, window: int = WINDOW):
        self._window = window
        self._lock = threading.Lock()
        self._samples: Dict[str, Deque[float]] = {}
        self._count: Dict[str, int] = {}
        self._errors: Dict[str, int] = {}

    def record(self, name: str, ms: float, error: bool = False) -> None:
        with self._lock:
            self._samples.setdefault(name, deque(maxlen=self._window)).append(float(ms))
            self._count[name] = self._count.get(name, 0) + 1
            if error:
                self._errors[name] = self._errors.get(name, 0) + 1

    @contextmanager
    def timed(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        failed = False
        try:
            yield
        except BaseException:
            failed = True
            raise
        finally:
            self.record(name, (time.perf_counter() - start) * 1000.0, error=failed)

    def snapshot(self) -> Dict[str, dict]:
        with self._lock:
            result: Dict[str, dict] = {}
            for name, samples in self._samples.items():
                if not samples:
                    continue
                ordered = sorted(samples)
                result[name] = {
                    "count": self._count.get(name, 0),
                    "samples": len(ordered),
                    "avg_ms": sum(ordered) / len(ordered),
                    "p50_ms": _percentile(ordered, 50),
                    "p95_ms": _percentile(ordered, 95),
                    "p99_ms": _percentile(ordered, 99),
                    "errors": self._errors.get(name, 0),
                }
            return result

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()
            self._count.clear()
            self._errors.clear()


metrics = MetricsRegistry()
