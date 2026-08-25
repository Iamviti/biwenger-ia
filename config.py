from pathlib import Path

from dotenv import load_dotenv
import os

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "biwenger.db"
SCHEMA_PATH = BASE_DIR / "db" / "schema.sql"

BIWENGER_TOKEN = os.getenv("BIWENGER_TOKEN")
BIWENGER_LEAGUE_ID = os.getenv("BIWENGER_LEAGUE_ID")
BIWENGER_USER_ID = os.getenv("BIWENGER_USER_ID")

# Único email de Google autorizado a entrar en la app cuando está desplegada (ver st.login
# en app/streamlit_app.py). Si no está definida, no se exige login (uso local normal).
ALLOWED_EMAIL = os.getenv("ALLOWED_EMAIL")
