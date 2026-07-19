from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

from PIL import Image


class ArtworkNotFoundError(FileNotFoundError):
    pass


class ArtworkStore(Protocol):
    async def load(self, relative_path: str) -> Image.Image: ...


class LocalArtworkStore:
    """Loads artwork from a configured root while preventing path traversal."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    async def load(self, relative_path: str) -> Image.Image:
        return await asyncio.to_thread(self._load_sync, relative_path)

    def _load_sync(self, relative_path: str) -> Image.Image:
        path = (self._root / relative_path).resolve()
        if not path.is_relative_to(self._root):
            raise ArtworkNotFoundError("artwork path escapes the configured asset root")
        if not path.is_file():
            raise ArtworkNotFoundError(f"artwork does not exist: {relative_path}")
        with Image.open(path) as source:
            return source.convert("RGBA")
