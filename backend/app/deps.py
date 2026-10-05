from collections.abc import Callable, Iterator

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import User
from .security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def get_current_user(
    token: str = Depends(oauth2_scheme), session: Session = Depends(get_session)
) -> User:
    user_id = decode_access_token(token)
    user = session.get(User, user_id) if user_id is not None else None
    if user is None or not user.is_active:
        raise HTTPException(401, "Non authentifié", headers={"WWW-Authenticate": "Bearer"})
    return user


def require_role(*roles: str) -> Callable[..., User]:
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "Droits insuffisants")
        return user

    return checker