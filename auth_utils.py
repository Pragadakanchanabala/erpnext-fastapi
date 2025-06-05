from datetime import datetime, timedelta
from typing import Optional, Dict
from jose import JWTError, jwt
from google.oauth2 import id_token
from google.auth.transport import requests
from config import settings

def create_access_token(data: Dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Creates a new JWT access token.
    Args:
        data (Dict): The payload to encode into the token.
        expires_delta (Optional[timedelta]): Optional timedelta for token expiration.
    Returns:
        str: The encoded JWT token.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

async def verify_google_id_token(token: str) -> Optional[Dict]:
    """
    Verifies a Google ID token and returns the user's information.
    Args:
        token (str): The Google ID token string.
    Returns:
        Optional[Dict]: A dictionary containing user info (google_id, email, name, picture)
                        if verification is successful, otherwise None.
    """
    try:
        idinfo = id_token.verify_oauth2_token(token, requests.Request(), settings.GOOGLE_CLIENT_ID)
        return {
            "google_id": idinfo['sub'],
            "email": idinfo['email'],
            "name": idinfo.get('name'),
            "picture": idinfo.get('picture')
        }
    except ValueError as e:
        print(f"Google ID token verification failed (ValueError): {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during Google ID token verification: {e}")
        return None
