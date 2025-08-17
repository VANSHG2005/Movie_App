from flask import Flask, render_template, request, jsonify, url_for, session, redirect
import joblib
import requests
from rapidfuzz import process
from datetime import datetime
from functools import lru_cache
import time
import os
from dotenv import load_dotenv
from oauthlib.oauth2 import WebApplicationClient
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_migrate import Migrate
import uuid

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(24)


load_dotenv()

# Load precomputed data
movie_df = joblib.load('model/tmdb_movies.pkl')
movie_similarity = joblib.load('model/tmdb_similarity.pkl')
tv_df = joblib.load('model/tmdb_tv_series.pkl')
tv_similarity = joblib.load('model/tmdb_tv_similarity.pkl')

TMDB_API_KEY = os.getenv('TMDB_API_KEY')
TMDB_IMAGE_URL = "https://image.tmdb.org/t/p/w500"

if TMDB_API_KEY:
        print(f"API Key loaded: {TMDB_API_KEY}")
else:
    print("API Key not found in environment variables.")

# Configure login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # Specify the login view
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'

# Google OAuth config
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"

client = WebApplicationClient(GOOGLE_CLIENT_ID)

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
app.config['SESSION_COOKIE_SECURE'] = True  # For HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# ------------- Helpers -------------

def get_best_match(title, choices):
    match = process.extractOne(title, choices, score_cutoff=60)
    return match[0] if match else None

def get_movie_recommendations(movie_name):
    titles = movie_df["title"].tolist()
    closest_match = get_best_match(movie_name, titles)

    if not closest_match:
        return None, []

    index_of_movie = movie_df[movie_df.title == closest_match].index.values[0]
    similarity_scores = list(enumerate(movie_similarity[index_of_movie]))
    sorted_scores = sorted(similarity_scores, key=lambda x: x[1], reverse=True)

    searched_movie_row = movie_df.iloc[index_of_movie]
    searched_movie = {
        "id": searched_movie_row["id"],
        "title": searched_movie_row["title"],
        "poster_path": searched_movie_row["poster_path"]
    }

    recs = []
    titles_seen = set()
    for i, _ in sorted_scores[1:]:
        movie = movie_df.iloc[i]
        title = movie["title"]
        if title == searched_movie["title"] or title in titles_seen:
            continue
        titles_seen.add(title)
        recs.append({
            "id": movie["id"],
            "title": title,
            "poster_path": movie["poster_path"]
        })
        if len(recs) == 30:
            break

    return searched_movie, recs

def get_tv_recommendations(tv_name):
    try:
        # Check what columns actually exist in your DataFrame
        print("Available columns in tv_df:", tv_df.columns.tolist())
        
        # Adjust based on actual column names
        title_column = "name" if "name" in tv_df.columns else "title"
        titles = tv_df[title_column].tolist()
        
        closest_match = get_best_match(tv_name, titles)

        if not closest_match:
            return None, []

        index_of_tv = tv_df[tv_df[title_column] == closest_match].index.values[0]
        similarity_scores = list(enumerate(tv_similarity[index_of_tv]))
        sorted_scores = sorted(similarity_scores, key=lambda x: x[1], reverse=True)

        searched_tv_row = tv_df.iloc[index_of_tv]
        searched_tv = {
            "id": searched_tv_row["id"],
            "name": searched_tv_row[title_column],
            "poster_path": searched_tv_row["poster_path"]
        }

        recs = []
        titles_seen = set()
        for i, _ in sorted_scores[1:]:
            tv = tv_df.iloc[i]
            name = tv[title_column]
            if name == searched_tv["name"] or name in titles_seen:
                continue
            titles_seen.add(name)
            recs.append({
                "id": tv["id"],
                "name": name,
                "poster_path": tv["poster_path"]
            })
            if len(recs) == 30:
                break

        return searched_tv, recs
    except Exception as e:
        app.logger.error(f"Error in get_tv_recommendations: {str(e)}")
        return None, []

def fetch_movies_by_category(category, genre_id=None):
    try:
        url = f"https://api.themoviedb.org/3/movie/{category}" if not genre_id else \
              f"https://api.themoviedb.org/3/discover/movie?with_genres={genre_id}"
        params = {"api_key": TMDB_API_KEY}
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises an HTTPError for bad responses
        return response.json().get("results", [])[:20]
    except requests.RequestException as e:
        print(f"Error fetching movies for {category}: {e}")
        return []

def fetch_tv_by_category(category, genre_id=None):
    try:
        url = f"https://api.themoviedb.org/3/tv/{category}" if not genre_id else \
              f"https://api.themoviedb.org/3/discover/tv?with_genres={genre_id}"
        params = {"api_key": TMDB_API_KEY}
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json().get("results", [])[:20]
    except requests.RequestException as e:
        print(f"Error fetching TV shows for {category}: {e}")
        return []
    
def get_movie_credits(movie_id):
    url = f"https://api.themoviedb.org/3/movie/{movie_id}/credits?api_key={TMDB_API_KEY}"
    response = requests.get(url)
    
    if response.status_code != 200:
        return {'cast': [], 'crew': []}  
    
    data = response.json()
    
    cast = []
    for person in data.get('cast', [])[:10]:
        cast.append({
            'id': person.get('id'),
            'name': person.get('name'),
            'character': person.get('character'),
            'profile_path': person.get('profile_path')
        })
    
    crew = []
    for person in data.get('crew', []):
        if person.get('job') in ['Director', 'Screenplay', 'Writer', 'Producer']:
            crew.append({
                'id': person.get('id'),
                'name': person.get('name'),
                'job': person.get('job'),
                'profile_path': person.get('profile_path')
            })
    
    return {
        'cast': cast,
        'crew': crew
    }

def get_movie_info(movie_id):
    try:
        url = f"https://api.themoviedb.org/3/movie/{movie_id}?api_key={TMDB_API_KEY}&language=en-US"
        response = requests.get(url)
        if response.status_code != 200:
            return None, []  # Return tuple even if failed

        movie_data = response.json()

        # Get related (franchise) movies
        collection = movie_data.get("belongs_to_collection")
        related_movies = []
        if collection:
            collection_id = collection["id"]
            coll_url = f"https://api.themoviedb.org/3/collection/{collection_id}?api_key={TMDB_API_KEY}&language=en-US"
            coll_response = requests.get(coll_url)
            if coll_response.status_code == 200:
                related_movies = coll_response.json().get("parts", [])
                # Remove the original movie from related list
                related_movies = [m for m in related_movies if m["id"] != movie_id]

        # Convert genre list
        movie_data["genres"] = [g["name"] for g in movie_data.get("genres", [])]

        return movie_data, related_movies
    except Exception as e:
        print("Error fetching movie info:", e)
        return None, []

def get_movie_trailer(movie_id):
    url = f"https://api.themoviedb.org/3/movie/{movie_id}/videos?api_key={TMDB_API_KEY}"
    response = requests.get(url)
    if response.status_code == 200:
        videos = response.json().get("results", [])
        for video in videos:
            if video['site'] == 'YouTube' and video['type'] == 'Trailer':
                return video['key']
    return None

def get_tv_info(tv_id):
    try:
        url = f"https://api.themoviedb.org/3/tv/{tv_id}?api_key={TMDB_API_KEY}&language=en-US"
        response = requests.get(url)
        if response.status_code != 200:
            return None

        return response.json()
    except Exception as e:
        print("Error fetching TV info:", e)
        return None

def get_tv_credits(tv_id):
    """Fetch TV show credits from TMDB API and ensure proper structure"""
    url = f"https://api.themoviedb.org/3/tv/{tv_id}/credits?api_key={TMDB_API_KEY}"
    response = requests.get(url)
    
    if response.status_code != 200:
        return {'cast': [], 'crew': []}
    
    data = response.json()
    
    # Process cast data with ID
    cast = []
    for person in data.get('cast', [])[:10]: 
        if 'id' in person:  
            cast.append({
                'id': person['id'],
                'name': person.get('name'),
                'character': person.get('character'),
                'profile_path': person.get('profile_path')
            })
    
    # Process crew data with ID
    crew = []
    for person in data.get('crew', []):
        if 'id' in person and person.get('job') in ['Director', 'Screenplay', 'Writer', 'Producer']:
            crew.append({
                'id': person['id'],
                'name': person.get('name'),
                'job': person.get('job'),
                'profile_path': person.get('profile_path')
            })
    
    return {
        'cast': cast,
        'crew': crew
    }

def get_tv_trailer(tv_id):
    url = f"https://api.themoviedb.org/3/tv/{tv_id}/videos?api_key={TMDB_API_KEY}"
    response = requests.get(url)
    if response.status_code == 200:
        videos = response.json().get("results", [])
        for video in videos:
            if video['site'] == 'YouTube' and video['type'] == 'Trailer':
                return video['key']
    return None

def get_similar_tv(tv_id):
    url = f"https://api.themoviedb.org/3/tv/{tv_id}/similar?api_key={TMDB_API_KEY}"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json().get("results", [])[:6]
    return []

def get_similar_movie(movie_id):
    url = f"https://api.themoviedb.org/3/movie/{movie_id}/similar?api_key={TMDB_API_KEY}"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json().get("results", [])[:6]
    return []


# ------------- Routes -------------

def get_genres_dict():
    return {
        'movies': {
            28: {'name': 'Action', 'tv_match': [10759]},
            12: {'name': 'Adventure', 'tv_match': [10759]},
            16: {'name': 'Animation', 'tv_match': [16]},
            35: {'name': 'Comedy', 'tv_match': [35]},
            80: {'name': 'Crime', 'tv_match': [80]},
            99: {'name': 'Documentary', 'tv_match': [99]},
            18: {'name': 'Drama', 'tv_match': [18]},
            10751: {'name': 'Family', 'tv_match': [10751]},
            14: {'name': 'Fantasy', 'tv_match': [10765]},
            36: {'name': 'History', 'tv_match': []},
            27: {'name': 'Horror', 'tv_match': [9648]},  # Horror often falls under Mystery in TV
            10402: {'name': 'Music', 'tv_match': []},
            9648: {'name': 'Mystery', 'tv_match': [9648]},
            10749: {'name': 'Romance', 'tv_match': [10749]},
            878: {'name': 'Science Fiction', 'tv_match': [10765]},
            10770: {'name': 'TV Movie', 'tv_match': []},
            53: {'name': 'Thriller', 'tv_match': [9648]},
            10752: {'name': 'War', 'tv_match': [10768]},
            37: {'name': 'Western', 'tv_match': [37]}
        },
        'tv': {
            10759: {'name': 'Action & Adventure', 'movie_match': [28, 12]},
            16: {'name': 'Animation', 'movie_match': [16]},
            35: {'name': 'Comedy', 'movie_match': [35]},
            80: {'name': 'Crime', 'movie_match': [80]},
            99: {'name': 'Documentary', 'movie_match': [99]},
            18: {'name': 'Drama', 'movie_match': [18]},
            10751: {'name': 'Family', 'movie_match': [10751]},
            10762: {'name': 'Kids', 'movie_match': []},
            9648: {'name': 'Mystery', 'movie_match': [9648, 27, 53]},  # Includes Horror and Thriller
            10763: {'name': 'News', 'movie_match': []},
            10764: {'name': 'Reality', 'movie_match': []},
            10765: {'name': 'Sci-Fi & Fantasy', 'movie_match': [878, 14]},
            10766: {'name': 'Soap', 'movie_match': []},
            10767: {'name': 'Talk', 'movie_match': []},
            10768: {'name': 'War & Politics', 'movie_match': [10752]},
            37: {'name': 'Western', 'movie_match': [37]}
        }
    }

@app.route('/')
def index():
    genres = get_genres_dict()
    
    # Fetch movies by genre
    movie_genres_data = {}
    for genre_id, genre_info in genres['movies'].items():  # Changed to get both id and info
        genre_name = genre_info['name']  # Extract the name string
        movies = fetch_movies_by_category("popular", genre_id=genre_id)
        if movies:
            movie_genres_data[genre_name] = movies[:20]  # Now using the string name as key
    
    # Fetch TV shows by genre
    tv_genres_data = {}
    for genre_id, genre_info in genres['tv'].items():  # Same change for TV
        genre_name = genre_info['name']
        tv_shows = fetch_tv_by_category("popular", genre_id=genre_id)
        if tv_shows: 
            tv_genres_data[genre_name] = tv_shows[:20]
    
    return render_template("index.html",
                         movie_genres=movie_genres_data,
                         tv_genres=tv_genres_data,
                         img_url=TMDB_IMAGE_URL)

@app.route('/movies/<category>')
def movies_category(category):
    valid_categories = ['popular', 'now_playing', 'upcoming', 'top_rated']
    if category not in valid_categories:
        return render_template("404.html", message="Invalid category")
    
    movies = fetch_movies_by_category(category)
    return render_template("category.html",
                         title=f"{category.replace('_', ' ').title()} Movies",
                         items=movies,
                         item_type="movie",
                         img_url=TMDB_IMAGE_URL)

@app.route('/tv/<category>')
def tv_category(category):
    valid_categories = ['popular', 'airing_today', 'on_the_air', 'top_rated']
    if category not in valid_categories:
        return render_template("404.html", message="Invalid category")
    
    tv_shows = fetch_tv_by_category(category)
    return render_template("category.html",
                         title=f"{category.replace('_', ' ').title()} TV Shows",
                         items=tv_shows,
                         item_type="tv",
                         img_url=TMDB_IMAGE_URL)

@app.route("/recommend", methods=["POST"])
def recommend():
    try:
        content_type = request.form.get("content_type", "movie").strip().lower()
        name = request.form.get("movie", "").strip()
        
        if not name:
            try:
                return render_template("404.html", message="Please enter a title to search")
            except:
                return "Please enter a title to search", 400
        
        if content_type == "movie":
            searched_item, recs = get_movie_recommendations(name)
            template = "recommend_movie.html"
        elif content_type == "tv":
            searched_item, recs = get_tv_recommendations(name)
            template = "recommend_tv.html"
        else:
            try:
                return render_template("404.html", message="Invalid content type specified")
            except:
                return "Invalid content type specified", 400
        
        if not searched_item:
            try:
                return render_template("404.html", message=f"No {content_type} found with that name")
            except:
                return f"No {content_type} found with that name", 404
        
        return render_template(
            template,
            name=searched_item.get("title") if content_type == "movie" else searched_item.get("name"),
            searched_item=searched_item,
            recs=recs,
            img_url=TMDB_IMAGE_URL,
            content_type=content_type
        )
        
    except Exception as e:
        app.logger.error(f"Error in recommend route: {str(e)}")
        try:
            return render_template("404.html", message="An error occurred while processing your request")
        except:
            return "An error occurred while processing your request", 500

@app.errorhandler(404)
def page_not_found(e):
    try:
        return render_template('404.html', message=e.description), 404
    except:
        return "Page not found", 404
    
@app.route('/movie/<int:movie_id>')
def movie_detail(movie_id):
    # Get movie details and related movies
    movie_details, related_movies = get_movie_info(movie_id)
    if not movie_details:
        return render_template("404.html", message="Movie not found.")
    
    # Get trailer key
    trailer_key = get_movie_trailer(movie_id)
    
    # Get credits
    credits = get_movie_credits(movie_id)

    # Add streaming providers
    streaming_providers = get_movie_watch_providers(movie_id)
    
    # Get API-based similar movies
    api_similar_movies = get_similar_movie(movie_id)
    
    # Get ML-based recommendations
    ml_recommendations = []
    if movie_details.get('title'):
        # Try to find the movie in our dataset
        titles = movie_df["title"].tolist()
        closest_match = get_best_match(movie_details['title'], titles)
        
        if closest_match:
            index_of_movie = movie_df[movie_df.title == closest_match].index.values[0]
            similarity_scores = list(enumerate(movie_similarity[index_of_movie]))
            sorted_scores = sorted(similarity_scores, key=lambda x: x[1], reverse=True)
            
            # Get top 6 ML recommendations
            titles_seen = set()
            for i, _ in sorted_scores[1:12]:  # Get top 6 similar
                movie = movie_df.iloc[i]
                title = movie["title"]
                if title == movie_details['title'] or title in titles_seen:
                    continue
                titles_seen.add(title)
                ml_recommendations.append({
                    "id": movie["id"],
                    "title": title,
                    "poster_path": movie["poster_path"],
                    "release_date": movie.get("release_date", "")[:4] if movie.get("release_date") else "N/A"
                })

    movie_data = {
        'details': movie_details,
        'cast': credits.get('cast', []) if credits else [],
        'crew': credits.get('crew', []) if credits else [],
        'trailer_key': trailer_key,
        'related_movies': related_movies,
        'similar_movies': api_similar_movies,
        'ml_recommendations': ml_recommendations
    }
    
    return render_template("movie_detail.html", 
                         movie=movie_data,
                         streaming_providers=streaming_providers,
                         img_url=TMDB_IMAGE_URL)

@app.route('/tv/<int:tv_id>')
def tv_detail(tv_id):
    # Get TV show details
    tv_details = get_tv_info(tv_id)
    if not tv_details:
        return render_template("404.html", message="TV show not found.")
    
    # Get trailer key
    trailer_key = get_tv_trailer(tv_id)
    
    # Get credits - ensure this includes IDs
    credits = get_tv_credits(tv_id)
    
    # Get similar TV shows from API
    api_similar = get_similar_tv(tv_id)

    # Get ML-based recommendations
    ml_recommendations = []
    if tv_details.get('name'):
        # Try to find the TV show in our dataset
        title_column = "name" if "name" in tv_df.columns else "title"
        titles = tv_df[title_column].tolist()
        closest_match = get_best_match(tv_details['name'], titles)
        
        if closest_match:
            index_of_tv = tv_df[tv_df[title_column] == closest_match].index.values[0]
            similarity_scores = list(enumerate(tv_similarity[index_of_tv]))
            sorted_scores = sorted(similarity_scores, key=lambda x: x[1], reverse=True)
            
            # Get top 6 ML recommendations
            titles_seen = set()
            for i, _ in sorted_scores[1:12]:  # Get top 6 similar
                tv = tv_df.iloc[i]
                title = tv[title_column]
                if title == tv_details['name'] or title in titles_seen:
                    continue
                titles_seen.add(title)
                ml_recommendations.append({
                    "id": tv["id"],
                    "name": title,
                    "poster_path": tv["poster_path"],
                    "first_air_date": tv.get("first_air_date", "")[:4] if tv.get("first_air_date") else "N/A"
                })

    # Add streaming providers
    streaming_providers = get_tv_watch_providers(tv_id)
    
    tv_data = {
        'show': tv_details,
        'cast': [{
            'id': person.get('id'),
            'name': person.get('name'),
            'character': person.get('character'),
            'profile_path': person.get('profile_path')
        } for person in credits.get('cast', [])[:10]] if credits else [],
        'crew': [{
            'id': person.get('id'),
            'name': person.get('name'),
            'job': person.get('job'),
            'profile_path': person.get('profile_path')
        } for person in credits.get('crew', []) if person.get('job') in ['Director', 'Screenplay', 'Writer', 'Producer']],
        'trailer_key': trailer_key,
        'similar': api_similar,
        'ml_recommendations': ml_recommendations,
        'seasons': tv_details.get('seasons', [])
    }
    
    return render_template("tv_detail.html", 
                         tv=tv_data,
                         streaming_providers=streaming_providers,
                         img_url=TMDB_IMAGE_URL)

@app.route('/person/<int:person_id>')
def person_detail(person_id):
    # Fetch person details from TMDB API
    url = f"https://api.themoviedb.org/3/person/{person_id}?api_key={TMDB_API_KEY}&append_to_response=combined_credits,images"
    response = requests.get(url)
    
    if response.status_code != 200:
        return render_template("404.html", message="Person not found")
    
    person_data = response.json()
    
    # Get known for works (top 4 most popular)
    known_for = sorted(
        person_data.get('combined_credits', {}).get('cast', []),
        key=lambda x: x.get('popularity', 0),
        reverse=True
    )[:4]
    
    return render_template(
        "person_detail.html",
        cast={
            **person_data,
            "known_for": known_for,
            "combined_credits": person_data.get('combined_credits', {})
        },
        img_url=TMDB_IMAGE_URL
    )

def calculate_age(birthdate):
    """Calculate age from birthdate string (YYYY-MM-DD)"""
    if not birthdate:
        return None
    today = datetime.today()
    born = datetime.strptime(birthdate, "%Y-%m-%d")
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))

app.jinja_env.globals.update(calculate_age=calculate_age)

def get_credit_year(credit):
    if 'release_date' in credit and credit['release_date']:
        return credit['release_date'][:4]
    elif 'first_air_date' in credit and credit['first_air_date']:
        return credit['first_air_date'][:4]
    return '0000'

app.jinja_env.filters['get_credit_year'] = get_credit_year

@app.route('/genre/<content_type>/<int:genre_id>')
def genre_content(content_type, genre_id):
    genres_dict = get_genres_dict()
    
    # Get the genre info
    if content_type == 'movie':
        genre_info = genres_dict['movies'].get(genre_id)
        genre_name = genre_info['name'] if genre_info else None
        tv_genre_ids = genre_info['tv_match'] if genre_info else []
    elif content_type == 'tv':
        genre_info = genres_dict['tv'].get(genre_id)
        genre_name = genre_info['name'] if genre_info else None
        movie_genre_ids = genre_info['movie_match'] if genre_info else []
    else:
        return render_template("404.html", message="Invalid content type")
    
    if not genre_name:
        return render_template("404.html", message="Genre not found")
    
    # Fetch content
    movies = []
    tv_shows = []
    
    if content_type == 'movie':
        # Get movies from this genre
        movies = fetch_movies_by_category("popular", genre_id=genre_id)
        
        # Get TV shows from matching genres
        for tv_genre_id in tv_genre_ids:
            shows = fetch_tv_by_category("popular", genre_id=tv_genre_id)
            tv_shows.extend(shows)
            
        # If still no TV shows, try to find similar genres
        if not tv_shows:
            similar_tv_genres = [gid for gid, info in genres_dict['tv'].items() 
                               if genre_name.lower() in info['name'].lower()]
            for tv_genre_id in similar_tv_genres:
                shows = fetch_tv_by_category("popular", genre_id=tv_genre_id)
                tv_shows.extend(shows)
                
    else:  # content_type == 'tv'
        # Get TV shows from this genre
        tv_shows = fetch_tv_by_category("popular", genre_id=genre_id)
        
        # Get movies from matching genres
        for movie_genre_id in movie_genre_ids:
            films = fetch_movies_by_category("popular", genre_id=movie_genre_id)
            movies.extend(films)
            
        # If still no movies, try to find similar genres
        if not movies:
            similar_movie_genres = [gid for gid, info in genres_dict['movies'].items() 
                                   if genre_name.lower() in info['name'].lower()]
            for movie_genre_id in similar_movie_genres:
                films = fetch_movies_by_category("popular", genre_id=movie_genre_id)
                movies.extend(films)
    
    # Remove duplicates
    movies = list({v['id']:v for v in movies}.values())
    tv_shows = list({v['id']:v for v in tv_shows}.values())
    
    return render_template("genre.html",
                         genre_name=genre_name,
                         movies=movies[:20],
                         tv_shows=tv_shows[:20],
                         img_url=TMDB_IMAGE_URL)

@lru_cache(maxsize=128)
def get_movie_watch_providers(movie_id, region='IN'):
    url = f"https://api.themoviedb.org/3/movie/{movie_id}/watch/providers"
    headers = {"Authorization": f"Bearer {TMDB_API_KEY}"}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if not data.get('results'):
            return None
            
        # Check India first
        in_providers = data['results'].get('IN', {})
        
        # If no IN results, try these fallback regions in order
        fallback_regions = ['US', 'GB', 'AU', 'CA'] if region == 'IN' else [region]
        
        providers = None
        for reg in [region] + fallback_regions:
            if reg in data['results']:
                providers = data['results'][reg]
                if any(providers.get(k) for k in ['flatrate', 'buy', 'rent']):
                    return {
                        "link": f"https://www.themoviedb.org/movie/{movie_id}/watch",
                        "region": reg,
                        "flatrate": providers.get('flatrate', []),
                        "buy": providers.get('buy', []),
                        "rent": providers.get('rent', [])
                    }
        return None
        
    except Exception as e:
        print(f"Error fetching providers: {e}")
        return None
    

@app.route('/movie/<int:movie_id>/refresh_providers')
def refresh_providers(movie_id):
    region = request.args.get('region', 'US')
    # Clear the cache for this movie
    get_movie_watch_providers.cache_clear()
    # Get fresh data with new region
    providers = get_movie_watch_providers(movie_id, region=region)
    return jsonify({
        'success': True,
        'region': region,
        'has_providers': providers is not None
    })

def get_tv_watch_providers(tv_id):
    """
    Get streaming providers for a TV show
    Returns same structure as get_movie_watch_providers
    """
    url = f"https://api.themoviedb.org/3/tv/{tv_id}/watch/providers"
    headers = {
        "Authorization": f"Bearer {TMDB_API_KEY}",
        "accept": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if 'results' in data and 'US' in data['results']:
            us_providers = data['results']['US']
            providers_data = {
                "link": f"https://www.themoviedb.org/tv/{tv_id}/watch"
            }
            
            if 'flatrate' in us_providers:
                providers_data['flatrate'] = [
                    {
                        "provider_name": p['provider_name'],
                        "provider_id": p['provider_id']
                    } for p in us_providers['flatrate']
                ]
            
            if 'buy' in us_providers:
                providers_data['buy'] = [
                    {
                        "provider_name": p['provider_name'],
                        "provider_id": p['provider_id']
                    } for p in us_providers['buy']
                ]
            
            return providers_data if any(k in providers_data for k in ['flatrate', 'buy']) else None
            
    except requests.exceptions.RequestException as e:
        print(f"Error fetching TV watch providers: {e}")
        return None
    
class User(UserMixin):
    def __init__(self, id_, name, email, profile_pic):
        self.id = id_
        self.name = name
        self.email = email
        self.profile_pic = profile_pic

@login_manager.user_loader
def load_user(user_id):
    # Here you would typically query your database for the user
    return User.get(user_id)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='Invalid email or password')
    
    return render_template('login.html')

# For Google OAuth login
@app.route('/login/google')
def login_google():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    google_provider_cfg = requests.get(GOOGLE_DISCOVERY_URL).json()
    authorization_endpoint = google_provider_cfg["authorization_endpoint"]
    
    request_uri = client.prepare_request_uri(
        authorization_endpoint,
        redirect_uri=url_for('auth_callback', _external=True),
        scope=["openid", "email", "profile"],
    )
    return redirect(request_uri)

# Google callback
@app.route('/login/google/callback')
def auth_callback():
    print("Callback route accessed")  # Debug print
    print("Request args:", request.args)  # Debug print
    # Get authorization code
    code = request.args.get("code")
    
    if not code:
        return render_template("404.html", message="Authorization code not received"), 400
    
    try:
        # Get token endpoint
        google_provider_cfg = requests.get(GOOGLE_DISCOVERY_URL).json()
        token_endpoint = google_provider_cfg["token_endpoint"]
        
        # Prepare token request
        token_url, headers, body = client.prepare_token_request(
            token_endpoint,
            authorization_response=request.url,
            redirect_url=request.base_url,
            code=code
        )
        token_response = requests.post(
            token_url,
            headers=headers,
            data=body,
            auth=(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET),
        )
        
        # Parse tokens
        client.parse_request_body_response(token_response.text)
        
        # Get userinfo
        userinfo_endpoint = google_provider_cfg["userinfo_endpoint"]
        uri, headers, body = client.add_token(userinfo_endpoint)
        userinfo_response = requests.get(uri, headers=headers, data=body)
        
        if userinfo_response.status_code != 200:
            return render_template("404.html", message="Failed to fetch user info"), 400
        
        userinfo = userinfo_response.json()
        
        if not userinfo.get("email_verified"):
            return render_template("404.html", message="Email not verified by Google"), 400
        
        # Create user object
        unique_id = userinfo["sub"]
        users_email = userinfo["email"]
        users_name = userinfo.get("given_name", users_email.split('@')[0])
        users_picture = userinfo.get("picture", "https://via.placeholder.com/150")
        
        # Store user data in session (in a real app, store in database)
        user_data = {
            'id': unique_id,
            'name': users_name,
            'email': users_email,
            'profile_pic': users_picture
        }
        session['user_data'] = user_data
        
        # Create user and log in
        user = User(
            id_=unique_id,
            name=users_name,
            email=users_email,
            profile_pic=users_picture
        )

        # Check if user exists, if not create them
        user = User.get(unique_id)
        if not user:
            user = User.create(
                id_=unique_id,
                name=users_name,
                email=users_email,
                profile_pic=users_picture
            )
    
        login_user(user)
        
        # Redirect to home
        return redirect(url_for("index"))
    
    except Exception as e:
        app.logger.error(f"Error in callback route: {str(e)}")
        return render_template("404.html", message="Authentication failed"), 500

@app.route("/logout")
@login_required
def logout():
    logout_user()
    session.pop('user_data', None)
    return redirect(url_for("index"))

class User(UserMixin, db.Model):
    __tablename__ = 'user'  # Explicit table name
    
    id = db.Column(db.String(100), primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    profile_pic = db.Column(db.String(200))
    password_hash = db.Column(db.String(128))  # Make sure this line exists
    # join_date = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __init__(self, id_, name, email, profile_pic):
        self.id = id_
        self.name = name
        self.email = email
        self.profile_pic = profile_pic
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    @staticmethod
    def get(user_id):
        return User.query.get(user_id)
    
    @staticmethod
    def create(id_, name, email, profile_pic, password=None):
        user = User(id_=id_, name=name, email=email, profile_pic=profile_pic)
        if password:
            user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user

# Create tables
with app.app_context():
    db.create_all()


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        # Handle form submission
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Basic validation
        if not name or not email or not password:
            return render_template('signup.html', error='All fields are required')
        if password != confirm_password:
            return render_template('signup.html', error='Passwords do not match')
        
        # Check if user exists (you'll need to implement this)
        if User.query.filter_by(email=email).first():
            return render_template('signup.html', error='Email already registered')
        
        # Create user (you'll need to add password hashing)
        user = User(
            id_=str(uuid.uuid4()),  # Generate a unique ID
            name=name,
            email=email,
            profile_pic='https://via.placeholder.com/150'  # Default profile picture
        )
        user.set_password(password)  # You'll need to add this method to User class
        db.session.add(user)
        db.session.commit()
        
        login_user(user)
        return redirect(url_for('index'))
    
    return render_template('signup.html')

@app.route('/profile')
@login_required  # Ensures only logged-in users can access
def profile():
    # Get the current user's data
    user_data = {
        'name': current_user.name,
        'email': current_user.email,
        'profile_pic': current_user.profile_pic or 'https://via.placeholder.com/150',
        # 'join_date': getattr(current_user, 'join_date', "N/A")
    }
    return render_template('profile.html', user=user_data)

class WatchlistItem(db.Model):
    __tablename__ = 'watchlist_items'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(100), db.ForeignKey('user.id'), nullable=False)
    item_id = db.Column(db.Integer, nullable=False)
    item_type = db.Column(db.String(10), nullable=False)  # 'movie' or 'tv'
    title = db.Column(db.String(200), nullable=False)
    poster_path = db.Column(db.String(200))
    added_on = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('watchlist', lazy=True))

@app.route('/add_to_watchlist', methods=['POST'])
@login_required
def add_to_watchlist():
    if not current_user.is_authenticated:
        return jsonify({'success': False, 'message': 'Please log in first'}), 401
    
    data = request.get_json()
    
    # Check if item already exists in watchlist
    existing = WatchlistItem.query.filter_by(
        user_id=current_user.id,
        item_id=data['item_id'],
        item_type=data['item_type']
    ).first()
    
    if existing:
        return jsonify({'success': False, 'message': 'Already in your watchlist'})
    
    # Add new item
    new_item = WatchlistItem(
        user_id=current_user.id,
        item_id=data['item_id'],
        item_type=data['item_type'],
        title=data['title'],
        poster_path=data['poster_path']
    )
    
    db.session.add(new_item)
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/watchlist')
@login_required
def watchlist():
    items = WatchlistItem.query.filter_by(user_id=current_user.id).order_by(WatchlistItem.added_on.desc()).all()
    return render_template('watchlist.html', items=items, img_url=TMDB_IMAGE_URL)

if __name__ == '__main__':
    app.run(debug=True)