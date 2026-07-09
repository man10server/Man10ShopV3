from __future__ import annotations

import threading
from collections.abc import MutableMapping, Iterator

from cachetools import TTLCache


class TTLDict(MutableMapping):

    def __init__(self, ttl: float, maxsize: int = 100_000):
        self._lock = threading.RLock()
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)

    def __getitem__(self, key):
        with self._lock:
            return self._cache[key]

    def __setitem__(self, key, value):
        with self._lock:
            self._cache[key] = value

    def __delitem__(self, key):
        with self._lock:
            del self._cache[key]

    def pop(self, key, *args):
        with self._lock:
            return self._cache.pop(key, *args)

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)

    def __contains__(self, key) -> bool:
        with self._lock:
            return key in self._cache

    def __iter__(self) -> Iterator:
        with self._lock:
            return iter(list(self._cache))
