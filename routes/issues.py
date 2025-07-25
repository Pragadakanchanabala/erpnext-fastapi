# File: routes/issues.py

from fastapi import APIRouter, HTTPException
from typing import List
from datetime import datetime
import logging

from models.issue import IssueEntry, IssueCreate # Import both models
from services import mongo_service, erp_service, sync_service

router = APIRouter(prefix="/issues", tags=["Issues Management"])
logger = logging.getLogger(__name__)


@router.post("/submit-issue", response_model=IssueEntry, summary="Submit a new issue")
async def submit_issue(issue_to_create: IssueCreate): # Use IssueCreate for input
    """
    Creates a new issue by saving it to MongoDB first, then attempts a
    real-time sync to ERPNext. This ensures data is never lost.
    """
    # --- Step 1: Prepare and Save to MongoDB FIRST ---
    issue_data = issue_to_create.model_dump()
    issue_data["synced"] = False # Always default to unsynced
    issue_data["created_at"] = datetime.utcnow()

    try:
        new_local_issue = await mongo_service.create_issue(issue_data)
        logger.info(f"Issue saved locally with MongoDB ID: {new_local_issue.id}")
    except Exception as e:
        logger.error(f"CRITICAL: Could not save issue to MongoDB. Error: {e}")
        raise HTTPException(status_code=500, detail="Failed to write issue to local database.")

    # --- Step 2: Try to sync the newly created issue to ERPNext ---
    try:
        erp_response = await erp_service.submit_issue_to_erp(new_local_issue.model_dump())
        
        # --- Step 3: If sync succeeds, update the local record ---
        update_data = {
            "synced": True,
            "synced_at": datetime.utcnow(),
            "name": erp_response.get("name") # Save the permanent ERP ID
        }
        updated_issue = await mongo_service.update_issue(new_local_issue.id, update_data)
        logger.info(f"Real-time sync to ERP successful. ERP Name: {updated_issue.name}")
        return updated_issue # Return the fully synced issue

    except Exception as e:
        logger.warning(f"Real-time sync to ERP failed. The issue will be synced by the background job. Error: {e}")
        # If sync fails, just return the locally saved record. It's safe.
        return new_local_issue

# --- Other endpoints you already have can remain the same ---

@router.get("/unsynced", response_model=List[IssueEntry], summary="Get issues not yet synced to ERP")
async def get_unsynced_issues():
    return await mongo_service.get_unsynced_issues()

@router.post("/sync-pending", summary="Manually trigger synchronization of pending issues")
async def sync_pending():
    synced_count = await sync_service.sync_pending_issues_task()
    return {"status": f"Manual sync attempt completed. Synced {synced_count} issues."}

# (Include the rest of your endpoints like /synced, /fetch-all, /{item_id}, etc.)


@router.get("/synced", response_model=List[IssueEntry], summary="Get issues successfully synced to ERP")
async def get_synced_issues():
    """Retrieves a list of issues from MongoDB that have been successfully synced to ERPNext."""
    return await mongo_service.get_synced_issues()

@router.get("/fetch-all", summary="Fetch all issues from ERP and sync to MongoDB")
async def fetch_all_and_insert():
    """
    Fetches all issues from ERPNext and synchronizes them with MongoDB.
    This acts as the incoming sync mechanism, creating new records or updating
    existing ones in MongoDB based on ERPNext's data.
    """
    # Delegate the entire fetching and inserting process to the sync_service
    return await sync_service.sync_all_issues_from_erp()

@router.delete("/delete-all", summary="Delete all issues from MongoDB (for testing/cleanup)")
async def delete_all_issues_local():
    """Deletes all issue records stored in MongoDB. Use with caution, primarily for testing or cleanup."""
    deleted_count = await mongo_service.delete_all_issues()
    logger.info(f"Deleted {deleted_count} issues from MongoDB.")
    return {"message": f"Deleted {deleted_count} issues from MongoDB."}

@router.get("/", response_model=List[IssueEntry], summary="Get all issues stored in MongoDB")
async def get_all_issues_local():
    """Retrieves all issues currently stored in the MongoDB database."""
    return await mongo_service.get_all_issues()

@router.get("/{item_id}", response_model=IssueEntry, summary="Get a specific issue by its MongoDB _id")
async def get_issue_by_id_local(item_id: str):
    """Retrieves a single issue from MongoDB by its unique MongoDB `_id`."""
    issue = await mongo_service.get_issue_by_id(item_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue

@router.post("/create-local", response_model=IssueEntry, summary="Create a new issue directly in MongoDB (without immediate ERP sync)")
async def create_local_issue(issue: IssueEntry):
    """
    Creates a new issue record directly in MongoDB.
    This issue will be marked as unsynced and will be picked up by the
    background sync task later if it needs to go to ERPNext.
    """
    issue_data = issue.dict()
    issue_data["created_at"] = datetime.utcnow()
    issue_data["synced"] = False
    issue_data["synced_at"] = None
    issue_data["name"] = issue_data.get("name") # Preserve ERPNext 'name' if provided locally
    
    created_issue = await mongo_service.create_issue(issue_data)
    return created_issue

@router.put("/{item_id}", response_model=IssueEntry, summary="Update an existing issue by its MongoDB _id")
async def update_local_issue(item_id: str, updated_issue: IssueEntry):
    """
    Updates an existing issue in MongoDB by its MongoDB `_id`.
    Attempts to update in ERPNext immediately if the issue has an ERPNext `name`.
    If ERPNext update fails, it will be retried by the background sync task.
    """
    existing_issue = await mongo_service.get_issue_by_id(item_id)
    if not existing_issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    update_data = updated_issue.dict(exclude_unset=True)
    
    # Mark as unsynced if crucial fields changed
    if "subject" in update_data or "raised_by" in update_data or "status" in update_data:
        update_data["synced"] = False
        update_data["synced_at"] = None
    
    erp_issue_name = existing_issue.name
    if erp_issue_name:
        try:
            erp_payload = {**existing_issue.dict(), **update_data}
            await erp_service.submit_issue_to_erp(erp_payload, is_update=True)
            update_data["synced"] = True
            update_data["synced_at"] = datetime.utcnow()
            logger.info(f"✅ Issue {item_id} (ERP: {erp_issue_name}) updated successfully in ERPNext.")
        except HTTPException as e:
            logger.warning(f"ERPNext rejection (Status: {e.status_code}) during update for {item_id}: {e.detail}. Will retry later.")
            update_data["synced"] = False
            update_data["synced_at"] = None
        except httpx.RequestError as e:
            logger.warning(f"🌐 [Offline] ERP unreachable during update for {item_id}: {e}. Will retry later.")
            update_data["synced"] = False
            update_data["synced_at"] = None
        except Exception as e:
            logger.error(f"❌ Unexpected error updating issue {item_id} in ERP: {e}. Will retry later.")
            update_data["synced"] = False
            update_data["synced_at"] = None

    updated_issue_mongo = await mongo_service.update_issue(item_id, update_data)
    if not updated_issue_mongo:
        raise HTTPException(status_code=404, detail="Issue not found or could not be updated in MongoDB")
    return updated_issue_mongo


@router.delete("/{item_id}", summary="Delete an issue by its MongoDB _id")
async def delete_local_issue(item_id: str):
    """
    Deletes an issue from MongoDB by its `_id`.
    Also attempts to delete the corresponding issue from ERPNext if it has an ERPNext `name`.
    """
    issue_to_delete = await mongo_service.get_issue_by_id(item_id)
    if not issue_to_delete:
        raise HTTPException(status_code=404, detail="Issue not found in MongoDB")

    erp_issue_name = issue_to_delete.name
    if erp_issue_name:
        erp_deleted = await erp_service.delete_issue_in_erp(erp_issue_name)
        if not erp_deleted:
            logger.warning(f"Failed to delete issue {erp_issue_name} from ERPNext. Deleting locally anyway.")

    deleted_from_mongo = await mongo_service.delete_issue(item_id)
    if not deleted_from_mongo:
        raise HTTPException(status_code=404, detail="Issue not found or could not be deleted from MongoDB")
    return {"message": f"Issue with ID '{item_id}' deleted successfully from MongoDB (and attempted from ERPNext)"}
