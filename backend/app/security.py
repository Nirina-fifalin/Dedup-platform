from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from .config import ACCESS_TOKEN_MINUTES, JWT_ALGORITHM, JWT_SECRET

_hasher = PasswordHasher()
# Hash factice : on fait le même travail quand l'email n'existe pas, pour ne pas
# révéler par le temps de réponse quels comptes existent.
_DUMMY_HASH = _hasher.hash("mot-de-passe-factice")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


def verify_dummy(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=ACCESS_TOKEN_MINUTES)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> int | None:
    try:
        payload = jwt.decode(
            token, JWT_SECRET, algorithms=[JWT_ALGORITHM], options={"require": ["exp", "sub"]}
        )
        return int(payload["sub"])
    except (jwt.PyJWTError, ValueError):
        return None