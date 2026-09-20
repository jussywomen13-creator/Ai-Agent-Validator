"""Initialize the SQLite database (run once via setup.ps1)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db

db.init_db()
print("Database ready:", db.DB_PATH)
