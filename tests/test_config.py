from __future__ import annotations

import unittest

from pydantic import ValidationError

from larpcard.config import Settings


class SettingsTests(unittest.TestCase):
    def test_drop_range_is_validated(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(drop_min_cards=4, drop_max_cards=2)

    def test_defaults_match_supported_drop_range(self) -> None:
        settings = Settings(_env_file=None)

        self.assertEqual(settings.drop_min_cards, 2)
        self.assertEqual(settings.drop_max_cards, 4)
