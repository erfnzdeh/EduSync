import logging
import json
from typing import Dict, Optional
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackContext,
    filters,
    JobQueue
)

from quera import QueraScraper
from gcalendar import GoogleCalendarManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
# Set httpx logger to WARNING to silence INFO messages
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Conversation states
QUERA_SESSION = 0

# File to store user data
USER_DATA_FILE = 'user_data.json'

class QueraCalendarBot:
    def __init__(self, token: str):
        """Initialize the bot with Telegram token."""
        logger.info("Initializing Quera Calendar Bot")
        self.application = Application.builder().token(token).build()
        self.user_data = self._load_user_data()
        logger.info(f"Loaded data for {len(self.user_data)} users")
        
        # Add conversation handler
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', self.start)],
            states={
                QUERA_SESSION: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_quera_session)],
            },
            fallbacks=[CommandHandler('cancel', self.cancel)],
        )
        
        # Add handlers
        self.application.add_handler(conv_handler)
        self.application.add_handler(CommandHandler('sync', self.sync_calendars))
        self.application.add_handler(CommandHandler('help', self.help_command))
        self.application.add_handler(CommandHandler('autosync', self.toggle_autosync))

        # Set up job queue for periodic syncing
        self.job_queue = self.application.job_queue
        logger.info("Bot initialization completed")

    def _load_user_data(self) -> Dict:
        """Load user data from file."""
        try:
            with open(USER_DATA_FILE, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_user_data(self) -> None:
        """Save user data to file."""
        with open(USER_DATA_FILE, 'w') as f:
            json.dump(self.user_data, f)

    async def start(self, update: Update, context: CallbackContext) -> int:
        """Start the conversation and ask for Quera session ID."""
        user_id = str(update.effective_user.id)
        
        if user_id in self.user_data:
            await update.message.reply_text(
                "You're already set up! Use /sync to sync your calendars or /help for more options."
            )
            return ConversationHandler.END
        
        await update.message.reply_text(
            "Welcome! Let's set up your Quera to Google Calendar sync.\n\n"
            "First, I need your Quera session ID. To get this:\n"
            "1. Go to quera.org and log in\n"
            "2. Open browser's developer tools (F12)\n"
            "3. Go to Application/Storage > Cookies\n"
            "4. Find and copy the value of 'session_id'\n\n"
            "Please send me your session ID:"
        )
        # TODO: Add validation for session ID
        return QUERA_SESSION

    async def process_quera_session(self, update: Update, context: CallbackContext) -> int:
        """Process the Quera session ID and complete setup."""
        user_id = str(update.effective_user.id)
        session_id = update.message.text.strip()
        
        logger.info(f"Validating Quera session for user {user_id}")
        
        # Validate session ID
        scraper = QueraScraper(session_id)
        if not scraper.validate_session():
            await update.message.reply_text(
                "❌ Invalid or expired Quera session ID.\n"
                "Please check and try again, or use /cancel to stop."
            )
            return QUERA_SESSION
        
        # Store session ID
        self.user_data[user_id] = {'quera_session_id': session_id}
        self._save_user_data()
        logger.info(f"Stored valid Quera session for user {user_id}")
        
        # Send success message for Quera validation
        await update.message.reply_text(
            "✅ Quera session validated!\n\n"
            "Now, let's set up Google Calendar access.\n"
            "Click the link that will appear in your browser to authorize access to your Google Calendar.\n"
            "After completing the Google authorization, you'll be redirected back to this bot."
        )
        
        # Initialize Google Calendar manager
        calendar_manager = GoogleCalendarManager(user_id)
        
        # Start Google Calendar authentication
        logger.info(f"Starting Google Calendar authentication for user {user_id}")
        if not calendar_manager.authenticate():
            logger.error(f"Google Calendar authentication failed for user {user_id}")
            await update.message.reply_text(
                "❌ Failed to start Google Calendar authentication.\n"
                "Please try /start again."
            )
            return ConversationHandler.END
        
        logger.info(f"Google Calendar authentication successful for user {user_id}")
        await update.message.reply_text(
            "🎉 Setup complete!\n\n"
            "You can now:\n"
            "- Use /sync to manually sync your assignments\n"
            "- Use /autosync to enable automatic syncing every 3 hours\n"
            "- Use /help to see all available commands"
        )
        return ConversationHandler.END

    async def cancel(self, update: Update, context: CallbackContext) -> int:
        """Cancel the conversation."""
        await update.message.reply_text(
            "Setup cancelled. Use /start to try again."
        )
        return ConversationHandler.END

    async def sync_calendars(self, update: Update, context: CallbackContext) -> None:
        """Sync Quera assignments to Google Calendar."""
        user_id = str(update.effective_user.id)
        
        if user_id not in self.user_data:
            await update.message.reply_text(
                "❌ Please set up your accounts first with /start"
            )
            return
        
        # Send initial message and store it
        status_message = await update.message.reply_text("🔄 Starting sync...")
        
        try:
            # Get Quera assignments
            scraper = QueraScraper(self.user_data[user_id]['quera_session_id'])
            events = scraper.get_assignments()
            
            if not events:
                await status_message.delete()
                await update.message.reply_text("No assignments found to sync.")
                return
            
            # Sync to Google Calendar
            calendar_manager = GoogleCalendarManager(user_id)
            if not calendar_manager.authenticate():
                await status_message.delete()
                await update.message.reply_text(
                    "❌ Google Calendar authentication failed. Please set up again with /start"
                )
                return
            
            results = calendar_manager.sync_events(events)
            
            # Delete the status message and send results
            await status_message.delete()
            await update.message.reply_text(
                f"✅ Sync complete!\n\n"
                f"📊 Results:\n"
                f"- {results['created']} new events added\n"
                f"- {results['updated']} events updated\n"
                f"- {results['existing']} events already existed\n"
                f"- {results['failed']} events failed to sync"
            )
            
        except Exception as e:
            logger.error(f"Error during sync for user {user_id}: {e}", exc_info=True)
            await status_message.delete()
            await update.message.reply_text(
                "❌ An error occurred during sync. Please try again later."
            )

    async def toggle_autosync(self, update: Update, context: CallbackContext) -> None:
        """Toggle automatic syncing every 3 hours."""
        user_id = str(update.effective_user.id)
        logger.info(f"User {user_id} toggling auto-sync")
        
        if user_id not in self.user_data:
            logger.warning(f"User {user_id} attempted to toggle auto-sync without setup")
            await update.message.reply_text(
                "❌ Please set up your accounts first with /start"
            )
            return
        
        # Check if autosync is already enabled
        current_jobs = context.job_queue.get_jobs_by_name(f"autosync_{user_id}")
        
        if current_jobs:
            # Disable autosync
            for job in current_jobs:
                job.schedule_removal()
            self.user_data[user_id]['autosync'] = False
            self._save_user_data()
            logger.info(f"Auto-sync disabled for user {user_id}")
            await update.message.reply_text("🔴 Auto-sync has been disabled.")
        else:
            # Enable autosync
            context.job_queue.run_repeating(
                self.periodic_sync,
                interval=10800,  # 3 hours in seconds
                first=10,  # Start first sync after 10 seconds
                name=f"autosync_{user_id}",
                chat_id=update.effective_chat.id,
                user_id=user_id
            )
            self.user_data[user_id]['autosync'] = True
            self._save_user_data()
            logger.info(f"Auto-sync enabled for user {user_id}")
            await update.message.reply_text(
                "🟢 Auto-sync has been enabled!\n"
                "Your calendar will be synced every 3 hours.\n"
                "Use /autosync again to disable it."
            )

    async def periodic_sync(self, context: CallbackContext) -> None:
        """Perform periodic sync for a user."""
        job = context.job
        user_id = job.user_id
        chat_id = job.chat_id
        
        logger.info(f"Starting periodic sync for user {user_id}")
        
        try:
            # Get Quera assignments
            scraper = QueraScraper(self.user_data[user_id]['quera_session_id'])
            events = scraper.get_assignments()
            
            if not events:
                logger.info(f"No new assignments found for user {user_id}")
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="🔄 Auto-sync: No new assignments found."
                )
                return
            
            logger.info(f"Found {len(events)} assignments for user {user_id}")
            
            # Sync to Google Calendar
            calendar_manager = GoogleCalendarManager(user_id)
            if not calendar_manager.authenticate():
                logger.error(f"Google Calendar authentication failed for user {user_id}")
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Auto-sync failed: Google Calendar authentication error.\n"
                         "Please use /start to set up again."
                )
                return
            
            results = calendar_manager.sync_events(events)
            logger.info(f"Sync results for user {user_id}: {results}")
            
            # Only send message if there were changes
            if results['created'] > 0 or results['updated'] > 0:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ Auto-sync complete!\n\n"
                         f"📊 Results:\n"
                         f"- {results['created']} new events added\n"
                         f"- {results['updated']} events updated"
                )
            
        except Exception as e:
            logger.error(f"Error during periodic sync for user {user_id}: {e}", exc_info=True)
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Auto-sync error. Will try again in 3 hours."
            )

    def run(self):
        """Run the bot."""
        logger.info("Starting bot")
        # Restore auto-sync for users who had it enabled
        restored_count = 0
        for user_id, data in self.user_data.items():
            if data.get('autosync', False):
                self.job_queue.run_repeating(
                    self.periodic_sync,
                    interval=10800,  # 3 hours in seconds
                    first=10,  # Start first sync after 10 seconds
                    name=f"autosync_{user_id}",
                    user_id=user_id
                )
                restored_count += 1
        
        logger.info(f"Restored auto-sync for {restored_count} users")
        logger.info("Bot is running...")
        self.application.run_polling()

    async def help_command(self, update: Update, context: CallbackContext) -> None:
        """Show help message."""
        user_id = str(update.effective_user.id)
        logger.info(f"Help command requested by user {user_id}")
        await update.message.reply_text(
            "Available commands:\n\n"
            "/start - Set up your Quera and Google Calendar integration\n"
            "/sync - Manually sync your Quera assignments to Google Calendar\n"
            "/autosync - Toggle automatic syncing every 3 hours\n"
            "/help - Show this help message\n"
            "/cancel - Cancel the current operation"
        ) 