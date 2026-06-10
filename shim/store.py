"""Shim-side persistence for favourites (spec §3.3/§9.4 — Hum stores nothing).

A small JSON file with atomic writes, mirrored by an in-process dict. Single
user, single worker, so the event loop serializes writes; no extra locking.

`star` only receives an id from Subsonic clients, so display metadata (title,
artist) is recalled from a bounded cache of items the shim has recently emitted
(`remember`/`recall`). This lets getStarred2 render names without re-fetching
from Hum (which would trigger pytubefix extraction).
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path

from shim.config import DATA_DIR_DEFAULT, get_settings


@dataclass(frozen=True)
class StarredItem:
    id: str
    kind: str  # "song" | "album"
    title: str
    artist: str


class FavouritesStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._items: dict[str, StarredItem] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text())
        except (FileNotFoundError, ValueError):
            return
        for d in raw.get("items", []):
            with contextlib.suppress(KeyError, TypeError):
                item = StarredItem(
                    id=str(d["id"]),
                    kind=str(d["kind"]),
                    title=str(d.get("title", "")),
                    artist=str(d.get("artist", "")),
                )
                self._items[item.id] = item

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"items": [asdict(i) for i in self._items.values()]}
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f)
            os.replace(tmp, self._path)  # atomic on POSIX
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)
            raise

    def star(self, item: StarredItem) -> None:
        self._items[item.id] = item
        self._save()

    def unstar(self, item_id: str) -> None:
        if self._items.pop(item_id, None) is not None:
            self._save()

    def is_starred(self, item_id: str) -> bool:
        return item_id in self._items

    def starred(self) -> list[StarredItem]:
        return list(self._items.values())


# ----- recently-emitted metadata cache (for star without re-fetch) ----------

_SEEN_MAX = 512
_seen: OrderedDict[str, tuple[str, str, str]] = OrderedDict()


def remember(item_id: str, kind: str, title: str, artist: str) -> None:
    _seen[item_id] = (kind, title, artist)
    _seen.move_to_end(item_id)
    while len(_seen) > _SEEN_MAX:
        _seen.popitem(last=False)


def recall(item_id: str) -> tuple[str, str, str] | None:
    return _seen.get(item_id)


# ----- singleton (mirrors hum_client.get_client) ----------------------------

_store: FavouritesStore | None = None


def get_store() -> FavouritesStore:
    global _store
    if _store is None:
        data_dir = Path(get_settings().data_dir) if get_settings().data_dir else DATA_DIR_DEFAULT
        _store = FavouritesStore(data_dir / "favourites.json")
    return _store


def reset_store() -> None:
    """Test seam: drop the singleton and the seen-cache."""
    global _store
    _store = None
    _seen.clear()
