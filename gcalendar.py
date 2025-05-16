import os
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict
import json
import webbrowser
import socket
import random
import string
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from dotenv import load_dotenv
import requests

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from quera import QueraEvent, extract_assignment_id

# Load environment variables
load_dotenv()

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

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar']

class GoogleCalendarManager:
    def __init__(self, user_id: str, tokens_file: str = 'user_tokens.json'):
        """
        Initialize the calendar manager for a specific user.
        user_id: Unique identifier for the user (e.g., Telegram user ID)
        tokens_file: JSON file storing all users' tokens
        """
        self.user_id = str(user_id)
        self.tokens_file = tokens_file
        self.credentials = self._load_credentials()
        self.service = None if not self.credentials else self._build_service()
        self.bot_username = os.getenv('BOT_USERNAME')
        if not self.bot_username:
            logger.warning("BOT_USERNAME not found in environment variables")
        
        # Load client configuration
        try:
            with open('credentials.json', 'r') as f:
                self.client_config = json.load(f)
                self.client_id = self.client_config['installed']['client_id']
                self.client_secret = self.client_config['installed']['client_secret']
        except Exception as e:
            logger.error(f"Error loading client configuration: {e}")
            self.client_config = None
            self.client_id = None
            self.client_secret = None

        # OAuth state
        self.auth_url = None
        self.auth_code = None
        self.flow = None

    def _load_credentials(self) -> Optional[Credentials]:
        """Load credentials for the specific user from the tokens file."""
        try:
            if os.path.exists(self.tokens_file):
                with open(self.tokens_file, 'r') as f:
                    all_tokens = json.load(f)
                    if self.user_id in all_tokens:
                        creds = Credentials.from_authorized_user_info(all_tokens[self.user_id], SCOPES)
                        if creds and creds.expired and creds.refresh_token:
                            creds.refresh(Request())
                            self._save_credentials(creds)
                        return creds
        except Exception as e:
            logger.error(f"Error loading credentials: {e}")
        return None

    def _save_credentials(self, creds: Credentials) -> None:
        """Save credentials for the specific user to the tokens file."""
        try:
            all_tokens = {}
            if os.path.exists(self.tokens_file):
                with open(self.tokens_file, 'r') as f:
                    all_tokens = json.load(f)
            
            all_tokens[self.user_id] = json.loads(creds.to_json())
            
            with open(self.tokens_file, 'w') as f:
                json.dump(all_tokens, f)
        except Exception as e:
            logger.error(f"Error saving credentials: {e}")

    def _build_service(self):
        """Build and return the Google Calendar service."""
        try:
            return build('calendar', 'v3', credentials=self.credentials)
        except Exception as e:
            logger.error(f"Error building service: {e}")
            return None

    def start_authentication(self) -> Dict[str, str]:
        """
        Start the OAuth2 flow and return the authorization URL.
        Returns a dictionary with the authorization URL.
        """
        try:
            # Create a unique state value for security
            state = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(30))
            
            # Create the flow
            self.flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json',
                SCOPES,
                redirect_uri='urn:ietf:wg:oauth:2.0:oob'  # Use out-of-band redirect URI
            )
            
            # Generate the authorization URL
            auth_url = self.flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true',
                state=state
            )[0]
            
            self.auth_url = auth_url
            
            return {
                'auth_url': auth_url
            }
        except Exception as e:
            logger.error(f"Error starting authentication: {e}")
            return None

    def complete_authentication(self, code: str) -> bool:
        """
        Complete the OAuth2 flow using the authorization code.
        Returns True if authentication was successful.
        """
        try:
            if not self.flow:
                logger.error("Authentication flow not started")
                return False

            try:
                # Exchange the code for credentials
                self.flow.fetch_token(code=code)
                self.credentials = self.flow.credentials
                self._save_credentials(self.credentials)
                self.service = self._build_service()
                self.flow = None  # Clear the flow
                return True
            except Exception as e:
                logger.error(f"Error fetching token: {e}")
                return False

        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False

    def add_event(self, event: QueraEvent) -> str:
        """
        Adds a single event to Google Calendar or updates if it exists with a different date.
        Returns: 'created', 'updated', 'exists', or False if failed
        """
        if not self.service:
            logger.error("Calendar service not initialized")
            return False

        logger.info(f"Checking/Adding event to calendar: {event.title}")
        
        try:
            # Extract assignment ID from the URL in the description
            assignment_link = event.description.split("Assignment Link: ")[1]
            logger.info(f"Extracted assignment link: {assignment_link}")
            
            assignment_id = extract_assignment_id(assignment_link)
            if not assignment_id:
                logger.error(f"Could not extract assignment ID from description: {event.description}")
                return False

            # Convert datetime to date string for full-day event
            start_date = event.start_time.date().isoformat()
            # For full-day events, end date should be the next day
            end_date = (event.end_time.date() + timedelta(days=1)).isoformat()
            
            try:
                # Search for events with the same assignment ID in extended properties
                three_months_ago = (event.start_time - timedelta(days=90)).isoformat() + 'Z'
                three_months_ahead = (event.end_time + timedelta(days=90)).isoformat() + 'Z'
                
                existing_events = self.service.events().list(
                    calendarId='primary',
                    timeMin=three_months_ago,
                    timeMax=three_months_ahead,
                    privateExtendedProperty=f'queraAssignmentId={assignment_id}'
                ).execute()

                event_body = {
                    'summary': event.title,
                    'description': event.description,
                    'start': {
                        'date': start_date,
                        'timeZone': 'Asia/Tehran',
                    },
                    'end': {
                        'date': end_date,
                        'timeZone': 'Asia/Tehran',
                    },
                    'extendedProperties': {
                        'private': {
                            'queraAssignmentId': assignment_id,
                            'source': 'quera-automation'
                        }
                    }
                }

                for existing_event in existing_events.get('items', []):
                    # Check if dates are different
                    existing_start = existing_event['start'].get('date')
                    if existing_start != start_date:
                        # Update the event with new dates
                        self.service.events().update(
                            calendarId='primary',
                            eventId=existing_event['id'],
                            body=event_body
                        ).execute()
                        logger.info(f"Updated existing event with new deadline: {event.title}")
                        return "updated"
                    else:
                        logger.info(f"Event already exists with same deadline: {event.title}")
                        return "exists"

                # If no existing event found, create new one
                self.service.events().insert(calendarId='primary', body=event_body).execute()
                logger.info(f"Successfully added new event: {event.title}")
                return "created"
                
            except HttpError as error:
                logger.error(f"Error managing event {event.title}: {error}")
                return False
                
        except Exception as e:
            logger.error(f"Unexpected error managing event {event.title}: {e}", exc_info=True)
            return False

    def sync_events(self, events: List[QueraEvent]) -> dict:
        """
        Syncs a list of events to Google Calendar.
        Returns a dictionary with counts of created, updated, existing, and failed events.
        """
        results = {
            'created': 0,
            'updated': 0,
            'existing': 0,
            'failed': 0
        }
        
        if not self.service:
            logger.error("Calendar service not initialized")
            return results

        logger.info(f"Starting sync of {len(events)} events to calendar")
        
        for event in events:
            result = self.add_event(event)
            if result == "created":
                results['created'] += 1
            elif result == "updated":
                results['updated'] += 1
            elif result == "exists":
                results['existing'] += 1
            else:
                results['failed'] += 1
        
        logger.info(f"Sync complete: {results}")
        return results

    def authenticate(self) -> bool:
        """
        Check if authenticated and refresh token if needed.
        Returns True if authenticated, False otherwise.
        """
        if self.credentials:
            if self.credentials.expired and self.credentials.refresh_token:
                try:
                    self.credentials.refresh(Request())
                    self._save_credentials(self.credentials)
                    self.service = self._build_service()
                    return True
                except Exception as e:
                    logger.error(f"Error refreshing token: {e}")
                    return False
            return True
        return False 