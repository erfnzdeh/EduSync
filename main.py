import logging
import os

from dotenv import load_dotenv

from telegram_bot import QueraCalendarBot

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(
            "app.log", encoding="utf-8"
        ),  # Add encoding for proper handling of Persian text
        logging.StreamHandler(),
    ],
)
# Set httpx logger to WARNING to silence INFO messages
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def main():
    # Load environment variables
    load_dotenv()

    # Get Telegram bot token from environment variables
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("Error: TELEGRAM_BOT_TOKEN not found in environment variables")
        return

    # Run the bot
    bot = QueraCalendarBot(token)
    logger.info("Bot is running...")
    bot.run()


if __name__ == "__main__":
    main()
