from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from typing import List, Optional
from jose import JWTError, jwt

from config import settings
from database import get_database
from auth_utils import create_access_token, verify_google_id_token

# Create an API Router for authentication-related endpoints
router = APIRouter(prefix="/auth", tags=["Authentication"])

# Pydantic models for request/response bodies for Google Auth
class GoogleSignInRequest(BaseModel):
    id_token: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str # Include user ID for frontend

class UserInDB(BaseModel):
    # This model needs ObjectId handling if it's directly from MongoDB
    id: Optional[str] = None # MongoDB _id will be ObjectId, convert to str for Pydantic
    google_id: str
    email: EmailStr
    name: Optional[str] = None
    picture: Optional[str] = None
    created_at: datetime = datetime.utcnow()
    last_login_at: datetime = datetime.utcnow()

    class Config:
        arbitrary_types_allowed = True
        # json_encoders = {ObjectId: str} # ObjectId import is not needed here
        populate_by_name = True

# OAuth2PasswordBearer for token authentication (used for protected routes)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

@router.post("/google-signin", response_model=Token, summary="Authenticate with Google ID Token")
async def google_signin(request: GoogleSignInRequest):
    """
    Handles Google Sign-In by verifying the ID token,
    creating/updating the user in MongoDB, and issuing an application JWT.
    """
    db = get_database()
    users_collection = db["users"] # Assuming you have a 'users' collection for your users

    # 1. Verify Google ID Token
    google_user_info = await verify_google_id_token(request.id_token)
    if not google_user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google ID token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    google_id = google_user_info["google_id"]
    email = google_user_info["email"]
    name = google_user_info.get("name")
    picture = google_user_info.get("picture")

    # 2. Check User in Database (MongoDB)
    # Using 'get_database()' and then accessing collection
    existing_user = await users_collection.find_one({"google_id": google_id})

    if existing_user:
        # 3. Update existing user's info and last login time
        # Need ObjectId for MongoDB query, import from bson if not already
        from bson import ObjectId # Import ObjectId here as needed for DB interaction
        await users_collection.update_one(
            {"_id": existing_user["_id"]},
            {"$set": {
                "name": name,
                "picture": picture,
                "last_login_at": datetime.utcnow()
            }}
        )
        user_id_str = str(existing_user["_id"])
        print(f"User {email} updated. User ID: {user_id_str}") # Use print or proper logger here
    else:
        # 3. Create new user record in MongoDB
        new_user = {
            "google_id": google_id,
            "email": email,
            "name": name,
            "picture": picture,
            "created_at": datetime.utcnow(),
            "last_login_at": datetime.utcnow()
        }
        # Need ObjectId for MongoDB, result.inserted_id is ObjectId
        result = await users_collection.insert_one(new_user)
        user_id_str = str(result.inserted_id)
        print(f"New user {email} created. User ID: {user_id_str}") # Use print or proper logger here

    # 4. Generate Application-Specific JWT
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user_id_str}, # 'sub' claim typically holds the user ID
        expires_delta=access_token_expires
    )

    # 5. Send JWT back to Frontend
    return {"access_token": access_token, "token_type": "bearer", "user_id": user_id_str}

async def get_current_user(token: str = Depends(oauth2_scheme)) -> UserInDB:
    """
    Dependency to get the current authenticated user from the JWT token.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials")

        db = get_database()
        users_collection = db["users"]
        from bson import ObjectId # Import ObjectId here
        user_data = await users_collection.find_one({"_id": ObjectId(user_id)})
        if not user_data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        user_data["id"] = str(user_data["_id"])
        return UserInDB(**user_data)

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

@router.get("/users/me", response_model=UserInDB, summary="Get current user information (Protected)")
async def read_users_me(current_user: UserInDB = Depends(get_current_user)):
    """
    Retrieves information about the current authenticated user.
    This route requires your application's JWT.
    """
    return current_user
