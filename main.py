import os
import logging
import threading
from flask import Flask
from dotenv import load_dotenv
from telegram_bot import QueraCalendarBot

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log', encoding='utf-8'),  # Add encoding for proper handling of Persian text
        logging.StreamHandler()
    ]
)
# Set httpx logger to WARNING to silence INFO messages
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)

@app.route('/health')
def health_check():
    return 'OK', 200

def run_bot(token):
    bot = QueraCalendarBot(token)
    print("Bot is running...")
    bot.run()

def main():
    # Load environment variables
    load_dotenv()
    
    # Get Telegram bot token from environment variables
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN not found in environment variables")
        return
    
    # Start the bot in a separate thread
    bot_thread = threading.Thread(target=run_bot, args=(token,))
    bot_thread.daemon = True
    bot_thread.start()
    
    # Run Flask app
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    main() 