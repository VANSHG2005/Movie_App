# 🎬 TMDB Movie & TV Recommendation App

A Flask-based web application that uses **The Movie Database (TMDB) API**, pre-trained **machine learning similarity models**, and fuzzy matching to provide:

- Movie & TV show search
- Personalized recommendations (ML + API)
- Genre-based browsing
- Cast & crew details
- Streaming provider info
- Trailers and similar titles

---

## 🚀 Features

- **Search Recommendations**  
  - Find the closest matching title using `rapidfuzz`.
  - Hybrid recommendations:  
    - **API-based** (similar titles from TMDB)  
    - **ML-based** (cosine similarity on precomputed embeddings).

- **Browse by Categories**  
  - Movies: `popular`, `now_playing`, `upcoming`, `top_rated`  
  - TV Shows: `popular`, `airing_today`, `on_the_air`, `top_rated`

- **Genre-based Content Matching**  
  - Intelligent cross-linking between related movie and TV genres.

- **Detailed Pages**  
  - Overview, genres, cast & crew (top 10), seasons (for TV), related titles, ML recommendations.
  - Trailers from YouTube.
  - Streaming providers (region-aware).

- **People Pages**  
  - Biography, known-for works, combined credits.

---

## 🛠️ Tech Stack

- **Backend**: Flask
- **Data Processing**: pandas, joblib, rapidfuzz
- **Machine Learning**: Precomputed similarity matrices
- **API Integration**: TMDB API
- **Environment Variables**: python-dotenv
- **Frontend**: HTML templates (Jinja2), Bootstrap/Tailwind (optional styling)
- **Caching**: `functools.lru_cache` for providers

---

## 📂 Project Structure

project/
│
├── model/
│ ├── tmdb_movies.pkl # Preprocessed movie dataframe
│ ├── tmdb_similarity.pkl # Movie similarity matrix
│ ├── tmdb_tv_series.pkl # Preprocessed TV dataframe
│ ├── tmdb_tv_similarity.pkl # TV similarity matrix
│
├── templates/
│ ├── index.html
│ ├── recommend_movie.html
│ ├── recommend_tv.html
│ ├── movie_detail.html
│ ├── tv_detail.html
│ ├── person_detail.html
│ ├── genre.html
│ ├── category.html
│ ├── 404.html
│
├── static/
│ ├── css/
│ ├── js/
│ ├── images/
│
├── app.py
├── requirements.txt
├── .env
└── README.md

---

## 🔑 Environment Variables

Create a `.env` file in the project root:

## TMDB_API_KEY=your_tmdb_api_key_here

You can get your API key from [The Movie Database API](https://www.themoviedb.org/settings/api).

---

## 📦 Installation

### 1️⃣ Clone the repository
```bash
git clone https://github.com/yourusername/tmdb-recommendation-app.git
cd tmdb-recommendation-app

2️⃣ Create a virtual environment

python -m venv venv
source venv/bin/activate   # Mac/Linux
venv\Scripts\activate      # Windows

3️⃣ Install dependencies
pip install -r requirements.txt

4️⃣ Prepare models
Ensure you have the .pkl model files in the model/ folder.

▶️ Run the App
python app.py
Open your browser and visit: http://127.0.0.1:5000/



🧠 How Recommendations Work
Search Matching
- Uses rapidfuzz.process.extractOne to match user input to closest title.

ML Recommendations
- Finds index in precomputed similarity matrix.
- Sorts scores & returns top matches excluding duplicates.

API Recommendations
- Calls TMDB /similar endpoint for real-time recommendations.


📝 Requirements

Flask
requests
python-dotenv
joblib
rapidfuzz
pandas

⚠️ Notes
- Make sure your TMDB API key has read access enabled.
- Precomputed .pkl files are required for ML-based recommendations.
- API rate limits apply — use caching for performance.
