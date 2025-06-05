from fastapi import APIRouter, HTTPException, status
from typing import List, Optional
import logging
import httpx # Still needed for specific httpx.RequestError in direct calls
from datetime import datetime # Still needed for datetime.utcnow()

from models.issue import IssueEntry
from services import erp_service, mongo_service, sync_service # Import the new service modules

# Create an API Router for issue-related endpoints
router = APIRouter(prefix="/issues", tags=["Issues Management"])

logger = logging.getLogger(__name__)

# --- API Endpoints for Issues ---

@router.post("/submit-issue", response_model=IssueEntry, summary="Submit a new issue to ERP and store in MongoDB")
async def submit_issue(issue: IssueEntry):
    """
    Creates a new issue. Attempts to submit to ERPNext immediately.
    If ERPNext is unreachable or rejects, stores the issue in MongoDB for later sync.
    """
    issue_data = issue.dict()
    issue_data["created_at"] = datetime.utcnow()
    issue_data["synced"] = False # Default to unsynced

    try:
        erp_response_data = await erp_service.submit_issue_to_erp(issue_data, is_update=False)
        issue_data["name"] = erp_response_data.get("name")
        issue_data["synced"] = True
        issue_data["synced_at"] = datetime.utcnow()
        logger.info(f"✅ Issue submitted to ERP successfully: {issue_data['subject']} (ERP ID: {issue_data.get('name')})")
    except HTTPException as e:
        logger.warning(f"ERPNext rejection (Status: {e.status_code}): {e.detail}, storing for sync.")
    except httpx.RequestError as e:
        logger.warning(f"🌐 [Offline] ERP unreachable, storing issue for sync: {e}")
    except Exception as e:
        logger.error(f"❌ Unexpected error submitting issue to ERP: {e}, storing for sync.")

    created_issue = await mongo_service.create_issue(issue_data)
    return created_issue

@router.get("/unsynced", response_model=List[IssueEntry], summary="Get issues not yet synced to ERP")
async def get_unsynced_issues():
    """Retrieves a list of issues from MongoDB that have not yet been successfully synced to ERPNext."""
    return await mongo_service.get_unsynced_issues()

@router.post("/sync-pending", summary="Manually trigger synchronization of pending issues")
async def sync_pending():
    """Manually triggers the background task to synchronize all pending (unsynced) issues from MongoDB to ERPNext."""
    # This now calls the comprehensive sync_all_issues_from_erp from sync_service
    # If you only want to sync pending (MongoDB to ERPNext) issues, you would call sync_service.sync_pending_issues_task()
    # The current definition of sync_pending_issues_task in sync_service.py still does only pending.
    # So, if you want this to *only* push pending issues to ERP, revert to:
    # synced = await sync_service.sync_pending_issues_task()
    # For now, sticking to the "sync_pending_issues_task" as named in the Canvas
    synced = await sync_service.sync_pending_issues_task()
    return {"status": f"Manual sync attempt completed. Synced {synced} issues."}


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
