import json
import logging
from typing import Dict, Optional
import threading

from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackContext,
    CommandHandler,
    ConversationHandler,
    JobQueue,
    MessageHandler,
    filters,
)

from gcalendar import GoogleCalendarManager
from quera import QueraScraper
from health_check import run_health_check_server

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

# Conversation states
MAIN_MENU = 0
QUERA_SESSION = 1
GOOGLE_AUTH_CODE = 2
SYNC_MENU = 3  # New state for sync submenu

# Command constants
CONNECT_GCAL = "🔗 Connect Calendar"
DISCONNECT_GCAL = "🔌 Disconnect Calendar"
CONNECT_QUERA = "🔗 Connect Quera"
DISCONNECT_QUERA = "🔌 Disconnect Quera"
SYNC_OPTIONS = "⚙️ Sync Options"
SYNC_NOW = "🔄 Sync Now"
TOGGLE_AUTO_SYNC = "⏱️ Toggle Auto Sync"
BACK_TO_MAIN = "↩️ Back to Main Menu"
CW_SYNC = "CW Sync"
DELETE_ACCOUNT = "Delete Account"
CONTACT_US = "Contact Us"

# File to store user data
USER_DATA_FILE = "user_data.json"


class QueraCalendarBot:
    def __init__(self, token: str):
        """Initialize the bot with Telegram token."""
        logger.info("Initializing Quera Calendar Bot")
        
        # Configure application with explicit settings
        self.application = (
            Application.builder()
            .token(token)
            .concurrent_updates(True)
            .arbitrary_callback_data(True)
            .post_init(self._post_init)
            .build()
        )
        
        self.user_data = self._load_user_data()
        logger.info(f"Loaded data for {len(self.user_data)} users")

    async def _post_init(self, application: Application) -> None:
        """Post initialization hook."""
        logger.info("Post initialization completed")

        # Add conversation handler
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start)],
            states={
                MAIN_MENU: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, self.handle_menu_selection
                    )
                ],
                QUERA_SESSION: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, self.process_quera_session
                    )
                ],
                GOOGLE_AUTH_CODE: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, self.process_google_auth_code
                    )
                ],
                SYNC_MENU: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, self.handle_sync_menu_selection
                    )
                ],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
        )

        # Add handlers
        self.application.add_handler(conv_handler)
        self.application.add_handler(CommandHandler("sync", self.sync_calendars))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("autosync", self.toggle_autosync))

        # Set up job queue for periodic syncing
        self.job_queue = self.application.job_queue
        logger.info("Bot initialization completed")

    def _load_user_data(self) -> Dict:
        """Load user data from file."""
        try:
            with open(USER_DATA_FILE, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_user_data(self) -> None:
        """Save user data to file."""
        with open(USER_DATA_FILE, "w") as f:
            json.dump(self.user_data, f)

    async def start(self, update: Update, context: CallbackContext) -> int:
        """Start the conversation and show the main menu."""
        user_id = str(update.effective_user.id)

        welcome_message = (
            "👋 Welcome to Quera Calendar Bot!\n\n"
            "This bot helps you sync your Quera/CW assignments with Google Calendar.\n\n"
            "Please select an option from the menu below:"
        )

        await update.message.reply_text(
            welcome_message, reply_markup=self.get_main_keyboard(user_id)
        )

        return MAIN_MENU

    async def handle_menu_selection(
        self, update: Update, context: CallbackContext
    ) -> int:
        """Handle menu button selections."""
        user_id = str(update.effective_user.id)
        selection = update.message.text
        user_data = self.user_data.get(user_id, {})

        if selection == SYNC_OPTIONS:
            if not user_data.get("quera_session_id") or not user_data.get(
                "gcal_connected", False
            ):
                await update.message.reply_text(
                    "❌ Please make sure both Quera and Google Calendar are connected.",
                    reply_markup=self.get_main_keyboard(user_id),
                )
                return MAIN_MENU

            await update.message.reply_text(
                "Select a sync option:",
                reply_markup=self.get_sync_menu_keyboard(user_id),
            )
            return SYNC_MENU

        elif selection in [CONNECT_GCAL, DISCONNECT_GCAL]:
            if selection == CONNECT_GCAL:
                if user_data.get("gcal_connected", False):
                    await update.message.reply_text(
                        "✅ Google Calendar is already connected!\n"
                        "You can sync your assignments when Quera is connected.",
                        reply_markup=self.get_main_keyboard(user_id),
                    )
                    return MAIN_MENU

                # Initialize Google Calendar manager and start authentication
                calendar_manager = GoogleCalendarManager(user_id)
                auth_info = calendar_manager.start_authentication()

                if not auth_info:
                    await update.message.reply_text(
                        "❌ Failed to start Google Calendar authentication.\n"
                        "Please try again later.",
                        reply_markup=self.get_main_keyboard(user_id),
                    )
                    return MAIN_MENU

                # Store calendar manager in context for later
                context.user_data["calendar_manager"] = calendar_manager

                # Send authentication instructions
                await update.message.reply_text(
                    "To connect Google Calendar:\n"
                    f"1. Visit this URL: {auth_info['auth_url']}\n"
                    f"2. Sign in with your Google account and authorize the app\n"
                    f"3. You'll receive a code - copy it and send it to me\n\n"
                    "I'm waiting for the code..."
                )
                return GOOGLE_AUTH_CODE
            else:  # DISCONNECT_GCAL
                if not user_data.get("gcal_connected", False):
                    await update.message.reply_text(
                        "❌ Google Calendar is not connected.",
                        reply_markup=self.get_main_keyboard(user_id),
                    )
                    return MAIN_MENU

                # Remove Google Calendar connection
                user_data["gcal_connected"] = False
                self._save_user_data()

                await update.message.reply_text(
                    "✅ Google Calendar has been disconnected.\n"
                    "You can reconnect anytime using '🔗 Connect Calendar'.",
                    reply_markup=self.get_main_keyboard(user_id),
                )
                return MAIN_MENU

        elif selection in [CONNECT_QUERA, DISCONNECT_QUERA]:
            if selection == CONNECT_QUERA:
                if user_data.get("quera_session_id"):
                    await update.message.reply_text(
                        "✅ Quera is already connected!\n"
                        "You can sync your assignments when Google Calendar is connected.",
                        reply_markup=self.get_main_keyboard(user_id),
                    )
                    return MAIN_MENU

                await update.message.reply_text(
                    "Let's connect your Quera account.\n\n"
                    "I need your Quera session ID. To get this:\n"
                    "1. Go to quera.org and log in\n"
                    "2. Open browser's developer tools (F12)\n"
                    "3. Go to Application/Storage > Cookies\n"
                    "4. Find and copy the value of 'session_id'\n\n"
                    "Please send me your session ID:"
                )
                return QUERA_SESSION
            else:  # DISCONNECT_QUERA
                if not user_data.get("quera_session_id"):
                    await update.message.reply_text(
                        "❌ Quera is not connected.",
                        reply_markup=self.get_main_keyboard(user_id),
                    )
                    return MAIN_MENU

                # Remove Quera session
                del user_data["quera_session_id"]
                self._save_user_data()

                await update.message.reply_text(
                    "✅ Quera account has been disconnected.\n"
                    "You can reconnect anytime using '🔗 Connect Quera'.",
                    reply_markup=self.get_main_keyboard(user_id),
                )
                return MAIN_MENU

        elif selection == CW_SYNC:
            await update.message.reply_text(
                "🚧 CW Sync feature is coming soon!",
                reply_markup=self.get_main_keyboard(user_id),
            )
            return MAIN_MENU

        elif selection == DELETE_ACCOUNT:
            if not user_data:
                await update.message.reply_text(
                    "You don't have any accounts connected yet.",
                    reply_markup=self.get_main_keyboard(user_id),
                )
                return MAIN_MENU

            # Delete user data
            del self.user_data[user_id]
            self._save_user_data()

            await update.message.reply_text(
                "✅ Your account has been deleted.\n"
                "You can set up again anytime using the available options.",
                reply_markup=self.get_main_keyboard(user_id),
            )
            return MAIN_MENU

        elif selection == CONTACT_US:
            await update.message.reply_text(
                "📧 For support or feedback:\n"
                "1. Visit our GitHub repository: https://github.com/erfnzdeh/EduSync\n"
                "2. Open an issue for bug reports or feature requests\n"
                "3. Or contact me directly at: t.me/Pouri2048",
                reply_markup=self.get_main_keyboard(user_id),
            )
            return MAIN_MENU

        else:
            await update.message.reply_text(
                "Please select an option from the menu buttons.",
                reply_markup=self.get_main_keyboard(user_id),
            )
            return MAIN_MENU

    async def process_google_auth_code(
        self, update: Update, context: CallbackContext
    ) -> int:
        """Process the Google authorization code."""
        user_id = str(update.effective_user.id)
        auth_code = update.message.text.strip()

        # Get calendar manager from context
        calendar_manager = context.user_data.get("calendar_manager")
        if not calendar_manager:
            await update.message.reply_text(
                "❌ Authentication session expired.\n" "Please try connecting again.",
                reply_markup=self.get_main_keyboard(user_id),
            )
            return MAIN_MENU

        # Complete authentication with the provided code
        status_message = await update.message.reply_text(
            "🔄 Verifying authentication code..."
        )

        if calendar_manager.complete_authentication(auth_code):
            logger.info(f"Google Calendar authentication successful for user {user_id}")

            # Initialize user data if not exists
            if user_id not in self.user_data:
                self.user_data[user_id] = {}

            # Mark Google Calendar as connected
            self.user_data[user_id]["gcal_connected"] = True
            self._save_user_data()

            await status_message.edit_text(
                "🎉 Google Calendar connected successfully!\n\n"
                "Next steps:\n"
                "• Connect your Quera account using 'Quera Sync'\n"
                "• Once both are connected, you can sync your assignments\n"
                "• Enable auto-sync with /autosync\n"
                "• View all commands with /help",
                reply_markup=self.get_main_keyboard(user_id),
            )
        else:
            logger.error(f"Google Calendar authentication failed for user {user_id}")
            await status_message.edit_text(
                "❌ Failed to complete Google Calendar authentication.\n"
                "The code might be invalid or expired. Please try connecting again.",
                reply_markup=self.get_main_keyboard(user_id),
            )

        # Clean up context
        if "calendar_manager" in context.user_data:
            del context.user_data["calendar_manager"]

        return MAIN_MENU

    async def process_quera_session(
        self, update: Update, context: CallbackContext
    ) -> int:
        """Process the Quera session ID."""
        user_id = str(update.effective_user.id)
        session_id = update.message.text.strip()

        logger.info(f"Validating Quera session for user {user_id}")

        # Validate session ID
        scraper = QueraScraper(session_id)
        if not scraper.validate_session():
            await update.message.reply_text(
                "❌ Invalid or expired Quera session ID.\n"
                "Please check and try again, or select a different option.",
                reply_markup=self.get_main_keyboard(user_id),
            )
            return MAIN_MENU

        # Initialize user data if not exists
        if user_id not in self.user_data:
            self.user_data[user_id] = {}

        # Store session ID
        self.user_data[user_id]["quera_session_id"] = session_id
        self._save_user_data()
        logger.info(f"Stored valid Quera session for user {user_id}")

        # Check if Google Calendar is connected
        if not self.user_data[user_id].get("gcal_connected", False):
            await update.message.reply_text(
                "✅ Quera account connected successfully!\n\n"
                "To start syncing your assignments, please connect to Google Calendar first.",
                reply_markup=self.get_main_keyboard(user_id),
            )
        else:
            await update.message.reply_text(
                "✅ Quera account connected successfully!\n\n"
                "You're all set! You can now:\n"
                "• Use 'Quera Sync' to sync your assignments\n"
                "• Enable auto-sync with /autosync\n"
                "• View all commands with /help",
                reply_markup=self.get_main_keyboard(user_id),
            )

        return MAIN_MENU

    async def cancel(self, update: Update, context: CallbackContext) -> int:
        """Cancel the conversation."""
        # Clean up any pending authentication
        if "calendar_manager" in context.user_data:
            del context.user_data["calendar_manager"]

        await update.message.reply_text("Setup cancelled. Use /start to try again.")
        return ConversationHandler.END

    async def sync_calendars(self, update: Update, context: CallbackContext) -> None:
        """Sync Quera assignments to Google Calendar."""
        user_id = str(update.effective_user.id)
        user_data = self.user_data.get(user_id, {})

        # Check if both services are connected
        if not user_data.get("quera_session_id"):
            await update.message.reply_text(
                "❌ Please connect your Quera account first.",
                reply_markup=self.get_main_keyboard(user_id),
            )
            return

        if not user_data.get("gcal_connected", False):
            await update.message.reply_text(
                "❌ Please connect to Google Calendar first.",
                reply_markup=self.get_main_keyboard(user_id),
            )
            return

        # Send initial message and store it
        status_message = await update.message.reply_text(
            "🔄 Starting sync...\n" "This may take a few moments."
        )

        try:
            # Get Quera assignments
            scraper = QueraScraper(user_data["quera_session_id"])
            events = scraper.get_assignments()

            if not events:
                await status_message.edit_text(
                    "ℹ️ No new assignments found to sync.",
                    reply_markup=self.get_main_keyboard(user_id),
                )
                return

            # Sync to Google Calendar
            calendar_manager = GoogleCalendarManager(user_id)
            if not calendar_manager.authenticate():
                await status_message.edit_text(
                    "❌ Google Calendar authentication expired.\n"
                    "Please reconnect using the 'Connect to Google Calendar' option.",
                    reply_markup=self.get_main_keyboard(user_id),
                )
                # Reset Google Calendar connection status
                user_data["gcal_connected"] = False
                self._save_user_data()
                return

            results = calendar_manager.sync_events(events)

            # Format the results message
            success_count = (
                results["created"] + results["updated"] + results["existing"]
            )
            total_count = success_count + results["failed"]

            status_emoji = "✅" if results["failed"] == 0 else "⚠️"

            await status_message.edit_text(
                f"{status_emoji} Sync completed!\n\n"
                f"📊 Summary:\n"
                f"• {results['created']} new assignments added\n"
                f"• {results['updated']} assignments updated\n"
                f"• {results['existing']} already synced\n"
                f"• {results['failed']} failed to sync\n\n"
                f"Total: {success_count}/{total_count} assignments synced successfully.",
                reply_markup=self.get_main_keyboard(user_id),
            )

        except Exception as e:
            logger.error(f"Error during sync for user {user_id}: {e}", exc_info=True)
            await status_message.edit_text(
                "❌ An error occurred during sync.\n"
                "Please try again later or reconnect your accounts if the problem persists.",
                reply_markup=self.get_main_keyboard(user_id),
            )

    async def toggle_autosync(self, update: Update, context: CallbackContext) -> None:
        """Toggle automatic syncing every 3 hours."""
        user_id = str(update.effective_user.id)
        logger.info(f"User {user_id} toggling auto-sync")

        if user_id not in self.user_data:
            logger.warning(
                f"User {user_id} attempted to toggle auto-sync without setup"
            )
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
            self.user_data[user_id]["autosync"] = False
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
                user_id=user_id,
            )
            self.user_data[user_id]["autosync"] = True
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
            scraper = QueraScraper(self.user_data[user_id]["quera_session_id"])
            events = scraper.get_assignments()

            if not events:
                logger.info(f"No new assignments found for user {user_id}")
                await context.bot.send_message(
                    chat_id=chat_id, text="🔄 Auto-sync: No new assignments found."
                )
                return

            logger.info(f"Found {len(events)} assignments for user {user_id}")

            # Sync to Google Calendar
            calendar_manager = GoogleCalendarManager(user_id)
            if not calendar_manager.authenticate():
                logger.error(
                    f"Google Calendar authentication failed for user {user_id}"
                )
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Auto-sync failed: Google Calendar authentication error.\n"
                    "Please use /start to set up again.",
                )
                return

            results = calendar_manager.sync_events(events)
            logger.info(f"Sync results for user {user_id}: {results}")

            # Only send message if there were changes
            if results["created"] > 0 or results["updated"] > 0:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ Auto-sync complete!\n\n"
                    f"📊 Results:\n"
                    f"- {results['created']} new events added\n"
                    f"- {results['updated']} events updated",
                )

        except Exception as e:
            logger.error(
                f"Error during periodic sync for user {user_id}: {e}", exc_info=True
            )
            await context.bot.send_message(
                chat_id=chat_id, text="❌ Auto-sync error. Will try again in 3 hours."
            )

    def run(self):
        """Run the bot."""
        logger.info("Starting bot")
        
        # Restore auto-sync for users who had it enabled
        restored_count = 0
        for user_id, data in self.user_data.items():
            if data.get("autosync", False):
                self.job_queue.run_repeating(
                    self.periodic_sync,
                    interval=10800,  # 3 hours in seconds
                    first=10,  # Start first sync after 10 seconds
                    name=f"autosync_{user_id}",
                    user_id=user_id,
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

    def get_main_keyboard(self, user_id: str = None) -> ReplyKeyboardMarkup:
        """Create the main menu keyboard with dynamic states based on user status."""
        user_data = self.user_data.get(user_id, {})
        has_gcal = user_data.get("gcal_connected", False)
        has_quera = user_data.get("quera_session_id") is not None

        keyboard = []

        # First row: Google Calendar connection
        keyboard.append([KeyboardButton(DISCONNECT_GCAL if has_gcal else CONNECT_GCAL)])

        # Second row: Quera and CW sync
        quera_buttons = [
            KeyboardButton(DISCONNECT_QUERA if has_quera else CONNECT_QUERA)
        ]

        # Add sync options if both services are connected
        if has_gcal and has_quera:
            quera_buttons.append(KeyboardButton(SYNC_OPTIONS))
        else:
            quera_buttons.append(KeyboardButton(CW_SYNC))

        keyboard.append(quera_buttons)

        # Third row: Account management
        keyboard.append([KeyboardButton(DELETE_ACCOUNT), KeyboardButton(CONTACT_US)])

        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    def get_sync_menu_keyboard(self, user_id: str = None) -> ReplyKeyboardMarkup:
        """Create the sync menu keyboard."""
        user_data = self.user_data.get(user_id, {})
        is_autosync = user_data.get("autosync", False)

        keyboard = [
            [
                KeyboardButton(SYNC_NOW),
                KeyboardButton(f"{TOGGLE_AUTO_SYNC} {'✅' if is_autosync else '❌'}"),
            ],
            [KeyboardButton(BACK_TO_MAIN)],
        ]

        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    async def handle_sync_menu_selection(
        self, update: Update, context: CallbackContext
    ) -> int:
        """Handle sync menu selections."""
        user_id = str(update.effective_user.id)
        selection = update.message.text.replace(" ✅", "").replace(
            " ❌", ""
        )  # Remove status indicators
        user_data = self.user_data.get(user_id, {})

        if selection == BACK_TO_MAIN:
            await update.message.reply_text(
                "Back to main menu.", reply_markup=self.get_main_keyboard(user_id)
            )
            return MAIN_MENU

        elif selection == SYNC_NOW:
            await self.sync_calendars(update, context)
            # Stay in sync menu after syncing
            await update.message.reply_text(
                "Select a sync option:",
                reply_markup=self.get_sync_menu_keyboard(user_id),
            )
            return SYNC_MENU

        elif selection == TOGGLE_AUTO_SYNC:
            # Get current jobs for this user
            current_jobs = context.job_queue.get_jobs_by_name(f"autosync_{user_id}")
            is_autosync = bool(current_jobs)

            if is_autosync:
                # Disable autosync
                for job in current_jobs:
                    job.schedule_removal()
                user_data["autosync"] = False
                self._save_user_data()
                await update.message.reply_text(
                    "🔴 Auto-sync has been disabled.",
                    reply_markup=self.get_sync_menu_keyboard(user_id),
                )
            else:
                # Enable autosync
                context.job_queue.run_repeating(
                    self.periodic_sync,
                    interval=10800,  # 3 hours in seconds
                    first=10,  # Start first sync after 10 seconds
                    name=f"autosync_{user_id}",
                    chat_id=update.effective_chat.id,
                    user_id=user_id,
                )
                user_data["autosync"] = True
                self._save_user_data()
                await update.message.reply_text(
                    "🟢 Auto-sync has been enabled!\n"
                    "Your calendar will be synced every 3 hours.",
                    reply_markup=self.get_sync_menu_keyboard(user_id),
                )
            return SYNC_MENU

        else:
            await update.message.reply_text(
                "Please select an option from the menu buttons.",
                reply_markup=self.get_sync_menu_keyboard(user_id),
            )
            return SYNC_MENU
