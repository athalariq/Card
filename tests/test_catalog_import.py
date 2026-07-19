from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from larpcard.cards.domain import Rarity
from larpcard.tools.catalog_import import CatalogImporter, load_catalog, slugify


class CatalogImportTests(unittest.TestCase):
    def test_load_catalog_validates_and_parses_rarity(self) -> None:
        payload = [
            {
                "character": "Character",
                "series": "Series",
                "image": "artwork/card.png",
                "rarity": "legendary",
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            cards = load_catalog(path)

        self.assertEqual(cards[0].rarity, Rarity.LEGENDARY)
        self.assertEqual(cards[0].edition, "standard")

    def test_unknown_fields_are_rejected(self) -> None:
        payload = [
            {
                "character": "Character",
                "series": "Series",
                "image": "artwork/card.png",
                "rarity": "common",
                "rarity_text_from_ocr": "common",
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(ValidationError):
                load_catalog(path)

    def test_slugify_is_stable(self) -> None:
        self.assertEqual(slugify("Jujutsu Kaisen"), "jujutsu-kaisen")

    def test_asset_validation_blocks_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            importer = CatalogImporter(
                database=object(),  # type: ignore[arg-type]
                asset_root=Path(directory),
            )

            with self.assertRaises(ValueError):
                importer.validate_asset_path("../outside.png")
