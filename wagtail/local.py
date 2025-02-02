import time
from typing import Any, Optional

from asgiref.local import Local


_VALUES = Local()
_VALUES.value = {}
_VALUE_TIMEOUTS = Local()
_VALUE_TIMEOUTS.value = {}
_ENABLED = Local()
_ENABLED.value = False


def _enable_local_cache():
    _ENABLED.value = True


def _disable_local_cache():
    _ENABLED.value = False


class LocalCacheManager:
    def is_enabled(self):
        return _ENABLED.value

    def _is_expired(self, key: str) -> bool:
        expires = _VALUE_TIMEOUTS.value.get(key, None)
        return expires is None or expires <= time.time()

    def set(self, key: str, value: Any, timeout: Optional[int] = None) -> None:
        if self.is_enabled():
            _VALUES.value[key] = value
            if timeout is not None:
                _VALUE_TIMEOUTS.value[key] = time.time() + timeout

    def get(self, key: str, default=None) -> Any:
        if self._is_expired(key):
            del _VALUES.value[key]
            del _VALUE_TIMEOUTS.value[key]
            return default
        if self.is_enabled():
            return _VALUES.value.get(key, default)
        return default

    def remove(self, key: str) -> None:
        _VALUES.value.pop(key, None)
        _VALUE_TIMEOUTS.value.pop(key, None)

    def clear(self) -> None:
        _VALUES.value.clear()
        _VALUE_TIMEOUTS.value.clear()


local_cache = LocalCacheManager()


class EnableLocalCacheContextManager:
    def __enter__(self):
        self.was_enabled = _ENABLED.value
        if not self.was_enabled:
            _enable_local_cache()

    def __exit__(self, exc_type, exc_value, traceback):
        if not self.was_enabled:
            _disable_local_cache()
            local_cache.clear()


local_cache_enabled = EnableLocalCacheContextManager
