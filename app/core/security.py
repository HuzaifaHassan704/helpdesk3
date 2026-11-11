from datetime import UTC, datetime, timedelta

import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=settings.BCRYPT_ROUNDS)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(subject: int | str, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {"sub": str(subject), "exp": expire, "iat": datetime.now(UTC)}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError on invalid/expired tokens."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
