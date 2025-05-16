import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import re
from dateutil import parser
import jdatetime

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Persian month names mapping
PERSIAN_MONTHS = {
    'فروردین': 1, 'اردیبهشت': 2, 'خرداد': 3,
    'تیر': 4, 'مرداد': 5, 'شهریور': 6,
    'مهر': 7, 'آبان': 8, 'آذر': 9,
    'دی': 10, 'بهمن': 11, 'اسفند': 12
}

def convert_persian_date(persian_date: str) -> datetime:
    """
    Convert Persian date string (e.g., '۲۵ اردیبهشت') to datetime object
    using jdatetime library for accurate Jalali to Gregorian conversion.
    """
    logger.debug(f"Converting Persian date: {persian_date}")
    
    # Convert Persian numerals to English
    persian_to_english = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
    date_parts = persian_date.translate(persian_to_english).split()
    
    if len(date_parts) != 2:
        raise ValueError(f"Invalid Persian date format: {persian_date}")
    
    day = int(date_parts[0])
    month = PERSIAN_MONTHS.get(date_parts[1])
    
    if not month:
        raise ValueError(f"Invalid Persian month: {date_parts[1]}")
    
    # Get current Jalali year
    current_jdate = jdatetime.datetime.now()
    year = current_jdate.year
    
    # Create Jalali datetime object
    jd = jdatetime.datetime(year, month, day, 23, 59, 59)
    
    # If the date has already passed, use next year
    if jd < current_jdate:
        jd = jdatetime.datetime(year + 1, month, day, 23, 59, 59)
    
    # Convert to Gregorian datetime
    gregorian_date = jd.togregorian()
    logger.debug(f"Converted to Gregorian datetime: {gregorian_date}")
    
    return gregorian_date

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log', encoding='utf-8'),  # Add encoding for proper handling of Persian text
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

def scrape_quera_events() -> List[QueraEvent]:
    """
    Scrapes events from Quera website and returns a list of QueraEvent objects.
    """
    logger.debug("Starting Quera event scraping")
    
    # Get session ID from environment variables
    session_id = os.getenv('QUERA_SESSION_ID')
    if not session_id:
        logger.error("QUERA_SESSION_ID not found in environment variables")
        return []
    
    # Minimal essential headers
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    # Minimal essential cookies - only session
    cookies = {
        'session_id': session_id
    }
    
    try:
        # Make the request to Quera
        url = 'https://quera.org/course'
        logger.debug("Making request to Quera course page...")
        response = requests.get(url, headers=headers, cookies=cookies)
        response.raise_for_status()
        
        # For debugging - save the response HTML
        with open('debug_section.html', 'w', encoding='utf-8') as f:
            f.write(response.text)
        
        logger.debug(f"Response status code: {response.status_code}")
        logger.debug(f"Response URL (after any redirects): {response.url}")
        
        # Check if we got redirected to login
        if 'login' in response.url:
            logger.error("Got redirected to login page. Authentication failed.")
            return []
        
        # Parse the HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find the deadline section
        deadline_section = soup.find('h2', string='مهلت تمرین‌های پیش رو')
        
        if not deadline_section:
            logger.warning("Could not find deadline section")
            return []
        
        # Find all assignment entries
        quera_events = []
        assignment_divs = soup.find_all('div', class_='css-ardi2f')
        
        for div in assignment_divs:
            try:
                # Get date
                date_span = div.find('span', class_='css-lvorr0')
                month_span = div.find('span', class_='css-itvw0n')
                date_str = f"{date_span.text.strip()} {month_span.text.strip()}" if date_span and month_span else None
                
                # Get assignment title and link
                title_link = div.find('a', class_='css-15qlil8')
                title = title_link.text.strip() if title_link else None
                link = f"https://quera.org{title_link['href']}" if title_link else None
                
                # Get course name
                course_span = div.find('span', class_='css-x4152s')
                course = course_span.text.strip() if course_span else None
                
                if date_str and title and course:
                    # Convert Persian date to datetime
                    end_time = convert_persian_date(date_str)
                    # Set start time to the beginning of the day
                    start_time = end_time.replace(hour=0, minute=0, second=0)
                    
                    # Create description with course name and link
                    description = f"Assignment Link: {link}"
                    
                    # Create QueraEvent object with new title format
                    event = QueraEvent(
                        title=f"{title} | {course}",
                        start_time=start_time,
                        end_time=end_time,
                        description=description
                    )
                    quera_events.append(event)
                    logger.debug(f"Created event: {event.title}")
            
            except Exception as e:
                logger.error(f"Error parsing assignment div: {e}")
                continue
        
        return quera_events
        
    except requests.RequestException as e:
        logger.error(f"Request error: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        logger.exception("Full traceback:")
        return []

def extract_assignment_id(url: str) -> str:
    """
    Extract the assignment ID from a Quera assignment URL.
    Example: https://quera.org/course/assignments/85830/problems -> 85830
    """
    match = re.search(r'/assignments/(\d+)/', url)
    if match:
        return match.group(1)
    return None

def add_event_to_calendar(service, event: QueraEvent) -> bool:
    """
    Adds a single event to Google Calendar as a full-day event or updates if it exists with a different date.
    Returns True if successful (either added or updated), False otherwise.
    """
    logger.debug(f"Checking/Adding event to calendar: {event.title}")
    
    # Extract assignment ID from the URL in the description
    assignment_id = extract_assignment_id(event.description.split("Assignment Link: ")[1])
    if not assignment_id:
        logger.error(f"Could not extract assignment ID from description: {event.description}")
        return False

    # Convert datetime to date string for full-day event
    start_date = event.start_time.date().isoformat()
    # For full-day events, end date should be the next day
    end_date = (event.end_time.date() + timedelta(days=1)).isoformat()
    
    try:
        # Search for events with the same assignment ID in extended properties
        # We search in a wider date range to find the event even if its date has changed
        three_months_ago = (event.start_time - timedelta(days=90)).isoformat() + 'Z'
        three_months_ahead = (event.end_time + timedelta(days=90)).isoformat() + 'Z'
        
        existing_events = service.events().list(
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
                updated_event = service.events().update(
                    calendarId='primary',
                    eventId=existing_event['id'],
                    body=event_body
                ).execute()
                logger.info(f"Updated existing event with new deadline: {event.title}")
                logger.debug(f"Event details: {json.dumps(updated_event, indent=2)}")
                return "updated"
            else:
                logger.info(f"Event already exists with same deadline: {event.title}")
                return "exists"

        # If no existing event found, create new one
        event_result = service.events().insert(calendarId='primary', body=event_body).execute()
        logger.info(f"Successfully added new event: {event.title}")
        logger.debug(f"Event details: {json.dumps(event_result, indent=2)}")
        return "created"
        
    except HttpError as error:
        logger.error(f"Error managing event {event.title}: {error}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error managing event {event.title}: {e}")
        return False

def sync_events_to_calendar(events: List[QueraEvent]) -> None:
    """
    Syncs a list of events to Google Calendar.
    """
    logger.info(f"Starting sync of {len(events)} events to calendar")
    
    try:
        service = get_google_calendar_service()
        
        new_count = 0
        existing_count = 0
        updated_count = 0
        failed_count = 0
        
        for event in events:
            result = add_event_to_calendar(service, event)
            if result == "created":
                new_count += 1
            elif result == "exists":
                existing_count += 1
            elif result == "updated":
                updated_count += 1
            else:
                failed_count += 1
        
        logger.info(f"Sync complete: {new_count} new, {existing_count} existing, {updated_count} updated, {failed_count} failed")
        print(f"\nSync complete:")
        print(f"- {new_count} new events added")
        print(f"- {existing_count} events already existed")
        print(f"- {updated_count} events updated with new deadlines")
        print(f"- {failed_count} events failed to sync")
        
    except Exception as e:
        logger.error(f"Error during calendar sync: {e}")
        print("\nError syncing events to calendar. Check the logs for details.")

def main():
    """
    Main function to run the Quera to Google Calendar sync.
    """
    try:
        # Load environment variables
        load_dotenv()
        
        # Scrape events from Quera
        print("Fetching assignments from Quera...")
        events = scrape_quera_events()
        
        if not events:
            print("No assignments found to sync.")
            return
        
        # Print found assignments
        print(f"\nFound {len(events)} assignments:")
        for event in events:
            print(f"\nTitle: {event.title}")
            print(f"Start: {event.start_time}")
            print(f"End: {event.end_time}")
            print(f"Description: {event.description}")
        
        # Sync to calendar
        print("\nSyncing assignments to Google Calendar...")
        sync_events_to_calendar(events)
        
    except Exception as e:
        logger.error(f"Error in main function: {e}")
        logger.exception("Full traceback:")
        print(f"\nError: {e}")
        print("Check the logs for more details.")

if __name__ == "__main__":
    main() 