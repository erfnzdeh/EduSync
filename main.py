import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar']

class QueraEvent:
    def __init__(self, title: str, start_time: datetime, end_time: datetime, description: Optional[str] = None):
        self.title = title
        self.start_time = start_time
        self.end_time = end_time
        self.description = description or ""

def get_google_calendar_service():
    """
    Authenticate and create Google Calendar service.
    Returns the Calendar API service object.
    """
    logger.debug("Starting Google Calendar authentication process")
    creds = None
    
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first time.
    if os.path.exists('token.json'):
        logger.debug("Found existing token.json")
        try:
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
            logger.debug("Successfully loaded credentials from token.json")
        except Exception as e:
            logger.error(f"Error loading credentials from token.json: {e}")
    
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        logger.debug("No valid credentials found, starting new authentication flow")
        if creds and creds.expired and creds.refresh_token:
            logger.debug("Refreshing expired credentials")
            try:
                creds.refresh(Request())
                logger.debug("Successfully refreshed credentials")
            except Exception as e:
                logger.error(f"Error refreshing credentials: {e}")
        else:
            logger.debug("Starting new OAuth2 flow")
            try:
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
                logger.debug("Successfully completed OAuth2 flow")
            except Exception as e:
                logger.error(f"Error in OAuth2 flow: {e}")
                raise

        # Save the credentials for the next run
        try:
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
            logger.debug("Successfully saved new credentials to token.json")
        except Exception as e:
            logger.error(f"Error saving credentials to token.json: {e}")

    try:
        service = build('calendar', 'v3', credentials=creds)
        logger.debug("Successfully built Google Calendar service")
        return service
    except Exception as e:
        logger.error(f"Error building Google Calendar service: {e}")
        raise

# TODO: Implement the actual scraping of events from the Quera website
def scrape_quera_events() -> List[QueraEvent]:
    """
    Scrapes events from Quera website.
    Returns a list of QueraEvent objects.
    """
    logger.debug("Starting Quera event scraping")
    
    # Create a mock event for tomorrow night
    tomorrow = datetime.now() + timedelta(days=1)
    start_time = tomorrow.replace(hour=20, minute=0, second=0, microsecond=0)  # 8:00 PM tomorrow
    end_time = tomorrow.replace(hour=22, minute=0, second=0, microsecond=0)    # 10:00 PM tomorrow
    
    mock_event = QueraEvent(
        title="Test Quera Event",
        start_time=start_time,
        end_time=end_time,
        description="This is a test event for the Quera Calendar integration"
    )
    
    logger.debug(f"Created mock event: {mock_event.title} from {mock_event.start_time} to {mock_event.end_time}")
    return [mock_event]

def add_event_to_calendar(service, event: QueraEvent) -> bool:
    """
    Adds a single event to Google Calendar.
    Returns True if successful, False otherwise.
    """
    logger.debug(f"Adding event to calendar: {event.title}")
    
    event_body = {
        'summary': event.title,
        'description': event.description,
        'start': {
            'dateTime': event.start_time.isoformat(),
            'timeZone': 'Asia/Tehran',
        },
        'end': {
            'dateTime': event.end_time.isoformat(),
            'timeZone': 'Asia/Tehran',
        },
    }

    try:
        event_result = service.events().insert(calendarId='primary', body=event_body).execute()
        logger.info(f"Successfully added event: {event.title}")
        logger.debug(f"Event details: {json.dumps(event_result, indent=2)}")
        return True
    except HttpError as error:
        logger.error(f"Error adding event {event.title}: {error}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error adding event {event.title}: {e}")
        return False

def sync_events_to_calendar(events: List[QueraEvent]) -> None:
    """
    Syncs all scraped events to Google Calendar.
    """
    logger.info(f"Starting sync of {len(events)} events to Google Calendar")
    
    try:
        service = get_google_calendar_service()
        
        successful_syncs = 0
        failed_syncs = 0
        
        for event in events:
            logger.debug(f"Processing event: {event.title}")
            if add_event_to_calendar(service, event):
                successful_syncs += 1
            else:
                failed_syncs += 1
        
        logger.info(f"Sync completed. Successfully added {successful_syncs} events, failed to add {failed_syncs} events")
    except Exception as e:
        logger.error(f"Error during event sync: {e}")
        raise

def main():
    """
    Main function to orchestrate the event sync process.
    """
    logger.info("Starting Quera to Google Calendar sync")
    
    try:
        # Load environment variables
        load_dotenv()
        logger.debug("Loaded environment variables")
        
        # Scrape events
        events = scrape_quera_events()
        if not events:
            logger.warning("No events found to sync")
            return
        
        # Sync events to calendar
        sync_events_to_calendar(events)
        
        logger.info("Sync process completed successfully")
    except Exception as e:
        logger.error(f"Error in main process: {e}")
        raise

if __name__ == "__main__":
    main() 