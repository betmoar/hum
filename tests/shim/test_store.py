"""Unit tests for the favourites store and the recently-seen metadata cache."""
from __future__ import annotations

from pathlib import Path

from shim import store
from shim.store import FavouritesStore, StarredItem


def test_star_unstar_roundtrip(tmp_path: Path) -> None:
    s = FavouritesStore(tmp_path / "fav.json")
    item = StarredItem(id="vid:abc", kind="song", title="T", artist="A")
    s.star(item)
    assert s.is_starred("vid:abc")
    assert s.starred() == [item]
    s.unstar("vid:abc")
    assert not s.is_starred("vid:abc")
    assert s.starred() == []


def test_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "fav.json"
    FavouritesStore(path).star(StarredItem(id="pl:x", kind="album", title="Mix", artist="C"))
    reloaded = FavouritesStore(path)
    assert reloaded.is_starred("pl:x")
    assert reloaded.starred()[0].title == "Mix"


def test_creates_missing_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "dir" / "fav.json"
    FavouritesStore(nested).star(StarredItem(id="vid:y", kind="song", title="t", artist="a"))
    assert nested.exists()


def test_corrupt_file_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "fav.json"
    path.write_text("{not json")
    s = FavouritesStore(path)  # must not raise
    assert s.starred() == []


def test_seen_cache_remember_recall() -> None:
    store.reset_store()
    store.remember("vid:abc", "song", "Title", "Artist")
    assert store.recall("vid:abc") == ("song", "Title", "Artist")
    assert store.recall("vid:missing") is None


def test_seen_cache_is_bounded() -> None:
    store.reset_store()
    for i in range(store._SEEN_MAX + 50):
        store.remember(f"vid:{i:011d}", "song", "t", "a")
    assert len(store._seen) == store._SEEN_MAX
    # Oldest evicted, newest retained.
    assert store.recall("vid:00000000000") is None
    assert store.recall(f"vid:{store._SEEN_MAX + 49:011d}") is not None
