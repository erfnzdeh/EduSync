import logging
from typing import List
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import jdatetime
from dataclasses import dataclass
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class QueraEvent:
    title: str
    start_time: datetime
    end_time: datetime
    description: str = ""

def extract_assignment_id(url: str) -> str:
    """
    Extract the assignment ID from a Quera assignment URL.
    Example: https://quera.org/course/assignments/85830/problems -> 85830
    """
    match = re.search(r'/assignments/(\d+)/', url)
    if match:
        return match.group(1)
    return None

def convert_persian_date(persian_date: str) -> datetime:
    """
    Convert Persian date string (e.g., '۲۵ اردیبهشت') to datetime object
    using jdatetime library for accurate Jalali to Gregorian conversion.
    """
    logger.info(f"Converting Persian date: {persian_date}")
    
    # Convert Persian numerals to English
    persian_to_english = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
    date_parts = persian_date.translate(persian_to_english).split()
    
    if len(date_parts) != 2:
        raise ValueError(f"Invalid Persian date format: {persian_date}")
    
    # Persian month names mapping
    PERSIAN_MONTHS = {
        'فروردین': 1, 'اردیبهشت': 2, 'خرداد': 3,
        'تیر': 4, 'مرداد': 5, 'شهریور': 6,
        'مهر': 7, 'آبان': 8, 'آذر': 9,
        'دی': 10, 'بهمن': 11, 'اسفند': 12
    }
    
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
    logger.info(f"Converted to Gregorian datetime: {gregorian_date}")
    
    return gregorian_date

class QueraScraper:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        self.cookies = {
            'session_id': session_id
        }

    def get_assignments(self) -> List[QueraEvent]:
        """
        Scrapes events from Quera website and returns a list of QueraEvent objects.
        """
        logger.info("Starting Quera event scraping")
        
        try:
            # Make the request to Quera
            url = 'https://quera.org/course'
            logger.info("Making request to Quera course page...")
            response = requests.get(url, headers=self.headers, cookies=self.cookies)
            response.raise_for_status()
            
            logger.info(f"Response status code: {response.status_code}")
            logger.info(f"Response URL (after any redirects): {response.url}")
            
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
                        logger.info(f"Created event: {event.title}")
                
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

    def validate_session(self) -> bool:
        """
        Validates if the session ID is still valid by making a test request.
        """
        try:
            response = requests.get('https://quera.org/course', 
                                 headers=self.headers, 
                                 cookies=self.cookies)
            return 'login' not in response.url
        except:
            return False 