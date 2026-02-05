import json
import time
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import firebase_functions.https_fn as https_fn
import firebase_functions.scheduler_fn as scheduler_fn
# from firebase_admin import initialize_app, firestore
from firebase_functions import https_fn
from firebase_admin import initialize_app
from router.health import health_check
from db import db
from router.movies import get_popular_movies
from router.movies import get_all_movies
from router.movies import get_movie_year

# Initialize Firebase Admin SDK

# --- creating the api to trigger the scrapping code



@https_fn.on_request()
def api(req):
    path = req.path
    method = req.method

    if path == "/health_check" and method == "GET":
        return health_check()
    
    if path == "movies/get_all" and method == "GET":
        return get_all_movies()
    
    if path == '/trigger/get_popular_movies' and method == 'GET':
        return get_popular_movies()
    
    if path == '/trigger/get_movie_year' and method == 'GET':
        return get_movie_year()

    # if path == "/api/movies" and method == "GET":
    #     return get_all_movies()

    # if path == "/api/movies/similar" and method == "GET":
    #     return get_similar_movies(req)

    return ("Route not found", 404)

@https_fn.on_request()
def trigger_imdb_scraper_api(req):
    data = req.get_json(silent=True)

    if not data or "movieId" not in data:
        return ("movieId required", 400)

    movie_id = data["movieId"]

    # later you will call scraper here
    print("Triggered scraper for:", movie_id)

    return {
        "status": "success",
        "movieId": movie_id
    }
    
    
@https_fn.on_call(
    cpu=1,
    timeout_sec=540
)
def trigger_imdb_scraper_callable(req: https_fn.CallableRequest):
    print("Callable scraper triggered")
    return {"status": "success"}    

GRAPHQL_QUERY = """
query GetHomeModules($country: Country!, $language: Language!, $platform: Platform!) {
  urlV2(fullPath: "/", site: "www") {
    node {
      ... on HomePage {
        modules {
          __typename

          ... on HMAVOD {
            titles {
              id
              objectType
              content(country: $country, language: $language) {
                title
                originalReleaseYear
                posterUrl
                genres { translation(language: $language) }
                scoring { imdbScore }
              }
              watchNowOffer(country: $country, platform: $platform) {
                standardWebURL
                package { clearName shortName icon }
              }
            }
          }

          ... on HMBecauseYouLikedTitle {
            titles {
              id
              objectType
              content(country: $country, language: $language) {
                title
                originalReleaseYear
                posterUrl
                genres { translation(language: $language) }
                scoring { imdbScore }
              }
              watchNowOffer(country: $country, platform: $platform) {
                standardWebURL
                package { clearName shortName icon }
              }
            }
          }

          ... on HMCinemaMostAnticipated {
            titles {
              id
              objectType
              content(country: $country, language: $language) {
                title
                originalReleaseYear
                posterUrl
                genres { translation(language: $language) }
                scoring { imdbScore }
              }
              watchNowOffer(country: $country, platform: $platform) {
                standardWebURL
                package { clearName shortName icon }
              }
            }
          }

        }
      }
    }
  }
}
"""
@https_fn.on_request(timeout_sec=540)
def scrape_justwatch_movies(req):
    """
    HTTP trigger:
    - Runs JustWatch Selenium scraper
    - Stores FULL movie data in Firestore
    """

    country = req.args.get("country", "in")
    limit = int(req.args.get("limit", 20))

    print(f"🔥 JustWatch scrape triggered | country={country}, limit={limit}")

    driver = setup_driver()
    saved = 0

    try:
        movie_urls = get_popular_movies(driver, country, limit)

        for url in movie_urls:
            movie = scrape_movie(driver, url)
            if not movie or not movie.get("id"):
                continue

            db.collection("justwatch_movies") \
              .document(movie["id"]) \
              .set(movie, merge=True)

            saved += 1

    finally:
        driver.quit()

    return {
        "status": "success",
        "movies_saved": saved
    }



@https_fn.on_request(timeout_sec=120)
def justwatch_home(req):
    country = req.args.get("country", "IN")
    language = "en"
    platform = "WEB"

    payload = {
        "operationName": "GetHomeModules",
        "variables": {
            "country": country,
            "language": language,
            "platform": platform
        },
        "query": GRAPHQL_QUERY
    }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Origin": "https://www.justwatch.com",
        "Referer": "https://www.justwatch.com/"
    }

    res = requests.post(
        "https://apis.justwatch.com/graphql",
        json=payload,
        headers=headers,
        timeout=30
    )
    
    if res.status_code != 200:
        return {
            "status": "error",
            "httpCode": res.status_code,
            "justwatchResponse": res.text
        }

    # res.raise_for_status()
    data = res.json()

    movies = []

    modules = (
        data.get("data", {})
        .get("urlV2", {})
        .get("node", {})
        .get("modules", [])
    )
    
    if not modules:
        return {"status": "error", "message": "No modules returned from JustWatch"}

    
    print("MODULE TYPES:", [m.get("__typename") for m in modules])
    
    ALLOWED = {"HMTrendingToday", "HMNewOnStreaming", "HMPopular"}

    for module in modules:
        titles = module.get("titles", [])
        if not titles:
            continue

        for t in module["titles"]:
            content = t.get("content") or {}
            offer = t.get("watchNowOffer")

            movie = {
                "id": t["id"],
                "title": content.get("title"),
                "year": content.get("originalReleaseYear"),
                "rating": content.get("scoring", {}).get("imdbScore"),
                "description": content.get(""),
                "genres": [g["translation"] for g in content.get("genres", [])],
                "posterUrl": (
                    f"https://images.justwatch.com{content['posterUrl'].replace('{profile}', 's592')}"
                    if content.get("posterUrl") else ""
                ),
                "platform": offer["package"]["clearName"] if offer else None,
                "platformUrl": offer["standardWebURL"] if offer else None
            }

            movies.append(movie)

            # OPTIONAL: store in Firestore
            db.collection("justwatch_movies").document(str(movie["id"])).set({
                # "description": description,
                # "runtime": runtime,
                # "cast": cast,
                # "director": director,
                # "trailerUrl": trailer_url,
                # "ottProviders": ott_list
                
                "id": t["id"],
                "title": content.get("title"),
                "year": content.get("originalReleaseYear"),
                "rating": content.get("scoring", {}).get("imdbScore"),
                "genres": [g["translation"] for g in content.get("genres", [])],
                "posterUrl": (
                    f"https://images.justwatch.com{content['posterUrl'].replace('{profile}', 's592')}"
                    if content.get("posterUrl") else ""
                ),
                "platform": offer["package"]["clearName"] if offer else None,
                "platformUrl": offer["standardWebURL"] if offer else None
            },
                merge=True
            )

    return {
        "status": "success",
        "count": len(movies)
    }

   

# --- Helper Functions (from original script) ---

def get_imdb_page(url):
    """Get IMDb page content using requests for static content"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {str(e)}")
        return None

def setup_selenium_driver():
    """Set up Selenium WebDriver for dynamic content"""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    try:
        # For Firebase Functions, ChromeDriverManager might not work directly as it downloads the driver.
        # You'd typically use a pre-installed ChromeDriver. However, for a simple setup,
        # if Chrome is available in the environment (like Cloud Run or some Firebase Function runtimes),
        # specifying the path might be needed. For a general setup, let's assume it's in PATH or handled.
        # In a real Firebase Function, you'd likely use a pre-packaged WebDriver like those provided by Headless Chrome builds.
        # For demonstration, we'll keep ChromeDriverManager but be aware it might not work out-of-the-box in all CF environments.
        
        # NOTE: Using ChromeDriverManager in a Firebase Function environment is problematic because it tries to download
        # and manage the driver, which is usually not allowed or feasible in a serverless environment.
        # For actual deployment to Firebase Functions, you would typically use a pre-installed ChromeDriver
        # whose path you specify, or use a Docker image with ChromeDriver already present.
        # For this example, we'll keep it as is, but it will likely fail during deployment without a custom runtime/setup.
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.set_page_load_timeout(30)
        return driver
    except Exception as e:
        print(f"Error setting up Selenium driver: {str(e)}")
        # Log more details for debugging in Firebase Functions logs
        print(f"WebDriverException details: {e.__class__.__name__} - {e}")
        return None

def extract_trailer_url(driver, url):
    """Extract the first video URL (trailer) from IMDb with improved robustness"""
    trailer_url = None
    
    try:
        # Strategy 1: Try to click the "Trailer" button on the main page first
        driver.get(url)
        # Scroll down to ensure button is in view
        driver.execute_script("window.scrollTo(0, 500);") 
        time.sleep(1) # Give a moment for elements to become interactive

        # Look for the main trailer button/link
        try:
            # This selector often points to the primary trailer button on the main page
            trailer_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'a[data-testid="videos-slate-overlay-1"], a[aria-label*="Watch trailer"]'))
            )
            trailer_button.click()
            print(f"Clicked main trailer button for {url}")
            
            # Wait for video player to appear and get source
            video_element = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'video.jw-video'))
            )
            trailer_url = video_element.get_attribute('src')
            if trailer_url:
                print(f"Found trailer URL via main page click for {url}")
                return trailer_url

        except (TimeoutException, NoSuchElementException, WebDriverException) as e:
            print(f"Main trailer button not found or clickable for {url}, trying video gallery. Error: {e}")
            pass # Continue to next strategy if this fails

        # Strategy 2: Go directly to the video gallery page and try to play the first video
        print(f"Attempting video gallery for {url}")
        videos_url = url.rstrip('/') + '/videogallery'
        driver.get(videos_url)
        
        # Wait for thumbnails to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'div.ipc-poster-card div.ipc-media, a.ipc-lockup-overlay'))
        )
        
        try:
            # Try to find the first video thumbnail or link
            first_video_thumbnail = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'div.ipc-poster-card div.ipc-media, a.ipc-lockup-overlay'))
            )
            first_video_thumbnail.click()
            print(f"Clicked first video thumbnail on gallery for {url}")
            
            # Wait for video player to load and get the source
            video_element = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'video.jw-video'))
            )
            trailer_url = video_element.get_attribute('src')
            if trailer_url:
                print(f"Found trailer URL via video gallery for {url}")
                return trailer_url

        except (TimeoutException, NoSuchElementException, WebDriverException) as e:
            print(f"Could not click video or find player in gallery for {url}. Error: {e}")
            pass # Return None if all strategies fail

    except Exception as e:
        print(f"Unexpected error in extract_trailer_url for {url}: {str(e)}")
    
    return None

def extract_streaming_options_with_selenium(driver, url):
    """Extract OTT platforms with their names using Selenium for JS-rendered content"""
    streaming_options = []
    try:
        driver.get(url)
        # Scroll to load the streaming section, try multiple scrolls if needed
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
        time.sleep(1) # Short delay
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2) # Allow time for content to load
        
        # Wait for streaming options to appear
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a.ipc-lockup-overlay[aria-label*='Watch on']"))
        )
        
        # Parse the page with BeautifulSoup from Selenium's page source
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # Extract streaming platforms with their names
        platform_links = soup.find_all('a', class_='ipc-lockup-overlay', 
                                     attrs={'aria-label': lambda x: x and 'Watch on' in x})
        
        for link in platform_links:
            platform_name = link.get('aria-label', '').replace('Watch on', '').strip()
            if not platform_name:
                continue
            
            # Construct full URL for the platform
            platform_url_suffix = link.get('href', '')
            if platform_url_suffix:
                platform_url = "https://www.imdb.com" + platform_url_suffix if platform_url_suffix.startswith('/') else platform_url_suffix
                streaming_options.append({
                    "platform": platform_name,
                    "url": platform_url
                })
                
    except (TimeoutException, NoSuchElementException) as e:
        print(f"Timeout or element not found for streaming options on {url}: {str(e)}")
        pass # No streaming options found or failed to load
    except Exception as e:
        print(f"Error extracting streaming options with Selenium for {url}: {str(e)}")
    
    return streaming_options

def get_high_quality_poster(soup):
    """Extract high quality poster image URL"""
    try:
        poster_element = soup.select_one('img.ipc-image')
        if not poster_element:
            return "N/A"
        image_url = poster_element.get('src', '')
        if not image_url:
            # Fallback to srcset if src is empty
            srcset = poster_element.get('srcset', '')
            if srcset:
                # Get the last URL from srcset which is usually the highest quality
                image_url = srcset.split(',')[-1].strip().split(' ')[0]
        
        if not image_url or image_url == "N/A":
            return "N/A"

        # Try to get a higher quality version by manipulating the URL
        if '@._V1_' in image_url:
            return image_url.split('@._V1_')[0] + '@._V1_.jpg'
        elif '._V1_' in image_url: # Handle cases like 'UX128_CR0,0,128,170_AL_.jpg'
            # This part might need more robust regex or string manipulation
            # For now, if no _V1_ is found, return the original
            pass 
        return image_url
    except Exception as e:
        print(f"Error extracting high quality poster: {str(e)}")
        return "N/A"

def extract_release_date(soup):
    """Extract release date in the format 'Month Day, Year (Country)'"""
    try:
        # Prioritize data-testid as it's more stable
        release_info = soup.find('li', {'data-testid': 'title-details-releasedate'})
        if release_info:
            date_element = release_info.find('a', class_='ipc-metadata-list-item__list-content-item')
            if date_element:
                return date_element.get_text(strip=True)

        # Fallback to JSON-LD data
        script = soup.find('script', type='application/ld+json')
        if script:
            try:
                data = json.loads(script.string)
                # If data is a list, take the first element
                if isinstance(data, list):
                    data = data[0]
                release_date = data.get('datePublished', '')
                if release_date:
                    return release_date
            except json.JSONDecodeError:
                pass
        
        return "N/A"
    except Exception as e:
        print(f"Error extracting release date: {str(e)}")
        return "N/A"

def extract_movie_details(url, driver):
    """Extract movie details - static content with BeautifulSoup, OTT with Selenium"""
    html = get_imdb_page(url)
    if not html:
        return None

    soup = BeautifulSoup(html, 'html.parser')

    # Extract static content
    title_element = soup.select_one('h1[data-testid="hero__pageTitle"] span.hero__primary-text')
    title = title_element.get_text(strip=True) if title_element else "N/A"

    # Extract release year more robustly
    release_year = "N/A"
    try:
        year_element = soup.select_one('a[href*="releaseinfo"].ipc-link')
        if year_element:
            year_text = year_element.get_text(strip=True)
            if year_text and year_text.isdigit():
                release_year = year_text
    except Exception:
        pass # Keep N/A if not found

    # Runtime
    runtime = "N/A"
    try:
        runtime_element = soup.select_one('li[data-testid="title-techspec_runtime"] div.ipc-metadata-list-item__content')
        if runtime_element:
            runtime = runtime_element.get_text(strip=True)
    except Exception:
        pass

    # Rating
    rating_element = soup.select_one('div[data-testid="hero-rating-bar__aggregate-rating__score"] span.ipc-rating-star__rating')
    rating = rating_element.get_text(strip=True).split('/')[0] if rating_element else "N/A"

    # Director
    director = "N/A"
    director_section = soup.find('li', {'data-testid': 'title-pc-principal-credit', 'class': 'ipc-metadata-list__item'})
    if director_section:
        director_link = director_section.find('a', class_='ipc-metadata-list-item__list-content-item')
        if director_link:
            director = director_link.get_text(strip=True)

    # Cast
    cast = []
    cast_items = soup.select('a[data-testid="title-cast-item__actor"]')
    for i, item in enumerate(cast_items):
        if i >= 5: # Limit to top 5
            break
        cast.append(item.get_text(strip=True))

    poster_url = get_high_quality_poster(soup)

    storyline_element = soup.select_one('span[data-testid="plot-xl"]')
    storyline = storyline_element.get_text(strip=True) if storyline_element else "N/A"

    genres = []
    genre_elements = soup.select('a.ipc-chip.ipc-chip--on-baseAlt') # More specific selector for genres
    if genre_elements:
        genres = [genre.get_text(strip=True) for genre in genre_elements]

    release_date = extract_release_date(soup)

    # Get streaming options and trailer URL with Selenium
    streaming_options = extract_streaming_options_with_selenium(driver, url)
    trailer_url = extract_trailer_url(driver, url)

    imdb_id = url.split('/title/')[1].strip('/') if '/title/' in url else "N/A"

    region = ""
    if release_date and isinstance(release_date, str) and "(" in release_date and ")" in release_date:
        region_match = release_date.split('(')[-1].replace(')', '').strip()
        if region_match:
            region = region_match
    
    # Check if release_date is a valid date string before attempting to format
    try:
        # Example: "Month Day, Year (Country)" or "YYYY-MM-DD"
        if release_date and release_date != "N/A":
            # Strip off country in parenthesis for date parsing
            date_part_for_parsing = release_date.split('(')[0].strip()
            
            # Try a few common date formats
            parsed_date = None
            for fmt in ('%B %d, %Y', '%Y-%m-%d', '%d %B %Y'):
                try:
                    parsed_date = datetime.strptime(date_part_for_parsing, fmt)
                    break
                except ValueError:
                    continue
            
            if parsed_date:
                release_date_formatted = release_date # Keep original format with country if present
            else:
                release_date_formatted = ""
        else:
            release_date_formatted = ""
    except Exception:
        release_date_formatted = "" # Invalid date format or other error

    movie_data = {
        "description": storyline,
        "watchLinks": {
            "IMDB": url,
            "OTT": streaming_options
        },
        "releaseType": "Theatrical", # Default, could be refined if more info available
        "trailerUrl": trailer_url if trailer_url else "",
        "director": director,
        "imdbId": imdb_id,
        "releaseDate": release_date_formatted,
        "title": title,
        "region": region,
        "lastUpdated": datetime.utcnow().isoformat() + "Z",
        "cast": cast,
        "genres": genres,
        "posterUrl": poster_url,
        "id": imdb_id
    }

    return movie_data

def scrape_single_url(url, driver):
    """Wrapper to scrape a single URL and handle its logging."""
    print(f"Scraping: {url}")
    movie_data = None
    try:
        movie_data = extract_movie_details(url, driver)
        if movie_data:
            print(f"Successfully scraped: {movie_data['title']} ({url})")
            if movie_data.get('trailerUrl'):
                print(f"  Found trailer URL: {movie_data['trailerUrl']}")
            else:
                print(f"  No trailer URL found for {movie_data['title']}")
            if movie_data['watchLinks']['OTT']:
                pass
        else:
            print(f"Failed to scrape details for: {url}")
    except Exception as e:
        print(f"Unhandled error scraping {url}: {str(e)}")
    return movie_data

def scrape_imdb_movies_optimized(urls, max_workers=2):
    """Main scraping function with optimized approach using ThreadPoolExecutor."""
    all_movies_data = []
    
    # Create a pool of Selenium drivers, one for each worker
    # In a Firebase Function, you might need to manage driver lifecycle carefully.
    # For a serverless environment, initializing a driver for each request can be slow.
    # A ThreadPoolExecutor with shared drivers or a more robust driver management strategy
    # might be needed for production. For this example, we re-initialize per function call.
    drivers = [setup_selenium_driver() for _ in range(max_workers)]
    drivers = [driver for driver in drivers if driver is not None] # Filter out failed setups

    if not drivers:
        print("No Selenium drivers could be initialized. Exiting scraping.")
        return []

    try:
        with ThreadPoolExecutor(max_workers=len(drivers)) as executor:
            future_to_url = {}
            # Distribute URLs among available drivers in a round-robin fashion
            for i, url in enumerate(urls):
                driver_index = i % len(drivers)
                # Pass the specific driver instance to the scrape_single_url function
                future = executor.submit(scrape_single_url, url, drivers[driver_index])
                future_to_url[future] = url

            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    movie_data = future.result()
                    if movie_data:
                        all_movies_data.append(movie_data)
                        # Store in Firestore (or other database) immediately after scraping
                        if movie_data.get('id'):
                            doc_ref = db.collection('movies').document(movie_data['id'])
                            doc_ref.set(movie_data)
                            print(f"Stored movie {movie_data['title']} in Firestore.")
                except Exception as exc:
                    print(f'{url} generated an exception: {exc}')

        return all_movies_data

    finally:
        for driver in drivers:
            if driver:
                driver.quit()
        print("All Selenium drivers closed.")

def fetch_json_from_url(url):
    """Fetch JSON data from a given URL"""
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching JSON from {url}: {str(e)}")
        return None

# --- Firebase Functions ---

@scheduler_fn.on_schedule(
    schedule="every 4 days", # Runs every 4th day. Adjust as needed.
    timezone="Asia/Kolkata", # Set to your desired timezone (e.g., "America/New_York", "Europe/London")
    timeout_sec=540 # Max timeout for scheduled functions is 540 seconds (9 minutes)
)
def scheduled_imdb_scraper(event: scheduler_fn.ScheduledEvent):
    """
    Scheduled function to fetch movie data from a URL, scrape IMDb for enhanced data,
    and store it in Firestore.
    """
    print(f"Scheduled IMDb scraper triggered at {datetime.now()}.")
    json_url = 'https://get-movies-hrtdxeyniq-uc.a.run.app/'
    max_workers = 3 # Adjust based on available memory and CPU, and IMDb's rate limits

    # Fetch the JSON data from the URL
    print(f"Fetching movie data from {json_url}...")
    data = fetch_json_from_url(json_url)
    
    if not data:
        print("Failed to fetch data from the URL. Aborting scheduled run.")
        return

    if 'movies' not in data or not isinstance(data['movies'], list):
        print(f"Error: JSON structure invalid. Expected 'movies' key with a list. Aborting scheduled run.")
        return

    imdb_urls_to_scrape = []
    # Extract IMDb URLs from the fetched data
    for movie in data['movies']:
        if 'watchLinks' in movie and 'IMDB' in movie['watchLinks']:
            imdb_url = movie['watchLinks']['IMDB']
            if imdb_url and imdb_url.startswith("https://www.imdb.com/title/"):
                imdb_urls_to_scrape.append(imdb_url)
    
    if not imdb_urls_to_scrape:
        print("No IMDb URLs found in the fetched JSON to scrape. Scheduled run complete.")
        return

    print(f"Found {len(imdb_urls_to_scrape)} IMDb URLs to scrape from the fetched data.")

    # Scrape the IMDb URLs to get enhanced data and store directly to Firestore
    enhanced_movies_data = scrape_imdb_movies_optimized(imdb_urls_to_scrape, max_workers)

    print(f"Scheduled scraping complete. Processed {len(enhanced_movies_data)} movies.")
    return {"status": "success", "movies_processed": len(enhanced_movies_data)}

@https_fn.on_call(
    cpu=1,
    timeout_sec=540 # Max timeout for callable functions is 540 seconds (9 minutes)
)
def trigger_imdb_scraper_now(req: https_fn.CallableRequest):
    """
    Callable function to manually trigger the IMDb scraper.
    Can optionally take a list of IMDb URLs in the request data.
    """
    print(f"Manual IMDb scraper triggered at {datetime.now()}.")
    
    imdb_urls_to_scrape = []
    json_url_fallback = 'https://get-movies-hrtdxeyniq-uc.a.run.app/'
    max_workers = 3

    # Check if specific URLs are provided in the request data
    if req.data and 'urls' in req.data and isinstance(req.data['urls'], list):
        print("Scraping specific URLs provided in the request.")
        for url in req.data['urls']:
            if isinstance(url, str) and url.startswith("https://www.imdb.com/title/"):
                imdb_urls_to_scrape.append(url)
    else:
        # Fallback to fetching from the default JSON URL if no URLs are provided
        print(f"No specific URLs provided. Fetching movie data from {json_url_fallback}...")
        data = fetch_json_from_url(json_url_fallback)
        if not data:
            print("Failed to fetch data from the fallback URL. Aborting manual run.")
            raise https_fn.HttpsError(
                code=https_fn.FunctionsErrorCode.INTERNAL,
                message="Failed to fetch initial movie data."
            )

        if 'movies' not in data or not isinstance(data['movies'], list):
            print(f"Error: JSON structure invalid from fallback URL. Aborting manual run.")
            raise https_fn.HttpsError(
                code=https_fn.FunctionsErrorCode.INTERNAL,
                message="Invalid JSON structure from movie data source."
            )
        
        for movie in data['movies']:
            if 'watchLinks' in movie and 'IMDB' in movie['watchLinks']:
                imdb_url = movie['watchLinks']['IMDB']
                if imdb_url and imdb_url.startswith("https://www.imdb.com/title/"):
                    imdb_urls_to_scrape.append(imdb_url)

    if not imdb_urls_to_scrape:
        print("No IMDb URLs found to scrape. Manual run complete.")
        return {"status": "success", "message": "No IMDb URLs found or provided to scrape."}

    print(f"Found {len(imdb_urls_to_scrape)} IMDb URLs to scrape.")

    # Scrape the IMDb URLs to get enhanced data and store directly to Firestore
    enhanced_movies_data = scrape_imdb_movies_optimized(imdb_urls_to_scrape, max_workers)

    print(f"Manual scraping complete. Processed {len(enhanced_movies_data)} movies.")
    return {"status": "success", "movies_processed": len(enhanced_movies_data)}