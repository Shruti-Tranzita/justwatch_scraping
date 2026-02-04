from fastapi import FastAPI, BackgroundTasks, Query
from util.scraper.justwatch_scraper import (
    start_scraping,
    search_and_scrape
)

app = FastAPI(
    title="JustWatch Scraping API",
    description="Triggers JustWatch scraping on demand",
    version="1.0.0"
)


@app.post("/api/scrape/popular")
def scrape_popular_movies(
    background_tasks: BackgroundTasks,
    country: str = Query("in", description="Country code like in, us, uk"),
    limit: int = Query(20, description="Number of movies to scrape")
):
    """
    Triggers scraping of popular movies from JustWatch in the background.
    """

    background_tasks.add_task(
        start_scraping,
        country=country,
        limit=limit
    )

    return {
        "status": "started",
        "message": "Popular movie scraping started in background",
        "country": country,
        "limit": limit
    }
