from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from PIL import Image

from larpcard.cards.assets import ArtworkNotFoundError, LocalArtworkStore
from larpcard.cards.domain import CardTemplate, Rarity, RenderCard, rarity_style
from larpcard.cards.renderer import CARD_SIZE, CardRenderer


class RarityTests(unittest.TestCase):
    def test_rarity_is_visual_metadata(self) -> None:
        common = rarity_style(Rarity.COMMON)
        legendary = rarity_style(Rarity.LEGENDARY)

        self.assertEqual(common.stars, 1)
        self.assertEqual(legendary.stars, 5)
        self.assertNotEqual(common.accent_rgb, legendary.accent_rgb)
        self.assertGreater(common.default_drop_weight, legendary.default_drop_weight)

    def test_card_template_rejects_invalid_weight(self) -> None:
        with self.assertRaises(ValueError):
            CardTemplate(
                id=uuid4(),
                character_name="Character",
                series_name="Series",
                aliases=(),
                image_path="artwork/card.png",
                frame_path=None,
                rarity=Rarity.COMMON,
                edition="standard",
                variant="base",
                drop_weight=0,
            )


class RendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self.renderer = CardRenderer(render_scale=1)
        self.artwork = Image.new("RGB", (800, 1200), (76, 82, 104))

    def test_renderer_produces_exact_transparent_rounded_card(self) -> None:
        card = RenderCard(
            template_id=uuid4(),
            character_name="Gojo Satoru",
            series_name="Jujutsu Kaisen",
            rarity=Rarity.LEGENDARY,
            print_number=42,
            edition="First Edition",
            variant="Base",
        )

        rendered = self.renderer.render(card, self.artwork)

        self.assertEqual(rendered.size, CARD_SIZE)
        self.assertEqual(rendered.mode, "RGBA")
        self.assertGreater(rendered.getpixel((CARD_SIZE[0] // 2, CARD_SIZE[1] // 2))[3], 0)

    def test_long_text_and_placeholder_render_without_resizing_layout(self) -> None:
        card = RenderCard(
            template_id=uuid4(),
            character_name="A Character Name That Is Intentionally Very Long",
            series_name="An Equally Long Series Name Used For Layout Verification",
            rarity=Rarity.COMMON,
            print_number=1_234_567,
            edition="Anniversary",
            variant="Alternate",
        )
        placeholder = self.renderer.placeholder_artwork(
            card.character_name,
            rarity_style(card.rarity).accent_rgb,
        )

        rendered = self.renderer.render(card, placeholder)

        self.assertEqual(rendered.size, CARD_SIZE)

    def test_drop_sheet_supports_four_cards(self) -> None:
        cards = [Image.new("RGBA", CARD_SIZE, (20 + i, 30, 40, 255)) for i in range(4)]

        sheet = self.renderer.compose_drop(cards)

        self.assertEqual(sheet.mode, "RGBA")
        self.assertGreater(sheet.width, CARD_SIZE[0])
        self.assertGreater(sheet.height, CARD_SIZE[1])


class ArtworkStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_store_loads_image_and_blocks_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "artwork" / "sample.png"
            source.parent.mkdir()
            Image.new("RGB", (4, 4), "red").save(source)
            store = LocalArtworkStore(root)

            loaded = await store.load("artwork/sample.png")

            self.assertEqual(loaded.size, (4, 4))
            with self.assertRaises(ArtworkNotFoundError):
                await store.load("../outside.png")
