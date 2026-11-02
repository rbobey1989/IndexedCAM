"""Create, rename, delete and order indexed setups through a storage backend."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Protocol, Sequence

from IndexedCAM.Core.indexed_setup import IndexedSetup


class SetupStorage(Protocol):
    """Persistence backend holding the serialized setups in order."""

    def load(self) -> List[Dict[str, Any]]:
        ...

    def save(self, setups: Sequence[Mapping[str, Any]]) -> None:
        ...


class MemoryStorage:
    """In-memory storage, useful for tests and non-persistent use."""

    def __init__(self) -> None:
        self._data: List[Dict[str, Any]] = []

    def load(self) -> List[Dict[str, Any]]:
        return [dict(item) for item in self._data]

    def save(self, setups: Sequence[Mapping[str, Any]]) -> None:
        self._data = [dict(item) for item in setups]


class SetupManager:
    """Ordered collection of setups with unique (case-insensitive) names.

    Every mutation validates first and persists afterwards, so a failed
    operation leaves both memory and storage unchanged.
    """

    def __init__(self, storage: SetupStorage) -> None:
        self._storage = storage
        self._setups: List[IndexedSetup] = [
            IndexedSetup.from_dict(item) for item in storage.load()
        ]
        self._check_unique_names()

    def _check_unique_names(self) -> None:
        names = [s.name.casefold() for s in self._setups]
        if len(names) != len(set(names)):
            raise ValueError("stored setups contain duplicate names")

    def _persist(self) -> None:
        self._storage.save([s.to_dict() for s in self._setups])

    def _index(self, name: str) -> int:
        key = name.strip().casefold()
        for i, setup in enumerate(self._setups):
            if setup.name.casefold() == key:
                return i
        raise KeyError("setup not found: {}".format(name))

    def names(self) -> List[str]:
        return [s.name for s in self._setups]

    def list(self) -> List[IndexedSetup]:
        """Setups in order (the objects themselves; call ``update`` after editing)."""
        return list(self._setups)

    def get(self, name: str) -> IndexedSetup:
        return self._setups[self._index(name)]

    def __len__(self) -> int:
        return len(self._setups)

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        try:
            self._index(name)
        except KeyError:
            return False
        return True

    def add(self, setup: IndexedSetup) -> IndexedSetup:
        if setup.name in self:
            raise ValueError("setup name already exists: {}".format(setup.name))
        self._setups.append(setup)
        self._persist()
        return setup

    def update(self, setup: IndexedSetup) -> None:
        """Persist in-place edits made to a managed setup."""
        if not any(s is setup for s in self._setups):
            raise KeyError("setup is not managed: {}".format(setup.name))
        self._persist()

    def rename(self, old: str, new: str) -> None:
        index = self._index(old)
        new = new.strip()
        if not new:
            raise ValueError("setup name must not be empty")
        if new.casefold() != old.strip().casefold() and new in self:
            raise ValueError("setup name already exists: {}".format(new))
        self._setups[index].name = new
        self._persist()

    def delete(self, name: str) -> IndexedSetup:
        removed = self._setups.pop(self._index(name))
        self._persist()
        return removed

    def move(self, name: str, position: int) -> None:
        """Move a setup to ``position`` (0-based, clamped to the valid range)."""
        index = self._index(name)
        position = max(0, min(position, len(self._setups) - 1))
        self._setups.insert(position, self._setups.pop(index))
        self._persist()

    def reorder(self, names: Sequence[str]) -> None:
        """Reorder using a permutation of all current names."""
        if sorted(n.casefold() for n in names) != sorted(
            s.name.casefold() for s in self._setups
        ):
            raise ValueError("names must be a permutation of the existing setups")
        self._setups = [self.get(n) for n in names]
        self._persist()

    def unique_name(self, base: str = "Setup") -> str:
        """First free name of the form ``base``, ``base 2``, ``base 3``..."""
        candidate, n = base, 1
        while candidate in self:
            n += 1
            candidate = "{} {}".format(base, n)
        return candidate
