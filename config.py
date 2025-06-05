from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    Using pydantic_settings for robust configuration management.
    """
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    # MongoDB Settings
    MONGO_DB_URL: str
    MONGO_DB_NAME: str

    # ERPNext Settings
    ERP_API_URL: str = "https://erp.kisanmitra.net/api/resource/Issue" # Default, can be overridden
    ERP_SID: str

    # Google Auth Settings
    GOOGLE_CLIENT_ID: str

    # JWT Settings for your application's tokens
    JWT_SECRET_KEY: str
    ALGORITHM: str = "HS256" # Default algorithm
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30 # Default token expiration

    # Optional: GitHub PAT (if ERPNext uses GitHub integration, ensure it's secure)
    GITHUB_PAT: Optional[str] = None

settings = Settings()

