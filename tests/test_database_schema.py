from __future__ import annotations

import unittest

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from larpcard.database import models as _models  # noqa: F401
from larpcard.database.base import Base


class DatabaseSchemaTests(unittest.TestCase):
    def test_expected_tables_are_registered(self) -> None:
        self.assertEqual(
            set(Base.metadata.tables),
            {
                "series",
                "characters",
                "card_definitions",
                "players",
                "series_priorities",
                "drops",
                "drop_slots",
                "owned_cards",
                "transactions",
                "reward_claims",
                "marketplace_listings",
                "trades",
                "trade_cards",
            },
        )

    def test_all_tables_compile_for_postgresql(self) -> None:
        dialect = postgresql.dialect()

        statements = [
            str(CreateTable(table).compile(dialect=dialect))
            for table in Base.metadata.sorted_tables
        ]

        self.assertEqual(len(statements), 13)
        self.assertTrue(all("CREATE TABLE" in statement for statement in statements))
