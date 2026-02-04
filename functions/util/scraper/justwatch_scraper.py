"""
JustWatch Movie Scraper
Extracts movie data from JustWatch.com including title, rating, description,
year, genres, cast, poster, trailer, and OTT platform information.
"""

import os
import json
import time
import random
import re
from datetime import datetime
from urllib.parse import urlparse, parse_qs

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Default country code (can be changed: 'us', 'in', 'uk', etc.)
DEFAULT_COUNTRY = "in"


# ---------------- DRIVER SETUP ---------------- #

def setup_driver():
    """Initialize headless Chrome driver with anti-detection settings."""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )
    driver.delete_all_cookies()
    driver.set_page_load_timeout(30)
    return driver


# ---------------- HELPER FUNCTIONS ---------------- #

def safe_text(soup, selector):
    """Safely extract text from a CSS selector."""
    el = soup.select_one(selector)
    return el.get_text(strip=True) if el else ""


def safe_attr(soup, selector, attr):
    """Safely extract an attribute from a CSS selector."""
    el = soup.select_one(selector)
    return el.get(attr, "") if el else ""


def extract_year_from_text(text):
    """Extract year (1900-2099) from a text string."""
    if not text:
        return None
    match = re.search(r'(19|20)\d{2}', text)
    return int(match.group()) if match else None


def construct_youtube_url(video_id):
    """Construct YouTube URL from video ID."""
    if video_id:
        # Clean video ID - remove any extra suffixes
        clean_id = video_id.split('-')[0] if '-' in video_id and len(video_id.split('-')[0]) == 11 else video_id
        # YouTube video IDs are typically 11 characters
        if len(clean_id) >= 11:
            clean_id = clean_id[:11]
        return f"https://www.youtube.com/watch?v={clean_id}"
    return ""


# ---------------- SCRAPING LOGIC ---------------- #

def scrape_movie(driver, url):
    """
    Scrape detailed movie information from a JustWatch movie page.
    
    Args:
        driver: Selenium WebDriver instance
        url: JustWatch movie detail page URL
        
    Returns:
        dict: Movie data with all required fields, or None if scraping failed
    """
    print(f"Scraping: {url}")
    time.sleep(random.uniform(2.0, 4.0))

    try:
        driver.get(url)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
    except TimeoutException:
        print(f"Page load timeout for: {url}")
        return None

    # Scroll to load lazy content
    # for _ in range(3):
    #     driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    #     time.sleep(1)
    
    # # Scroll back to top
    # driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(1)

    soup = BeautifulSoup(driver.page_source, "html.parser")

    # ---- Extract Movie ID from URL ----
    movie_id = url.rstrip('/').split('/')[-1]

    # ---- Title ----
    title = ""
    title_el = soup.select_one('div.title-block h1')
    if title_el:
        title = title_el.get_text(strip=True)
    if not title:
        title_el = soup.select_one('h1')
        if title_el:
            title = title_el.get_text(strip=True)
    
    # Clean title: remove year suffix like "(2014)" at the end
    title = re.sub(r'\s*\(\d{4}\)\s*$', '', title)

    # ---- Release Year ----
    year = None
    # First try to extract from title before cleaning
    title_with_year = soup.select_one('h1')
    if title_with_year:
        year_match = re.search(r'\((19|20\d{2})\)', title_with_year.get_text())
        if year_match:
            year = int(year_match.group(1))
    
    # Fallback: look for release-year span
    if not year:
        year_el = soup.select_one('span.release-year')
        if year_el:
            year = extract_year_from_text(year_el.get_text())
    
    # Try alternate location in "About the movie" section
    if not year:
        for h3 in soup.select('h3'):
            if 'Release' in h3.get_text():
                parent = h3.find_parent('div')
                if parent:
                    value_div = parent.select_one('.detail-infos__value')
                    if value_div:
                        year = extract_year_from_text(value_div.get_text())
                        break

    # ---- Rating (IMDb rating) ----
    rating = 0.0
    
    rating_el = soup.select_one(
        '.imdb-score'
    )

    if rating_el:
        try:
            # print("ratinge;>>", rating_el.get_text(strip=True).split("(")[0])
            rating = float(rating_el.get_text(strip=True).split(r"(")[0])
        except ValueError:
            rating = None
    # Method 1: Look for rating value near IMDb text/logo
    for div in soup.select('div.jw-scoring-listing'):
        div_text = div.get_text(' ', strip=True).upper()
        if 'IMDB' in div_text:
            rating_el = div.select_one('.jw-scoring-listing__rating span, .jw-scoring-listing__rating')
            if rating_el:
                rating_text = rating_el.get_text(strip=True)
                try:
                    rating = float(rating_text)
                    break
                except ValueError:
                    pass
    
    # Method 2: Look for any element with data containing rating
    if rating == 0.0:
        for span in soup.select('span'):
            text = span.get_text(strip=True)
            # IMDb ratings are typically X.X format between 0-10
            if re.match(r'^\d\.\d$', text):
                try:
                    potential_rating = float(text)
                    if 0 < potential_rating <= 10:
                        rating = potential_rating
                        break
                except ValueError:
                    pass

    # ---- Description/Synopsis ----
    description = ""
    synopsis_el = soup.select_one('#synopsis p.text-wrap-pre-line')
    if synopsis_el:
        description = synopsis_el.get_text(strip=True)
    if not description:
        synopsis_section = soup.select_one('#synopsis')
        if synopsis_section:
            p_el = synopsis_section.select_one('p')
            if p_el:
                description = p_el.get_text(strip=True)

    # ---- Genres ----
    genres = []
    
    # Method 1: Look for genre links anywhere on the page
    genre_links = soup.select('a[href*="/genres/"]')
    if genre_links:
        for g in genre_links:
            genre_text = g.get_text(strip=True)
            if genre_text and genre_text not in genres:
                genres.append(genre_text)
            if len(genres) >= 5:
                break
    
    # Method 2: Look in "About the movie" section
    if not genres:
        for h3 in soup.select('h3'):
            h3_text = h3.get_text(strip=True)
            if 'Genre' in h3_text:
                parent = h3.find_parent('div', class_='detail-infos')
                if parent:
                    value_div = parent.select_one('.detail-infos__value')
                    if value_div:
                        # Genres might be comma-separated or in individual spans
                        genre_text = value_div.get_text(strip=True)
                        genres = [g.strip() for g in genre_text.split(',') if g.strip()]
                        break
                # Also check sibling element
                sibling = h3.find_next_sibling('div')
                if sibling:
                    genre_text = sibling.get_text(strip=True)
                    if genre_text:
                        genres = [g.strip() for g in genre_text.split(',') if g.strip()]
                        break

    # ---- Cast ----
    cast = []
    # Method 1: Look for actor images with alt text
    for img in soup.select('div.title-credits__actor img'):
        actor_name = img.get('alt', '').strip()
        if actor_name and actor_name not in cast:
            cast.append(actor_name)
        if len(cast) >= 5:
            break
    
    # Method 2: Look for cast section in "About the movie"
    if not cast:
        for h3 in soup.select('h3'):
            if 'Cast' in h3.get_text():
                parent = h3.find_parent('div', class_='detail-infos')
                if parent:
                    # Try to find actor names in links or spans
                    for a in parent.select('a'):
                        actor_name = a.get_text(strip=True)
                        if actor_name and actor_name not in cast:
                            cast.append(actor_name)
                        if len(cast) >= 5:
                            break
                    break

    # ---- Poster URL ----
    poster_url = ""
    # Look for main poster image
    poster_el = soup.select_one('picture.picture-comp img')
    if poster_el:
        # Prefer srcset for higher quality
        srcset = poster_el.get('srcset', '')
        if srcset:
            # Get the highest resolution from srcset
            poster_url = srcset.split(',')[-1].strip().split(' ')[0]
        else:
            poster_url = poster_el.get('src', '')
    
    # Fallback: look for any large poster image
    if not poster_url:
        for img in soup.select('img'):
            src = img.get('src', '')
            if 'poster' in src.lower() or 'backdrop' in src.lower():
                poster_url = src
                break

    # ---- Trailer URL ----
    trailer_url = ""
    # Look for YouTube player div with video ID
    youtube_div = soup.select_one('div[id^="youtube-player-"]')
    if youtube_div:
        div_id = youtube_div.get('id', '')
        # Extract video ID from the div id (format: youtube-player-{VIDEO_ID})
        if 'youtube-player-' in div_id:
            video_id = div_id.replace('youtube-player-', '')
            trailer_url = construct_youtube_url(video_id)
    
    # Alternative: Look for YouTube URL in data attributes or iframes
    if not trailer_url:
        youtube_iframe = soup.select_one('iframe[src*="youtube.com"]')
        if youtube_iframe:
            iframe_src = youtube_iframe.get('src', '')
            if 'embed/' in iframe_src:
                video_id = iframe_src.split('embed/')[-1].split('?')[0]
                trailer_url = construct_youtube_url(video_id)

    # ---- OTT Platform Information ----
    platform = None
    platform_url = None
    platform_image = None
    quality = None

    # Find streaming offers
    offer_links = soup.select('a.offer')
    # print(offer_links)
    
    if offer_links:
        first_offer = offer_links[0]
        
        
        # Platform URL
        platform_url = first_offer.get('href', '')
        
        # Platform name from provider icon alt text
        provider_icon = first_offer.select_one('img.provider-icon')
        if provider_icon:
            platform = provider_icon.get('alt', '').strip()
            # Platform icon image
            platform_image = provider_icon.get('src', '')
        
        # Quality label
        quality_el = first_offer.select_one('span.offer__label--presentation')
        if quality_el:
            quality = quality_el.get_text(strip=True)
        else:
            # Check for quality in offer text
            offer_text = first_offer.get_text(' ', strip=True).lower()
            if '4k' in offer_text or 'ultra' in offer_text:
                quality = "4K"
            elif 'hd' in offer_text:
                quality = "HD"
            else:
                quality = "HD"  # Default

    return {
        "id": movie_id,
        "title": title,
        "rating": rating,
        "description": description,
        "year": year,
        "genres": genres,
        "cast": cast,
        "posterUrl": poster_url,
        "trailerUrl": trailer_url,
        "platform": platform,
        "platformUrl": platform_url,
        "platformImage": platform_image,
        "quality": quality,
        "lastUpdated": datetime.utcnow().isoformat() + "Z"
    }


def get_popular_movie_urls(driver, country=DEFAULT_COUNTRY, limit=20):
    """
    Get URLs of popular movies from JustWatch.
    
    Args:
        driver: Selenium WebDriver instance
        country: Country code (e.g., 'in', 'us', 'uk')
        limit: Maximum number of movie URLs to return
        
    Returns:
        list: List of movie detail page URLs
    """
    base_url = f"https://www.justwatch.com/{country}/movies"
    print(f"Fetching popular movies from: {base_url}")
    
    try:
        driver.get(base_url)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
    except TimeoutException:
        print("Page load timeout for popular movies")
        return []
    
    # Scroll to load more movies
    # for _ in range(3):
    #     driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    #     time.sleep(2)
    
    soup = BeautifulSoup(driver.page_source, "html.parser")
    
    movie_urls = []
    # Look for movie card links
    for a in soup.select('a[href*="/movie/"]'):
        href = a.get('href', '')
        if '/movie/' in href:
            # Construct full URL
            if href.startswith('/'):
                full_url = f"https://www.justwatch.com{href}"
            else:
                full_url = href
            
            if full_url not in movie_urls:
                movie_urls.append(full_url)
            
            if len(movie_urls) >= limit:
                break
    
    print(f"Found {len(movie_urls)} movie URLs")
    return movie_urls


def scrape_movies_from_urls(driver, urls):
    """
    Scrape multiple movies from a list of URLs.
    
    Args:
        driver: Selenium WebDriver instance
        urls: List of movie detail page URLs
        
    Returns:
        list: List of movie data dictionaries
    """
    results = []
    for url in urls:
        movie = scrape_movie(driver, url)
        if movie:
            results.append(movie)
    return results


# ---------------- MAIN ENTRY POINTS ---------------- #

def start_scraping(country=DEFAULT_COUNTRY, limit=20):
    """
    Main function to scrape popular movies from JustWatch.
    
    Args:
        country: Country code (e.g., 'in', 'us', 'uk')
        limit: Maximum number of movies to scrape
        
    Returns:
        dict: Result summary with message, count, and output file path
    """
    output_json = os.path.join(BASE_DIR, "justwatch_movies.json")
    
    driver = setup_driver()
    results = []
    
    try:
        # Get popular movie URLs
        movie_urls = get_popular_movie_urls(driver, country, limit)
        
        # Scrape each movie
        for url in movie_urls:
            movie = scrape_movie(driver, url)
            if movie:
                results.append(movie)
                
    finally:
        driver.quit()
    
    # Save results
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    return {
        "message": "Scraping completed",
        "count": len(results),
        "output": output_json
    }


def scrape_from_urls_file(input_file="movie_urls.json"):
    """
    Scrape movies from a JSON file containing URLs.
    
    Args:
        input_file: Path to JSON file with movie URLs
        
    Returns:
        dict: Result summary
    """
    input_json = os.path.join(BASE_DIR, input_file)
    output_json = os.path.join(BASE_DIR, "justwatch_movies.json")
    
    with open(input_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Support multiple input formats
    if isinstance(data, list):
        urls = data
    elif isinstance(data, dict) and "movies" in data:
        urls = [m.get("url") for m in data["movies"] if m.get("url")]
    else:
        urls = []
    
    driver = setup_driver()
    results = []
    
    try:
        for url in urls:
            movie = scrape_movie(driver, url)
            if movie:
                results.append(movie)
    finally:
        driver.quit()
    
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    return {
        "message": "Scraping completed",
        "count": len(results),
        "output": output_json
    }


def search_and_scrape(query, country=DEFAULT_COUNTRY):
    """
    Search for a movie and scrape its details.
    
    Args:
        query: Search query (movie name)
        country: Country code
        
    Returns:
        dict: Movie data or None
    """
    driver = setup_driver()
    
    try:
        search_url = f"https://www.justwatch.com/{country}/search?q={query}"
        print(f"Searching: {search_url}")
        
        driver.get(search_url)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(2)
        
        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        # Get first movie result
        first_result = soup.select_one('a[href*="/movie/"]')
        if first_result:
            href = first_result.get('href', '')
            if href.startswith('/'):
                movie_url = f"https://www.justwatch.com{href}"
            else:
                movie_url = href
            
            return scrape_movie(driver, movie_url)
        
        return None
        
    finally:
        driver.quit()


# ---------------- CLI ENTRY POINT ---------------- #

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="JustWatch Movie Scraper")
    parser.add_argument(
        "--country", 
        type=str, 
        default=DEFAULT_COUNTRY,
        help="Country code (e.g., 'in', 'us', 'uk')"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of movies to scrape"
    )
    parser.add_argument(
        "--search",
        type=str,
        help="Search for a specific movie"
    )
    parser.add_argument(
        "--url",
        type=str,
        help="Scrape a specific movie URL"
    )
    
    args = parser.parse_args()
    
    if args.search:
        # Search and scrape a specific movie
        result = search_and_scrape(args.search, args.country)
        if result:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print("Movie not found")
    elif args.url:
        # Scrape a specific URL
        driver = setup_driver()
        try:
            result = scrape_movie(driver, args.url)
            if result:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print("Failed to scrape movie")
        finally:
            driver.quit()
    else:
        # Scrape popular movies
        result = start_scraping(args.country, args.limit)
        print(json.dumps(result, indent=2))
