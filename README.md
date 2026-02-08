# Activate virtual environment
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Make sure PostgreSQL is running, then run migrations
# (init_db() auto-creates tables on startup)

# Run the backend
uvicorn main:app --reload --port 8000

# Reload Backend
uvicorn main:app --reload