from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import List, Optional
import httpx
import logging
from httpx import RequestError
from bson import ObjectId # Import ObjectId for MongoDB _id handling

from config import settings
from database import get_database, get_issues_collection # Assuming get_issues_collection is available
from models.issue import IssueEntry # Import IssueEntry model

# Create an API Router for issue-related endpoints
router = APIRouter(prefix="/issues", tags=["Issues Management"])

logger = logging.getLogger(__name__)

# 🔧 Handle datetime serialization for ERP
def serialize_for_erp(data: dict) -> dict:
    for key, value in data.items():
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return data

# 🔁 Sync pending issues task (called by scheduler or manual trigger)
async def sync_pending_issues_task():
    synced_count = 0
    issues_collection = get_issues_collection() # Get collection inside the task

    pending_issues = await issues_collection.find({"synced": False}).to_list(length=None)
    logger.info(f"Found {len(pending_issues)} pending issues.")

    for issue in pending_issues:
        issue_id = issue["_id"]
        logger.info(f"🔄 Syncing issue: {issue_id}")

        # Construct data for ERP, ensure 'status' is capitalized as per ERP requirement
        issue_data_for_erp = {
            "subject": issue["subject"],
            "raised_by": issue["raised_by"],
            "status": issue["status"].capitalize() if issue.get("status") else "Open"
        }

        try:
            serialized_data = serialize_for_erp(issue_data_for_erp)

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    settings.ERP_API_URL,
                    cookies={"sid": settings.ERP_SID}, # Reverted to cookies for SID authentication
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


# Submit Issue to ERPNext or store in MongoDB
@router.post("/submit-issue", summary="Submit a new issue to ERP or store for sync")
async def submit_issue(issue: IssueEntry):
    issues_collection = get_issues_collection()
    issue_data = issue.dict()
    issue_data["created_at"] = datetime.utcnow()

    synced_status = False
    synced_at_time = None

    try:
        serialized_data = serialize_for_erp(issue_data)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                settings.ERP_API_URL,
                cookies={"sid": settings.ERP_SID}, # Reverted to cookies for SID authentication
                json={"data": serialized_data}
            )
            response.raise_for_status()
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

# Get unsynced issues from MongoDB
@router.get("/unsynced-issues", response_model=List[IssueEntry], summary="Get issues not yet synced to ERP")
async def get_unsynced():
    issues_collection = get_issues_collection()
    issues = await issues_collection.find({"synced": False}).to_list(100)
    for issue in issues:
        issue["_id"] = str(issue["_id"])
    return issues

# Manually trigger synchronization of pending issues
@router.post("/sync-pending", summary="Manually trigger synchronization of pending issues")
async def sync_pending():
    synced = await sync_pending_issues_task()
    return {"status": f"Manual sync attempt completed. Synced {synced} issues."}

# Get synced issues from MongoDB
@router.get("/synced-issues", response_model=List[IssueEntry], summary="Get issues successfully synced to ERP")
async def get_synced_issues():
    issues_collection = get_issues_collection()
    issues = await issues_collection.find({"synced": True}).to_list(100)
    for issue in issues:
        issue["_id"] = str(issue["_id"])
    return issues

# Fetch all issues from ERP and insert/update in MongoDB
@router.get("/fetch-all", summary="Fetch all issues from ERP and sync to MongoDB")
async def fetch_all_and_insert():
    issues_collection = get_issues_collection()
    batch_size = 500
    inserted_total = 0
    updated_total = 0
    failed_batches = []

    async with httpx.AsyncClient() as client:
        for start in range(0, 5000, batch_size):
            url = (
                f"{settings.ERP_API_URL}"
                f"?fields=[\"name\",\"subject\",\"raised_by\",\"status\"]"
                f"&limit_start={start}&limit_page_length={batch_size}"
            )

            try:
                response = await client.get(url, cookies={"sid": settings.ERP_SID}) # Reverted to cookies
                if response.status_code != 200:
                    logger.error(f"Failed to fetch batch from ERP. Start: {start}, Status: {response.status_code}, Response: {response.text}")
                    failed_batches.append({"start": start, "status": response.status_code, "response": response.text})
                    break
                
                batch = response.json().get("data", [])
                if not batch:
                    logger.info(f"No more data from ERP at start: {start}")
                    break

                for issue in batch:
                    update_data = {
                        "subject": issue.get("subject"),
                        "raised_by": issue.get("raised_by"),
                        "status": issue.get("status", "Open"),
                        "synced": True,
                        "synced_at": datetime.utcnow()
                    }
                    
                    result = await issues_collection.update_one(
                        {"name": issue["name"]},
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
                continue

    return {
        "inserted_total": inserted_total,
        "updated_total": updated_total,
        "failed_batches": failed_batches
    }

# Delete all issues from MongoDB
@router.delete("/delete-issues", summary="Delete all issues from MongoDB (for testing/cleanup)")
async def delete_issues():
    issues_collection = get_issues_collection()
    result = await issues_collection.delete_many({})
    logger.info(f"Deleted {result.deleted_count} issues from MongoDB.")
    return {"message": f"Deleted {result.deleted_count} issues from MongoDB."}

# Minimal Issue Model for ERP data for direct CRUD
class Issue(BaseModel):
    name: str
    subject: str
    raised_by: Optional[str] = None
    status: str = "Open" # This is used for direct MongoDB CRUD, not for ERP sync

@router.get("/", response_model=List[IssueEntry], summary="Get all issues stored in MongoDB")
async def get_all_issues():
    issues_collection = get_issues_collection()
    issues = await issues_collection.find().to_list(length=100)
    for issue in issues:
        issue["_id"] = str(issue["_id"])
    return issues

@router.get("/{item_id}", response_model=IssueEntry, summary="Get a specific issue by its MongoDB _id")
async def get_issue_by_id(item_id: str):
    issues_collection = get_issues_collection()
    try:
        object_id = ObjectId(item_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ObjectId format")

    issue = await issues_collection.find_one({"_id": object_id})
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    issue["_id"] = str(issue["_id"])
    return IssueEntry(**issue)

@router.post("/", response_model=IssueEntry, summary="Create a new issue directly in MongoDB")
async def create_local_issue(issue: IssueEntry):
    issues_collection = get_issues_collection()
    issue_data = issue.dict()
    issue_data["created_at"] = datetime.utcnow()
    issue_data["synced"] = False
    issue_data["synced_at"] = None
    result = await issues_collection.insert_one(issue_data)
    issue_data["_id"] = str(result.inserted_id)
    return IssueEntry(**issue_data)

@router.put("/{item_id}", response_model=IssueEntry, summary="Update an existing issue by its MongoDB _id")
async def update_local_issue(item_id: str, updated_issue: IssueEntry):
    issues_collection = get_issues_collection()
    try:
        object_id = ObjectId(item_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ObjectId format")

    update_data = updated_issue.dict(exclude_unset=True)
    if "subject" in update_data or "raised_by" in update_data or "status" in update_data:
        update_data["synced"] = False
        update_data["synced_at"] = None

    result = await issues_collection.update_one(
        {"_id": object_id},
        {"$set": update_data}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Issue not found")

    updated_document = await issues_collection.find_one({"_id": object_id})
    updated_document["_id"] = str(updated_document["_id"])
    return IssueEntry(**updated_document)


@router.delete("/{item_id}", summary="Delete an issue by its MongoDB _id")
async def delete_local_issue(item_id: str):
    issues_collection = get_issues_collection()
    try:
        object_id = ObjectId(item_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ObjectId format")

    result = await issues_collection.delete_one({"_id": object_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Issue not found")
    return {"message": f"Issue with ID '{item_id}' deleted successfully"}
