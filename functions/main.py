from firebase_functions import https_fn
from router.health import health_check
from router.movies import get_popular_movies
from router.movies import get_all_movies
from router.movies import get_movie_year


@https_fn.on_request(region="asia-south1")
def api(req):
    path = req.path
    method = req.method

    if path == "/health_check" and method == "GET":
        return health_check()
    
    if path == "/movies/get_all" and method == "GET":
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