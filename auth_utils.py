from datetime import datetime, timedelta
from typing import Optional, Dict
from jose import JWTError, jwt # Prefer python-jose for JWT operations
from google.oauth2 import id_token
from google.auth.transport import requests
from config import settings # Import settings

# Note: CryptContext is useful if you also manage local email/password users.
# If not, you might not strictly need it for Google Auth only.
# from passlib.context import CryptContext
# pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_access_token(data: Dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Creates a new application-specific JWT access token.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    # Use settings.JWT_SECRET_KEY and settings.ALGORITHM
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

async def verify_google_id_token(token: str) -> Optional[Dict]:
    """
    Verifies a Google ID token and returns the user's information.
    Uses the GOOGLE_CLIENT_ID from settings.
    """
    try:
        # Specify the CLIENT_ID of the app that accesses the backend
        # This is the Web client ID from your Firebase/Google Cloud Console
        idinfo = id_token.verify_oauth2_token(token, requests.Request(), settings.GOOGLE_CLIENT_ID)

        # ID token is valid. Get the user's Google Account ID, email, etc.
        # 'sub' is the unique user ID from Google
        # 'email' is the user's email address
        # 'name' is the user's full name
        # 'picture' is the URL of the user's profile picture
        return {
            "google_id": idinfo['sub'],
            "email": idinfo['email'],
            "name": idinfo.get('name'),
            "picture": idinfo.get('picture')
        }
    except ValueError as e:
        # Invalid token (e.g., tampered, expired, wrong client ID)
        print(f"Google ID token verification failed (ValueError): {e}")
        return None
    except Exception as e:
        # Catch any other unexpected errors during verification
        print(f"An unexpected error occurred during Google ID token verification: {e}")
        return None

