from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import threading
import time
from typing import Dict, Optional, Tuple


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split())


def _normalize_key_part(value: str) -> str:
    return value.strip().lower()


def dedupe_key(alert: Dict[str, str]) -> str:
    parts = [
        _normalize_key_part(alert["service"]),
        _normalize_key_part(alert["environment"]),
        _normalize_key_part(alert["error_code"]),
        _normalize_key_part(alert["resource"]),
        _normalize_text(alert["summary"]),
    ]
    combined = "|".join(parts)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def rate_limit_key(alert: Dict[str, str]) -> str:
    return "|".join([
        _normalize_key_part(alert["service"]),
        _normalize_key_part(alert["error_code"]),
    ])


@dataclass
class DedupeResult:
    deduped: bool
    dedupe_key: str
    retry_after: Optional[int]


class DedupeStore:
    def __init__(self, window_seconds: int, max_keys: int):
        self._window = window_seconds
        self._max_keys = max_keys
        self._lock = threading.Lock()
        self._store: "OrderedDict[str, float]" = OrderedDict()

    def check(self, key: str) -> DedupeResult:
        if self._window == 0:
            return DedupeResult(False, key, None)
        now = time.time()
        with self._lock:
            ts = self._store.get(key)
            if ts is not None and (now - ts) < self._window:
                remaining = int(self._window - (now - ts))
                self._store.move_to_end(key)
                return DedupeResult(True, key, max(0, remaining))
            self._store[key] = now
            self._store.move_to_end(key)
            while len(self._store) > self._max_keys:
                self._store.popitem(last=False)
        return DedupeResult(False, key, None)


@dataclass
class RateLimitResult:
    rate_limited: bool
    key: str
    retry_after: Optional[int]
    reset_at: Optional[int]


class RateLimiter:
    def __init__(self, max_per_window: int, window_seconds: int, max_keys: int):
        self._max = max_per_window
        self._window = window_seconds
        self._max_keys = max_keys
        self._lock = threading.Lock()
        self._store: "OrderedDict[str, Tuple[float, int]]" = OrderedDict()

    def check(self, key: str) -> RateLimitResult:
        if self._max == 0:
            return RateLimitResult(False, key, None, None)
        now = time.time()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._store[key] = (now, 1)
            else:
                window_start, count = entry
                if (now - window_start) >= self._window:
                    window_start = now
                    count = 1
                    self._store[key] = (window_start, count)
                else:
                    if count >= self._max:
                        reset_at = int(window_start + self._window)
                        retry_after = int(max(0, window_start + self._window - now))
                        self._store.move_to_end(key)
                        return RateLimitResult(True, key, retry_after, reset_at)
                    count += 1
                    self._store[key] = (window_start, count)
            self._store.move_to_end(key)
            while len(self._store) > self._max_keys:
                self._store.popitem(last=False)
        return RateLimitResult(False, key, None, None)
