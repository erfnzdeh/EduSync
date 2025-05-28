import logging
import threading
from health_check import run_health_check_server
from telegram_bot import QueraCalendarBot
import os
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("app.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
# Set httpx logger to WARNING to silence INFO messages
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

def main():
    # Load environment variables
    load_dotenv()
    
    # Start health check server
    try:
        health_check_thread = threading.Thread(target=run_health_check_server)
        health_check_thread.daemon = True
        health_check_thread.start()
        logger.info("Health check server started")
    except Exception as e:
        logger.error(f"Failed to start health check server: {e}")
        raise

    # Initialize and run the bot
    try:
        bot_token = os.getenv("BOT_TOKEN")
        if not bot_token:
            raise ValueError("BOT_TOKEN environment variable is not set")
            
        bot = QueraCalendarBot(bot_token)
        logger.info("Bot initialized, starting...")
        bot.run()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        raise

if __name__ == "__main__":
    main()
