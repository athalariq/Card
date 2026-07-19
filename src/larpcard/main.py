from __future__ import annotations

from larpcard.bot.application import LarpCardBot
from larpcard.config import Settings
from larpcard.log_setup import configure_logging


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    token = settings.discord_token.get_secret_value()
    if not token:
        raise RuntimeError("LARPCARD_DISCORD_TOKEN must be configured")
    bot = LarpCardBot(settings)
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
