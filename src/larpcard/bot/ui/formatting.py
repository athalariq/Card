"""Small shared presentation helpers for card-related Discord embeds."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Protocol

import discord

from larpcard.cards.domain import Rarity
from larpcard.economy.domain import Balance, CurrencyType, Transaction, TransactionType

COIN = "\U0001FA99"
GEM = "\U0001F48E"
TOKEN = "\U0001F3AB"
STAR = "\u2B50"
FIRE = "\U0001F525"
GIFT = "\U0001F381"

RARITY_EMOJI: dict[Rarity, str] = {
    Rarity.COMMON: "\U0001F539",
    Rarity.LEGENDARY: "\U0001F7E1",
}


def rarity_icon(rarity: Rarity) -> str:
    return RARITY_EMOJI.get(rarity, "\u2B1C")


def currency_icon(currency: CurrencyType) -> str:
    match currency:
        case CurrencyType.COINS:
            return COIN
        case CurrencyType.GEMS:
            return GEM
        case CurrencyType.EVENT_TOKENS:
            return TOKEN


def balance_text(balance: Balance) -> str:
    return (
        f"{COIN} **{balance.coins:,}** coins\n"
        f"{GEM} **{balance.gems:,}** gems\n"
        f"{TOKEN} **{balance.event_tokens:,}** event tokens"
    )


class CardLineData(Protocol):
    """Structural subset shared by inventory, listing, and trade cards."""

    @property
    def character_name(self) -> str: ...

    @property
    def print_number(self) -> int: ...

    @property
    def rarity(self) -> Rarity: ...

    @property
    def edition(self) -> str: ...

    @property
    def variant(self) -> str: ...


def card_line(card: CardLineData, *, favorite: bool = False) -> str:
    suffix = f" {STAR}" if favorite else ""
    detail = _variant_detail(card.edition, card.variant)
    return (
        f"{rarity_icon(card.rarity)} **{card.character_name}** "
        f"`#{card.print_number}`{detail}{suffix}"
    )


def transaction_icon(transaction_type: TransactionType) -> str:
    match transaction_type:
        case TransactionType.DAILY_REWARD | TransactionType.WEEKLY_REWARD:
            return GIFT
        case TransactionType.MARKETPLACE_SALE:
            return "\U0001F4B0"
        case TransactionType.MARKETPLACE_PURCHASE:
            return "\U0001F6D2"
        case TransactionType.TRADE:
            return "\U0001F501"
        case _:
            return "\U0001F4C4"


def transaction_line(transaction: Transaction) -> str:
    sign = "+" if transaction.amount >= 0 else "-"
    icon = transaction_icon(transaction.transaction_type)
    currency = currency_icon(transaction.currency)
    label = transaction.description or transaction.transaction_type.value.replace("_", " ")
    return f"{icon} `{sign}{abs(transaction.amount):,}` {currency} {label}"


def embed_color(rarity: Rarity) -> discord.Color:
    match rarity:
        case Rarity.LEGENDARY:
            return discord.Color.gold()
        case _:
            return discord.Color.blurple()


def discord_reset_timestamp(day: date) -> int:
    """Epoch seconds for midnight (local time) on the given date."""

    midnight = datetime.combine(day, time.min)
    return int(midnight.timestamp())


def _variant_detail(edition: str, variant: str) -> str:
    parts = [part for part in (edition, variant) if part and part not in {"standard", "base"}]
    if not parts:
        return ""
    return f" · {' / '.join(parts)}"


def format_duration_until(target: datetime) -> str:
    remaining = target - datetime.now(target.tzinfo)
    if remaining <= timedelta():
        return "now"
    seconds = int(remaining.total_seconds())
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return "<1m"


def disable_view_items(view: discord.ui.View) -> None:
    """Disable every interactive item on a view (timeout/end-of-life)."""

    for item in view.children:
        if isinstance(item, discord.ui.Button | discord.ui.Select):
            item.disabled = True
