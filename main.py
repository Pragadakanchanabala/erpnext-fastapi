from fastapi import FastAPI, HTTPException, Depends, status, APIRouter
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from typing import List, Optional
import httpx
import os
from dotenv import load_dotenv
from bson import ObjectId
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging
from httpx import RequestError
from jose import JWTError, jwt # Import jwt from jose for decoding tokens

# Import utilities and configurations
from config import settings
from database import connect_to_mongo, close_mongo_connection, get_database, get_issues_collection
from auth_utils import create_access_token, verify_google_id_token
from models.issue import IssueEntry # Assuming models/issue.py defines IssueEntry

# Load environment variables (done via pydantic_settings in config.py, but keep for other `os.getenv` if any)
load_dotenv()

# FastAPI app
app = FastAPI(title="ERPNext FastAPI Bridge")

# Logger setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# APScheduler
scheduler = AsyncIOScheduler()

# Initialize issues_collection globally (will be set in startup event)
issues_collection = None

# OAuth2PasswordBearer for token authentication
# tokenUrl should point to your backend's token generation endpoint, e.g., for local login or a generic token route.
# For Google Sign-In, the frontend will send the Google ID token to /auth/google-signin,
# and then use the returned JWT for other protected routes.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Pydantic models for request/response bodies for Google Auth
class GoogleSignInRequest(BaseModel):
    id_token: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str # Include user ID for frontend

class UserInDB(BaseModel):
    """
    Pydantic model for user data as stored in MongoDB.
    Includes special handling for MongoDB's ObjectId.
    """
    id: Optional[str] = None # MongoDB _id will be ObjectId, convert to str for Pydantic
    google_id: str
    email: EmailStr
    name: Optional[str] = None
    picture: Optional[str] = None
    created_at: datetime = datetime.utcnow()
    last_login_at: datetime = datetime.utcnow()

    # Pydantic configuration to allow conversion from MongoDB ObjectId
    class Config:
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
        # Allow population by field name or alias for MongoDB compatibility
        populate_by_name = True


# --- API Endpoints ---

@app.post("/auth/google-signin", response_model=Token, summary="Authenticate with Google ID Token")
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
    existing_user = await users_collection.find_one({"google_id": google_id})

    if existing_user:
        # 3. Update existing user's info and last login time
        await users_collection.update_one(
            {"_id": existing_user["_id"]},
            {"$set": {
                "name": name,
                "picture": picture,
                "last_login_at": datetime.utcnow()
            }}
        )
        user_id_str = str(existing_user["_id"])
        logger.info(f"User {email} updated. User ID: {user_id_str}")
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
        result = await users_collection.insert_one(new_user)
        user_id_str = str(result.inserted_id)
        logger.info(f"New user {email} created. User ID: {user_id_str}")

    # 4. Generate Application-Specific JWT
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user_id_str}, # 'sub' claim typically holds the user ID
        expires_delta=access_token_expires
    )

    # 5. Send JWT back to Frontend
    return {"access_token": access_token, "token_type": "bearer", "user_id": user_id_str}

# Example of a protected route (requires your application's JWT)
async def get_current_user(token: str = Depends(oauth2_scheme)) -> UserInDB:
    """
    Dependency to get the current authenticated user from the JWT token.
    """
    try:
        # Decode the JWT token using your application's secret key
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials")

        db = get_database()
        users_collection = db["users"]
        # Retrieve user from MongoDB using the extracted user ID
        user_data = await users_collection.find_one({"_id": ObjectId(user_id)})
        if not user_data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Convert ObjectId to string for Pydantic model before returning
        user_data["id"] = str(user_data["_id"])
        return UserInDB(**user_data) # Validate and return with Pydantic model

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

@app.get("/users/me", response_model=UserInDB, summary="Get current user information (Protected)")
async def read_users_me(current_user: UserInDB = Depends(get_current_user)):
    """
    Retrieves information about the current authenticated user.
    This route requires your application's JWT.
    """
    return current_user

# 🔧 Handle datetime serialization for ERP
def serialize_for_erp(data: dict) -> dict:
    for key, value in data.items():
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return data

# 🔁 Sync pending issues
async def sync_pending_issues_task():
    synced_count = 0
    # Ensure issues_collection is globally available
    if issues_collection is None:
        logger.error("Issues collection not initialized for sync task.")
        return 0

    # Use .to_list(length=None) to fetch all results from async cursor
    pending_issues = await issues_collection.find({"synced": False}).to_list(length=None)
    logger.info(f"Found {len(pending_issues)} pending issues.")

    for issue in pending_issues:
        issue_id = issue["_id"]
        logger.info(f"🔄 Syncing issue: {issue_id}")

        # Construct data for ERP, ensure 'status' is capitalized as per ERP requirement
        issue_data_for_erp = {
            "subject": issue["subject"],
            "raised_by": issue["raised_by"],
            "status": issue["status"].capitalize() if "status" in issue else "Open" # Default if status missing
        }

        try:
            serialized_data = serialize_for_erp(issue_data_for_erp)

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    settings.ERP_API_URL, # Use ERP_API_URL from settings
                    cookies={"sid": settings.ERP_SID}, # Use ERP_SID from settings
                    json={"data": serialized_data}
                )
                logger.info(f"📤 ERP response for {issue_id}: {response.status_code} - {response.text}")
                response.raise_for_status() # Raises HTTPStatusError for 4xx/5xx responses

            # Update issue status in MongoDB
            await issues_collection.update_one(
                {"_id": issue_id},
                {"$set": {"synced": True, "synced_at": datetime.utcnow()}}
            )
            synced_count += 1
            logger.info(f"✅ Issue {issue_id} synced successfully.")

        except httpx.RequestError as re:
            logger.error(f"🌐 Request error while syncing {issue_id}: {re}")
        except httpx.HTTPStatusError as hse:
            logger.error(f"HTTP error while syncing {issue_id}: {hse.response.status_code} - {hse.response.text}")
        except Exception as e:
            logger.error(f"❌ Failed to sync issue {issue_id}: {e}")

    return synced_count

# Run on startup and shutdown events
@app.on_event("startup")
async def startup_event():
    global issues_collection # Ensure issues_collection is updated globally
    # Connect to MongoDB
    await connect_to_mongo()
    issues_collection = get_issues_collection() # Get the initialized collection

    # Create indexes (if not already created)
    await issues_collection.create_index("created_at")
    await issues_collection.create_index("synced")
    # You might also want an index on 'google_id' in the 'users' collection
    await get_database()["users"].create_index("google_id", unique=True)
    logger.info("MongoDB indexes ensured.")

    # Start the background sync scheduler
    scheduler.add_job(sync_pending_issues_task, IntervalTrigger(minutes=5))
    scheduler.start()
    logger.info("🔁 Background sync scheduler started.")

@app.on_event("shutdown")
async def shutdown_event():
    # Shut down scheduler
    scheduler.shutdown()
    logger.info("🔁 Background sync scheduler stopped.")
    # Close MongoDB connection
    await close_mongo_connection()

# Submit Issue
@app.post("/submit-issue", summary="Submit a new issue to ERP or store for sync")
async def submit_issue(issue: IssueEntry):
    # Ensure issues_collection is globally available
    if issues_collection is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    issue_data = issue.dict()
    issue_data["created_at"] = datetime.utcnow()

    synced_status = False
    synced_at_time = None

    try:
        serialized_data = serialize_for_erp(issue_data)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                settings.ERP_API_URL,
                cookies={"sid": settings.ERP_SID},
                json={"data": serialized_data}
            )
            response.raise_for_status() # Raises HTTPStatusError for 4xx/5xx responses
        synced_status = True
        synced_at_time = datetime.utcnow()
        logger.info(f"✅ Issue submitted to ERP successfully: {issue_data['subject']}")

    except RequestError as e:
        logger.warning(f"🌐 [Offline] ERP unreachable, storing issue for sync: {e}")
        synced_status = False
        synced_at_time = None

    except httpx.HTTPStatusError as hse:
        logger.error(f"HTTP error submitting issue: {hse.response.status_code} - {hse.response.text}")
        synced_status = False
        synced_at_time = None

    except Exception as e:
        logger.error(f"❌ Unexpected error submitting issue: {e}")
        synced_status = False
        synced_at_time = None

    issue_data["synced"] = synced_status
    issue_data["synced_at"] = synced_at_time

    await issues_collection.insert_one(issue_data)
    return {"status": "stored", "synced": issue_data["synced"]}

# Get unsynced issues
@app.get("/unsynced-issues", response_model=List[IssueEntry], summary="Get issues not yet synced to ERP")
async def get_unsynced():
    # Ensure issues_collection is globally available
    if issues_collection is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    issues = await issues_collection.find({"synced": False}).to_list(100)
    # Convert ObjectId to string for all issues before returning
    for issue in issues:
        issue["_id"] = str(issue["_id"])
    return issues

# Manual Sync Trigger
@app.post("/sync-pending", summary="Manually trigger synchronization of pending issues")
async def sync_pending():
    synced = await sync_pending_issues_task()
    return {"status": f"Manual sync attempt completed. Synced {synced} issues."}

# Get synced issues
@app.get("/synced-issues", response_model=List[IssueEntry], summary="Get issues successfully synced to ERP")
async def get_synced_issues():
    # Ensure issues_collection is globally available
    if issues_collection is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    issues = await issues_collection.find({"synced": True}).to_list(100)
    # Convert ObjectId to string for all issues before returning
    for issue in issues:
        issue["_id"] = str(issue["_id"])
    return issues

# Fetch all issues from ERP and insert/update in MongoDB
@app.get("/fetch-all", summary="Fetch all issues from ERP and sync to MongoDB")
async def fetch_all_and_insert():
    batch_size = 500
    inserted_total = 0
    updated_total = 0
    failed_batches = []

    # Ensure issues_collection is globally available
    if issues_collection is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    async with httpx.AsyncClient() as client:
        # Adjusted range for demonstration. Consider pagination and ERP API limits.
        for start in range(0, 5000, batch_size): # Fetching up to 5000 records for example
            url = (
                f"{settings.ERP_API_URL}"
                f"?fields=[\"name\",\"subject\",\"raised_by\",\"status\"]" # Added status to fields
                f"&limit_start={start}&limit_page_length={batch_size}"
            )

            try:
                response = await client.get(url, cookies={"sid": settings.ERP_SID})
                if response.status_code != 200:
                    logger.error(f"Failed to fetch batch from ERP. Start: {start}, Status: {response.status_code}, Response: {response.text}")
                    failed_batches.append({"start": start, "status": response.status_code, "response": response.text})
                    break # Stop if a batch fails to fetch
                
                batch = response.json().get("data", [])
                if not batch:
                    logger.info(f"No more data from ERP at start: {start}")
                    break # No more data to fetch

                for issue in batch:
                    # Ensure '_id' is not passed to MongoDB if it's ERP's internal ID
                    # Use 'name' (ERP's primary key) for upsert logic
                    update_data = {
                        "subject": issue.get("subject"),
                        "raised_by": issue.get("raised_by"),
                        "status": issue.get("status", "Open"), # Default status if not present
                        "synced": True, # Issues fetched from ERP are considered synced
                        "synced_at": datetime.utcnow()
                    }
                    
                    result = await issues_collection.update_one(
                        {"name": issue["name"]}, # Use ERP's 'name' as unique identifier
                        {"$set": update_data},
                        upsert=True
                    )
                    if result.upserted_id:
                        inserted_total += 1
                        logger.debug(f"Inserted new issue from ERP: {issue['name']}")
                    elif result.modified_count > 0:
                        updated_total += 1
                        logger.debug(f"Updated existing issue from ERP: {issue['name']}")

            except Exception as e:
                logger.error(f"Error processing batch from ERP (start: {start}): {e}")
                failed_batches.append({"start": start, "error": str(e)})
                continue # Continue to next batch even if one fails

    return {
        "inserted_total": inserted_total,
        "updated_total": updated_total,
        "failed_batches": failed_batches
    }

# Delete all issues from MongoDB
@app.delete("/delete-issues", summary="Delete all issues from MongoDB (for testing/cleanup)")
async def delete_issues():
    # Ensure issues_collection is globally available
    if issues_collection is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    result = await issues_collection.delete_many({})
    logger.info(f"Deleted {result.deleted_count} issues from MongoDB.")
    return {"message": f"Deleted {result.deleted_count} issues from MongoDB."}

# Minimal Issue Model for ERP data for direct CRUD
class Issue(BaseModel):
    name: str # Assuming ERP's 'name' is the unique identifier for CRUD
    subject: str
    raised_by: Optional[str] = None
    status: str = "Open" # Default status

# CRUD APIs for issues directly in MongoDB
@app.get("/issues", response_model=List[IssueEntry], summary="Get all issues stored in MongoDB")
async def get_all_issues():
    # Ensure issues_collection is globally available
    if issues_collection is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    # Fetching all issues, limit to 100 for performance unless explicitly needed
    issues = await issues_collection.find().to_list(length=100)
    for issue in issues:
        issue["_id"] = str(issue["_id"]) # Convert ObjectId to string
    return issues

@app.get("/issues/{item_id}", response_model=IssueEntry, summary="Get a specific issue by its MongoDB _id")
async def get_issue_by_id(item_id: str):
    # Ensure issues_collection is globally available
    if issues_collection is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    try:
        object_id = ObjectId(item_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ObjectId format")

    issue = await issues_collection.find_one({"_id": object_id})
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    issue["_id"] = str(issue["_id"]) # Convert ObjectId to string
    return IssueEntry(**issue) # Use IssueEntry model for consistency

@app.post("/issues", response_model=IssueEntry, summary="Create a new issue directly in MongoDB")
async def create_local_issue(issue: IssueEntry):
    # Ensure issues_collection is globally available
    if issues_collection is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    issue_data = issue.dict()
    issue_data["created_at"] = datetime.utcnow()
    issue_data["synced"] = False # New local issues are unsynced by default
    issue_data["synced_at"] = None
    result = await issues_collection.insert_one(issue_data)
    issue_data["_id"] = str(result.inserted_id) # Set the new ID
    return IssueEntry(**issue_data)

@app.put("/issues/{item_id}", response_model=IssueEntry, summary="Update an existing issue by its MongoDB _id")
async def update_local_issue(item_id: str, updated_issue: IssueEntry):
    # Ensure issues_collection is globally available
    if issues_collection is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    try:
        object_id = ObjectId(item_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ObjectId format")

    # Prepare data for update, excluding _id if present in model
    update_data = updated_issue.dict(exclude_unset=True)
    # Mark as unsynced if crucial fields changed
    if "subject" in update_data or "raised_by" in update_data or "status" in update_data:
        update_data["synced"] = False
        update_data["synced_at"] = None

    result = await issues_collection.update_one(
        {"_id": object_id},
        {"$set": update_data}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Fetch and return the updated document
    updated_document = await issues_collection.find_one({"_id": object_id})
    updated_document["_id"] = str(updated_document["_id"])
    return IssueEntry(**updated_document)


@app.delete("/issues/{item_id}", summary="Delete an issue by its MongoDB _id")
async def delete_local_issue(item_id: str):
    # Ensure issues_collection is globally available
    if issues_collection is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    try:
        object_id = ObjectId(item_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ObjectId format")

    result = await issues_collection.delete_one({"_id": object_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Issue not found")
    return {"message": f"Issue with ID '{item_id}' deleted successfully"}

