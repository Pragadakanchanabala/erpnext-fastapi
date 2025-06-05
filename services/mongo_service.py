import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from bson import ObjectId
from pymongo.errors import ConnectionFailure

from database import get_issues_collection # Assuming this returns a MotorCollection
from models.issue import IssueEntry # Import IssueEntry model

logger = logging.getLogger(__name__)

async def get_all_issues() -> List[IssueEntry]:
    """Retrieves all issues from MongoDB."""
    issues_collection = get_issues_collection()
    issues = await issues_collection.find().to_list(length=100) # Limit for performance
    for issue in issues:
        issue["_id"] = str(issue["_id"])
    return [IssueEntry(**issue) for issue in issues]

async def get_unsynced_issues() -> List[IssueEntry]:
    """Retrieves issues from MongoDB that are not yet synced to ERPNext."""
    issues_collection = get_issues_collection()
    issues = await issues_collection.find({"synced": False}).to_list(length=100)
    for issue in issues:
        issue["_id"] = str(issue["_id"])
    return [IssueEntry(**issue) for issue in issues]

async def get_synced_issues() -> List[IssueEntry]:
    """Retrieves issues from MongoDB that have been successfully synced to ERPNext."""
    issues_collection = get_issues_collection()
    issues = await issues_collection.find({"synced": True}).to_list(length=100)
    for issue in issues:
        issue["_id"] = str(issue["_id"])
    return [IssueEntry(**issue) for issue in issues]

async def get_issue_by_id(item_id: str) -> Optional[IssueEntry]:
    """Retrieves a single issue from MongoDB by its MongoDB _id."""
    issues_collection = get_issues_collection()
    try:
        object_id = ObjectId(item_id)
    except Exception as e:
        logger.error(f"Invalid ObjectId format: {item_id}, Error: {e}")
        return None

    issue = await issues_collection.find_one({"_id": object_id})
    if issue:
        issue["_id"] = str(issue["_id"])
        return IssueEntry(**issue)
    return None

async def create_issue(issue_data: Dict[str, Any]) -> IssueEntry:
    """Creates a new issue record in MongoDB."""
    issues_collection = get_issues_collection()
    result = await issues_collection.insert_one(issue_data)
    issue_data["_id"] = str(result.inserted_id)
    return IssueEntry(**issue_data)

async def update_issue(item_id: str, update_data: Dict[str, Any]) -> Optional[IssueEntry]:
    """Updates an existing issue in MongoDB by its MongoDB _id."""
    issues_collection = get_issues_collection()
    try:
        object_id = ObjectId(item_id)
    except Exception as e:
        logger.error(f"Invalid ObjectId format for update: {item_id}, Error: {e}")
        return None

    result = await issues_collection.update_one(
        {"_id": object_id},
        {"$set": update_data}
    )
    if result.matched_count == 0:
        return None
    
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
    except Exception as e:
        logger.error(f"Invalid ObjectId format for delete: {item_id}, Error: {e}")
        return False

    result = await issues_collection.delete_one({"_id": object_id})
    return result.deleted_count > 0

async def delete_all_issues() -> int:
    """Deletes all issue records from MongoDB."""
    issues_collection = get_issues_collection()
    result = await issues_collection.delete_many({})
    return result.deleted_count
