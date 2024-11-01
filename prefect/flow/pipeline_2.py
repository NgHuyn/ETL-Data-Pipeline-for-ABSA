from prefect import task, flow
from movie_crawling.crawl_reviews import MovieReviewScraper
from movie_crawling.crawl_movies import MoviesScraper
from movie_crawling.fetch_data import fetch_and_save_movie_data
from movie_crawling.tmdb_api import TMDBApi
import pymongo
import os
from datetime import datetime, timedelta
import logging
from dotenv import load_dotenv


logging.basicConfig(level=logging.INFO)

def configure():
    """Load environment variables."""
    load_dotenv()

# Task to fetch reviews and load movies in a week
@task(retries=2)
def extract_and_load_recent_movies(batch_size=10):
    release_date_from = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    release_date_to = datetime.now().strftime('%Y-%m-%d')
    fetch_and_save_movie_data(release_date_from, release_date_to, batch_size)

# Task to check the existence of the top popular movies collection
@task
def check_top_popular_movies(db):
    collection_name = 'top_popular_movies'
    if collection_name not in db.list_collection_names():
        return None  # Collection does not exist
    return list(db[collection_name].find().limit(10))

@task
def get_top_10_movies():
    release_date_from = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    release_date_to = datetime.now().strftime('%Y-%m-%d')
    # current popular movies
    popular_movies = MoviesScraper(release_date_from=release_date_from, release_date_to=release_date_to).fetch_movies(limit=50)
    return popular_movies

def update_db(db, imdb_id, type_update, new_reviews, total_reviews=0, last_date_review=None):
    if type_update == 'update_db_reviews':
        db['movie_reviews'].update_one(
        {'Movie ID': imdb_id},
        {
            # '$addToSet': {'Reviews': {'$each': new_reviews['Reviews']}, '$position': 0},
            '$addToSet': {'Reviews': {'$each': new_reviews['Reviews']}}

        },
        upsert=True
    )
    elif type_update == 'update_db_top_popular': 
        print(f"Added {len(new_reviews['Reviews'])} new reviews for {imdb_id}.")
        db['top_popular_movies'].update_one(
            {'imdb_id': imdb_id},
            {
                '$set': {
                    'total_reviews': total_reviews,
                    'last_date_review': last_date_review
                }
            }
        )
    elif type_update == 'insert_db_top_popular':
        db['top_popular_movies'].insert_one({
                    'imdb_id': imdb_id,
                    'total_reviews': total_reviews,
                    'last_date_review': last_date_review,
        })
        logging.info(f"Inserted new movie info for ID: {imdb_id}.")


@task
def update_movie_reviews(db):
    tmdb_api_key = os.getenv('TMDB_API_KEY')
    tmdb_api = TMDBApi(api_key=tmdb_api_key)

    # get new top 10
    popular_movies = get_top_10_movies()
    # check if db top popular exists
    existing_movies = check_top_popular_movies(db)
    
    # Case 1: if the collection exists
    if existing_movies:
        logging.info("Updating reviews for existing popular movies.")
        
        existing_movies = db['top_popular_movies'].find({}, {'imdb_id': 1})

        existing_imdb_ids = {movie['imdb_id'] for movie in existing_movies}
        popular_imdb_ids = {movie['Movie ID'] for movie in popular_movies}

        # update reviews for older top 10 popular before updating new top 10
        for movie in existing_movies:
            # Fetch `last_date_review` and `total_reviews` from database
            try:
                db_movie = db['top_popular_movies'].find_one({'imdb_id': imdb_id}, {'total_reviews': 1, 'last_date_review': 1})
                
                last_date_review = db_movie.get('last_date_review')
                initial_reviews = db_movie.get('total_reviews')

                fetch_reviews = MovieReviewScraper(movie_id=imdb_id, total_reviews=initial_reviews, last_date_review=last_date_review)
                new_reviews = fetch_reviews.fetch_reviews()

                if new_reviews is not None and len(new_reviews['Reviews']) > 0:
                    # Update the reviews for the db movie_reviews
                    update_db(db, imdb_id, 'update_db_reviews', new_reviews)

                    # Update db top_popular_movies
                    update_db(db, imdb_id, 'update_db_top_popular', new_reviews, fetch_reviews.total_reviews, fetch_reviews.last_date_review)
                    
                    logging.info(f"Updated top_popular_movies for {imdb_id}.")
                else:
                    logging.info(f"No new reviews for {imdb_id}.")
            except Exception as e:
                logging.error(f"Error fetching reviews for movie ID {imdb_id}: {e}")
        count_movie = 0

        # Fetch reviews for new top 10 movies
        for movie in popular_movies:
            imdb_id = movie['Movie ID']

            # Check if imdb_id exists in the database
            tmdb_id = tmdb_api.find_tmdb_id_by_imdb_id(imdb_id)
            if not tmdb_id:
                logging.warning(f"TMDB ID not found for IMDB ID {imdb_id}. Skipping.")
                continue

            # If we have enough movies, stop
            if count_movie >= 10:
                break

            logging.info(f"Fetching new reviews for movie ID: {imdb_id}")
            
            try:
                fetch_reviews = MovieReviewScraper(movie_id=imdb_id, total_reviews=0, last_date_review=None)
                new_reviews = fetch_reviews.fetch_reviews()

                if new_reviews and len(new_reviews['Reviews']) > 0:
                    # Update the reviews for the db movie_reviews
                    update_db(db, imdb_id, 'update_db_reviews', new_reviews)
                    
                    # Update db top_popular_movies
                    update_db(db, imdb_id, 'update_db_top_popular', new_reviews, fetch_reviews.total_reviews, fetch_reviews.last_date_review)

                    logging.info(f"Updated top_popular_movies for {imdb_id}.")
                else:
                    # Update db top_popular_movies
                    if fetch_reviews.total_reviews != 0:
                        update_db(db, imdb_id, 'update_db_top_popular', new_reviews, fetch_reviews.total_reviews, fetch_reviews.last_date_review)
                    else:
                        update_db(db, imdb_id, 'update_db_top_popular', new_reviews)

                    logging.info(f"No new reviews for {imdb_id}.")

                count_movie += 1
            except Exception as e:
                logging.error(f"Error fetching reviews for movie ID {imdb_id}: {e}")

        # Remove outdated movies from db_top_popular
        popular_imdb_ids = {movie['Movie ID'] for movie in popular_movies}
        for existing_id in existing_imdb_ids:
            if existing_id not in popular_imdb_ids:
                db['top_popular_movies'].delete_one({'imdb_id': existing_id})
                logging.info(f"Removed movie with imdb_id: {existing_id} from top_popular_movies.")

    # Case 2: Collection does not exist
    else:
        logging.info("No existing popular movies found. Fetching new top 10 popular movies.")
        for movie in popular_movies:
            imdb_id = movie['Movie ID']
            
            logging.info(f"Fetching reviews for new movie ID: {imdb_id}")
            try:
                fetch_reviews = MovieReviewScraper(movie_id=imdb_id)
                new_reviews = fetch_reviews.fetch_reviews()

                # Insert to db top_popular_movies
                update_db(db, imdb_id, 'insert_db_top_popular', new_reviews, fetch_reviews.total_reviews, fetch_reviews.last_date_review)
            except Exception as e:
                logging.error(f"Error fetching reviews for movie ID {imdb_id}: {e}")

@flow(name="Movie-ETL-History", log_prints=True)
def movie_etl_flow():
    configure()

    # Database configuration
    mongo_uri = os.getenv('MONGO_URI')
    client = pymongo.MongoClient(mongo_uri)
    db_name = os.getenv('MONGODB_DATABASE', 'default_db_name').replace(' ', '_')
    db = client[db_name]

    # Step 1: cập nhật phim mỗi tuần
    extract_and_load_recent_movies()

    # step 2: update new review of top popular movies 
    update_movie_reviews(db)

# Execute the flow
if __name__ == "__main__":
    movie_etl_flow()
