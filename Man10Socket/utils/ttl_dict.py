from __future__ import annotations

import logging
import threading
import time
import weakref
from collections.abc import MutableMapping, Iterator

from cachetools import TTLCache


# Match the old cleanup cadence without creating a worker for every dictionary.
_CLEANUP_INTERVAL_SECONDS = 0.1
_CLEANUP_THREAD_NAME = "Man10Socket-TTL-Cleanup"
_logger = logging.getLogger(__name__)


class TTLDict(MutableMapping):

    def __init__(self, ttl: float, maxsize: int = 100_000):
        self._lock = threading.RLock()
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)
        _register_ttl_dict(self)

    def _expire(self):
        with self._lock:
            self._cache.expire()

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


_registry_lock = threading.Lock()
# Closed connections can be collected even though the shared worker lives for the process.
_ttl_dicts: weakref.WeakValueDictionary[int, TTLDict] = weakref.WeakValueDictionary()
_cleanup_thread: threading.Thread | None = None


def _expire_registered_ttl_dicts():
    with _registry_lock:
        ttl_dicts = list(_ttl_dicts.values())
    for ttl_dict in ttl_dicts:
        try:
            ttl_dict._expire()
        except Exception:
            _logger.exception("Failed to clean expired TTLDict entries")


def _cleanup_expired_entries():
    while True:
        time.sleep(_CLEANUP_INTERVAL_SECONDS)
        _expire_registered_ttl_dicts()


def _register_ttl_dict(ttl_dict: TTLDict):
    global _cleanup_thread

    with _registry_lock:
        _ttl_dicts[id(ttl_dict)] = ttl_dict
        if _cleanup_thread is None or not _cleanup_thread.is_alive():
            _cleanup_thread = threading.Thread(
                target=_cleanup_expired_entries,
                name=_CLEANUP_THREAD_NAME,
                daemon=True,
            )
            _cleanup_thread.start()
