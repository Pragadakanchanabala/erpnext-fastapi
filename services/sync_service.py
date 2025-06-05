import logging
from datetime import datetime
import httpx
from fastapi import HTTPException, status # Import status for HTTP exceptions

from database import get_issues_collection # Access MongoDB collection
from services import erp_service, mongo_service # Import ERP-specific service functions

logger = logging.getLogger(__name__)

async def sync_pending_issues_task():
    """
    Background task that periodically checks MongoDB for unsynced issues
    and attempts to create/update them in ERPNext.
    This function acts as the core of the offline caching mechanism for outgoing changes.
    """
    synced_count = 0
    issues_collection = get_issues_collection()

    pending_issues = await issues_collection.find({"synced": False}).to_list(length=None)
    logger.info(f"Found {len(pending_issues)} pending issues to sync to ERPNext.")

    for issue in pending_issues:
        issue_mongodb_id = issue["_id"]
        erp_issue_name = issue.get("name")

        try:
            if erp_issue_name:
                # Issue already has an ERPNext ID, attempt to UPDATE it in ERPNext
                erp_response_data = await erp_service.submit_issue_to_erp(issue, is_update=True)
            else:
                # New issue, attempt to CREATE it in ERPNext
                erp_response_data = await erp_service.submit_issue_to_erp(issue, is_update=False)
                erp_issue_name = erp_response_data.get("name")
                if not erp_issue_name:
                    logger.error(f"ERPNext did not return 'name' for new issue {issue_mongodb_id}. Cannot mark as synced properly.")
                    continue

            await issues_collection.update_one(
                {"_id": issue_mongodb_id},
                {"$set": {
                    "synced": True,
                    "synced_at": datetime.utcnow(),
                    "name": erp_issue_name
                }}
            )
            synced_count += 1
            logger.info(f"✅ Issue {issue_mongodb_id} (ERPName: {erp_issue_name}) synced/updated successfully.")

        except HTTPException as e:
            logger.error(f"HTTP error during sync task for {issue_mongodb_id}: {e.detail} (Status: {e.status_code})")
        except httpx.RequestError as re:
            logger.warning(f"🌐 [Offline/Connection] ERP unreachable during sync for {issue_mongodb_id}: {re}")
        except Exception as e:
            logger.error(f"❌ Unexpected error syncing issue {issue_mongodb_id}: {e}")

    return synced_count


async def sync_all_issues_from_erp(batch_size: int = 500, max_records: int = 35000):
    """
    Fetches all issues from ERPNext in batches and synchronizes them with MongoDB.
    This acts as the core of the incoming sync mechanism, creating new records or updating
    existing ones in MongoDB based on ERPNext's data.
    """
    inserted_total = 0
    updated_total = 0
    failed_batches = []
    issues_collection = get_issues_collection() # Get collection here

    for start in range(0, max_records, batch_size):
        try:
            batch = await erp_service.fetch_issues_from_erp(start, batch_size)
            if not batch:
                logger.info(f"No more data from ERP at start: {start}")
                break

            for issue_from_erp in batch:
                erp_issue_name = issue_from_erp["name"]
                update_data = {
                    "subject": issue_from_erp.get("subject"),
                    "raised_by": issue_from_erp.get("raised_by"),
                    "status": issue_from_erp.get("status", "Open"),
                    "synced": True,
                    "synced_at": datetime.utcnow()
                }
                
                result = await issues_collection.update_one(
                    {"name": erp_issue_name},
                    {"$set": update_data},
                    upsert=True
                )
                if result.upserted_id:
                    inserted_total += 1
                    logger.debug(f"Inserted new issue from ERP: {erp_issue_name}")
                elif result.modified_count > 0:
                    updated_total += 1
                    logger.debug(f"Updated existing issue from ERP: {erp_issue_name}")

        except HTTPException as hse: # ERP service now raises HTTPException for HTTP errors
            logger.error(f"Failed to fetch batch from ERP. Start: {start}, Status: {hse.status_code}, Response: {hse.detail}")
            failed_batches.append({"start": start, "status": hse.status_code, "response": hse.detail})
            break
        except httpx.RequestError as e:
            logger.error(f"Request error while fetching batch from ERP (start: {start}): {e}")
            failed_batches.append({"start": start, "error": str(e)})
            break # Break on network errors to avoid flooding
        except Exception as e:
            logger.error(f"Error processing batch from ERP (start: {start}): {e}")
            failed_batches.append({"start": start, "error": str(e)})
            continue

    return {
        "inserted_total": inserted_total,
        "updated_total": updated_total,
        "failed_batches": failed_batches
    }
