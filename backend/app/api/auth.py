from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_session
from ..models import User
from ..schemas import TokenOut, UserOut
from ..security import create_access_token, verify_dummy, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _invalid() -> HTTPException:
    # Même message pour « compte inconnu », « mauvais mot de passe » et « compte désactivé »
    return HTTPException(401, "Identifiants invalides", headers={"WWW-Authenticate": "Bearer"})


@router.post("/login", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_session)):
    user = session.scalar(select(User).where(User.email == form.username.strip().lower()))
    if user is None:
        verify_dummy(form.password)
        raise _invalid()
    if not verify_password(form.password, user.password_hash) or not user.is_active:
        raise _invalid()
    return TokenOut(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut(id=user.id, email=user.email, role=user.role)