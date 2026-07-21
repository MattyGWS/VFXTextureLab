from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class CacheStats:
    entries: int
    bytes_used: int
    budget_bytes: int
    hits: int
    misses: int
    evictions: int


class MemoryLRU(Generic[T]):
    """Byte-budgeted LRU cache for CPU arrays and GPU textures."""

    def __init__(self, budget_bytes: int) -> None:
        self.budget_bytes = max(int(budget_bytes), 1)
        self._items: OrderedDict[str, T] = OrderedDict()
        self._bytes = 0
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def get(self, key: str) -> T | None:
        item = self._items.get(key)
        if item is None:
            self.misses += 1
            return None
        self.hits += 1
        self._items.move_to_end(key)
        return item

    def put(self, key: str, item: T) -> None:
        existing = self._items.pop(key, None)
        if existing is not None:
            self._bytes -= self._item_bytes(existing)
            if existing is not item:
                self._release(existing)
        self._items[key] = item
        self._bytes += self._item_bytes(item)
        self._items.move_to_end(key)
        self._evict_to_budget(protected_key=key)

    def remove(self, key: str) -> None:
        item = self._items.pop(key, None)
        if item is None:
            return
        self._bytes -= self._item_bytes(item)
        self._release(item)

    def take(self, key: str) -> T | None:
        """Remove and return an item without releasing its owned resources."""
        item = self._items.pop(key, None)
        if item is None:
            return None
        self._bytes -= self._item_bytes(item)
        return item

    def clear(self) -> None:
        for item in self._items.values():
            self._release(item)
        self._items.clear()
        self._bytes = 0

    def set_budget(self, budget_bytes: int, *, protected_key: str | None = None) -> None:
        self.budget_bytes = max(int(budget_bytes), 1)
        self._evict_to_budget(protected_key=protected_key)

    def stats(self) -> CacheStats:
        return CacheStats(
            entries=len(self._items),
            bytes_used=self._bytes,
            budget_bytes=self.budget_bytes,
            hits=self.hits,
            misses=self.misses,
            evictions=self.evictions,
        )

    def _evict_to_budget(self, protected_key: str | None = None) -> None:
        while self._bytes > self.budget_bytes and self._items:
            oldest_key = next(iter(self._items))
            if oldest_key == protected_key and len(self._items) == 1:
                # A single image larger than the budget is still useful for the
                # current evaluation. It will be evicted when another item lands.
                break
            if oldest_key == protected_key:
                self._items.move_to_end(oldest_key)
                continue
            item = self._items.pop(oldest_key)
            self._bytes -= self._item_bytes(item)
            self._release(item)
            self.evictions += 1

    @staticmethod
    def _item_bytes(item: T) -> int:
        return int(getattr(item, "bytes_used", 0))

    @staticmethod
    def _release(item: T) -> None:
        release = getattr(item, "release", None)
        if callable(release):
            release()
