from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import settings

# bcrypt only looks at the first 72 bytes of a password. Longer ones are rejected up front (schemas/user.py)
# instead of being silently truncated, which would make "A"*72 + anything log in with the same hash.
MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    raw = password.encode()
    if len(raw) > MAX_PASSWORD_BYTES:
        raise ValueError(f"password longer than {MAX_PASSWORD_BYTES} bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    raw = plain.encode()
    if len(raw) > MAX_PASSWORD_BYTES:
        return False  # can never match: such a password cannot have been set
    try:
        return bcrypt.checkpw(raw, hashed.encode())
    except ValueError:  # malformed stored hash
        return False


def create_access_token(subject: int | str, expires_delta: timedelta | None = None, token_version: int = 0) -> str:
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {"sub": str(subject), "exp": expire, "iat": datetime.now(UTC), "tv": token_version}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError on invalid/expired tokens."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
