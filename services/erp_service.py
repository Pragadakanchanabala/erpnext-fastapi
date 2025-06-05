import httpx
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from config import settings
from fastapi import HTTPException, status # Used for raising specific HTTP exceptions

logger = logging.getLogger(__name__)

def serialize_for_erp(data: dict) -> dict:
    """Converts datetime objects in a dict to ISO format strings for ERPNext."""
    for key, value in data.items():
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return data

async def submit_issue_to_erp(issue_data: dict, is_update: bool = False) -> Dict[str, Any]:
    """
    Helper function to send issue data to ERPNext.
    Handles both creation (POST) and update (PUT) based on `is_update`.
    Returns ERPNext's response data if successful.
    Raises HTTPException for configuration errors or HTTPStatusError for 4xx/5xx responses from ERPNext.
    """
    if not settings.ERP_API_URL or not settings.ERP_SID:
        logger.error("ERPNext API URL or SID is not configured.")
        raise HTTPException(status_code=500, detail="ERPNext API not configured.")

    # Prepare data for ERP, ensuring 'status' is capitalized and other fields are present
    erp_payload = {
        "subject": issue_data.get("subject"),
        "raised_by": issue_data.get("raised_by"),
        "status": issue_data.get("status", "Open").capitalize() # Default to "Open" if status missing
    }
    # Add ERPNext's 'name' for updates
    if is_update and "name" in issue_data:
        erp_payload["name"] = issue_data["name"]

    serialized_data = serialize_for_erp(erp_payload)

    async with httpx.AsyncClient() as client:
        if is_update and "name" in issue_data:
            erp_update_url = f"{settings.ERP_API_URL}/{issue_data['name']}"
            response = await client.put(
                erp_update_url,
                cookies={"sid": settings.ERP_SID},
                json={"data": serialized_data}
            )
            logger.info(f"📤 ERP PUT response for {issue_data.get('name', 'N/A')}: {response.status_code} - {response.text}")
        else:
            response = await client.post(
                settings.ERP_API_URL,
                cookies={"sid": settings.ERP_SID},
                json={"data": serialized_data}
            )
            logger.info(f"📤 ERP POST response: {response.status_code} - {response.text}")

        response.raise_for_status() # Raises HTTPStatusError for 4xx/5xx responses
        return response.json().get("data", {}) # Return ERPNext's response data if successful

async def delete_issue_in_erp(erp_issue_name: str) -> bool:
    """
    Helper function to delete an issue in ERPNext by its 'name' (ERPNext's ID).
    Returns True if deletion in ERPNext was successful, False otherwise.
    """
    if not settings.ERP_API_URL or not settings.ERP_SID:
        logger.error("ERPNext API URL or SID is not configured for deletion.")
        return False

    erp_delete_url = f"{settings.ERP_API_URL}/{erp_issue_name}"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.delete(
                erp_delete_url,
                cookies={"sid": settings.ERP_SID}
            )
            response.raise_for_status()
            logger.info(f"✅ Issue {erp_issue_name} deleted successfully in ERPNext.")
            return True
        except httpx.RequestError as re:
            logger.error(f"🌐 Request error while deleting {erp_issue_name} in ERP: {re}")
        except httpx.HTTPStatusError as hse:
            logger.error(f"HTTP error while deleting {erp_issue_name} in ERP: {hse.response.status_code} - {hse.response.text}")
        except Exception as e:
            logger.error(f"❌ Failed to delete issue {erp_issue_name} in ERP: {e}")
    return False

async def fetch_issues_from_erp(start: int, batch_size: int) -> Dict[str, Any]:
    """
    Fetches a batch of issues from ERPNext.
    Returns response data or raises errors.
    """
    if not settings.ERP_API_URL or not settings.ERP_SID:
        logger.error("ERPNext API URL or SID is not configured for fetching.")
        raise HTTPException(status_code=500, detail="ERPNext API not configured.")

    url = (
        f"{settings.ERP_API_URL}"
        f"?fields=[\"name\",\"subject\",\"raised_by\",\"status\"]" # Ensure status is fetched
        f"&limit_start={start}&limit_page_length={batch_size}"
    )

    async with httpx.AsyncClient() as client:
        response = await client.get(url, cookies={"sid": settings.ERP_SID})
        response.raise_for_status() # Raise HTTPStatusError for bad responses
        return response.json().get("data", [])
