import httpx
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

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

async def fetch_issues_from_erp(start: int, batch_size: int) -> List[Dict[str, Any]]:
    """
    Fetches a batch of issues from ERPNext.
    Returns response data or raises errors.
    """
    if not settings.ERP_API_URL or not settings.ERP_SID:
        logger.error("ERPNext API URL or SID is not configured for fetching issues.")
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

async def get_doctype_count() -> int:
    """Fetches the total count of DocTypes from ERPNext."""
    if not settings.ERP_API_URL or not settings.ERP_SID:
        logger.error("ERPNext API URL or SID is not configured for fetching DocType count.")
        raise HTTPException(status_code=500, detail="ERPNext API not configured.")

    # ERPNext often exposes /api/method/frappe.client.get_count for DocType counts
    count_url = settings.ERP_API_URL.replace("/api/resource/Issue", "/api/method/frappe.client.get_count")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{count_url}?doctype=DocType",
                cookies={"sid": settings.ERP_SID}
            )
            response.raise_for_status()
            count = response.json().get("message", 0) # get_count usually returns count in 'message'
            logger.info(f"Fetched DocType count: {count}")
            return count
    except httpx.RequestError as e:
        logger.error(f"🌐 Network error fetching DocType count: {e}")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"ERPNext unreachable: {e}")
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching DocType count: {e.response.status_code} - {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except Exception as e:
        logger.error(f"Unexpected error fetching DocType count: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal error: {e}")

async def get_doctype_list_from_erp(limit_start: int = 0, limit_page_length: int = 100) -> List[Dict[str, Any]]:
    """Fetches a list of DocTypes (names only) from ERPNext."""
    if not settings.ERP_API_URL or not settings.ERP_SID:
        logger.error("ERPNext API URL or SID is not configured for fetching DocType list.")
        raise HTTPException(status_code=500, detail="ERPNext API not configured.")

    # ERPNext often exposes /api/method/frappe.client.get_list for DocType lists
    list_url = settings.ERP_API_URL.replace("/api/resource/Issue", "/api/method/frappe.client.get_list")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{list_url}?doctype=DocType&fields=[\"name\"]&limit_start={limit_start}&limit_page_length={limit_page_length}",
                cookies={"sid": settings.ERP_SID}
            )
            response.raise_for_status()
            data = response.json().get("message", []) # get_list usually returns data in 'message'
            logger.info(f"Fetched DocType list (batch {limit_start}-{limit_start+limit_page_length}): {len(data)} items")
            return data
    except httpx.RequestError as e:
        logger.error(f"🌐 Network error fetching DocType list: {e}")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"ERPNext unreachable: {e}")
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching DocType list: {e.response.status_code} - {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except Exception as e:
        logger.error(f"Unexpected error fetching DocType list: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal error: {e}")


async def get_doctype_schema_from_erp(doctype_name: str) -> Dict[str, Any]:
    """Fetches the full DocType schema (definition) for a given DocType name."""
    if not settings.ERP_API_URL or not settings.ERP_SID:
        logger.error("ERPNext API URL or SID is not configured for fetching DocType schema.")
        raise HTTPException(status_code=500, detail="ERPNext API not configured.")

    # To get full DocType schema, you typically fetch the DocType itself as a resource
    # The URL pattern for getting a DocType's definition is /api/resource/DocType/{doctype_name}
    schema_url = settings.ERP_API_URL.replace("/api/resource/Issue", f"/api/resource/DocType/{doctype_name}")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                schema_url,
                cookies={"sid": settings.ERP_SID}
            )
            response.raise_for_status()
            data = response.json().get("data") # Direct resource get returns data in 'data'
            if not data:
                logger.warning(f"No data found for DocType schema: {doctype_name}")
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"DocType '{doctype_name}' not found or no data available.")
            logger.info(f"Fetched schema for DocType: {doctype_name}")
            return data
    except httpx.RequestError as e:
        logger.error(f"🌐 Network error fetching DocType schema for {doctype_name}: {e}")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"ERPNext unreachable: {e}")
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching DocType schema for {doctype_name}: {e.response.status_code} - {e.response.text}")
        # Re-raise the specific HTTP error received from ERPNext
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except Exception as e:
        logger.error(f"Unexpected error fetching DocType schema for {doctype_name}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal error: {e}")
