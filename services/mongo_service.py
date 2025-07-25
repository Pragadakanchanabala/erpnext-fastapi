import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from bson import ObjectId

from database import get_issues_collection
from models.issue import IssueEntry

logger = logging.getLogger(__name__)

async def get_all_issues() -> List[IssueEntry]:
    """Retrieves all issues from MongoDB."""
    issues_collection = get_issues_collection()
    issues_cursor = issues_collection.find()
    
    valid_issues = []
    async for issue_doc in issues_cursor:
        issue_doc["_id"] = str(issue_doc["_id"])
        try:
            valid_issues.append(IssueEntry(**issue_doc))
        except Exception as e:
            logger.error(f"Data validation error for document {issue_doc['_id']}: {e}")
            
    return valid_issues

async def get_unsynced_issues() -> List[IssueEntry]:
    """Retrieves issues from MongoDB that are not yet synced to ERPNext."""
    issues_collection = get_issues_collection()
    issues_cursor = issues_collection.find({"synced": False})

    valid_issues = []
    async for issue_doc in issues_cursor:
        issue_doc["_id"] = str(issue_doc["_id"])
        try:
            valid_issues.append(IssueEntry(**issue_doc))
        except Exception as e:
            logger.error(f"Data validation error for unsynced document {issue_doc['_id']}: {e}")
            
    return valid_issues

async def get_synced_issues() -> List[IssueEntry]:
    """Retrieves issues from MongoDB that have been successfully synced to ERPNext."""
    issues_collection = get_issues_collection()
    issues_cursor = issues_collection.find({"synced": True})

    valid_issues = []
    async for issue_doc in issues_cursor:
        issue_doc["_id"] = str(issue_doc["_id"])
        try:
            valid_issues.append(IssueEntry(**issue_doc))
        except Exception as e:
            logger.error(f"Data validation error for synced document {issue_doc['_id']}: {e}")
            
    return valid_issues

async def get_issue_by_id(item_id: str) -> Optional[IssueEntry]:
    """Retrievis a single issue from MongoDB by its MongoDB _id."""
    issues_collection = get_issues_collection()
    try:
        object_id = ObjectId(item_id)
    except Exception:
        return None # Invalid ID format

    issue = await issues_collection.find_one({"_id": object_id})
    if issue:
        issue["_id"] = str(issue["_id"])
        return IssueEntry(**issue)
    return None

async def create_issue(issue_data: Dict[str, Any]) -> IssueEntry:
    """
    Creates a new issue record in MongoDB and returns the created document.
    This version reads the document back from the DB to ensure consistency.
    """
    issues_collection = get_issues_collection()
    result = await issues_collection.insert_one(issue_data)
    
    # Fetch the document we just created to get its true state from the DB
    created_document = await issues_collection.find_one({"_id": result.inserted_id})
    
    created_document["_id"] = str(created_document["_id"])
    return IssueEntry(**created_document)

async def update_issue(item_id: str, update_data: Dict[str, Any]) -> Optional[IssueEntry]:
    """Updates an existing issue in MongoDB by its MongoDB _id."""
    issues_collection = get_issues_collection()
    try:
        object_id = ObjectId(item_id)
    except Exception:
        return None # Invalid ID format

    await issues_collection.update_one(
        {"_id": object_id},
        {"$set": update_data}
    )
    
    # Fetch the updated document to return it
    updated_document = await issues_collection.find_one({"_id": object_id})
    if updated_document:
        updated_document["_id"] = str(updated_document["_id"])
        return IssueEntry(**updated_document)
    return None

async def delete_issue(item_id: str) -> bool:
    """Deletes an issue from MongoDB by its MongoDB _id."""
    issues_collection = get_issues_collection()
    try:
        object_id = ObjectId(item_id)
    except Exception:
        return False # Invalid ID format

    result = await issues_collection.delete_one({"_id": object_id})
    return result.deleted_count > 0

async def delete_all_issues() -> int:
    """Deletes all issue records from MongoDB."""
    issues_collection = get_issues_collection()
    result = await issues_collection.delete_many({})
    return result.deleted_count