import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

DATABASE_URL = os.environ["DATABASE_URL"]

JWT_SECRET = os.environ["JWT_SECRET"]
if len(JWT_SECRET) < 32:
    raise RuntimeError("JWT_SECRET doit contenir au moins 32 caractères (voir .env.example)")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "60"))