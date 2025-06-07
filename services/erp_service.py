import httpx
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

from config import settings
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

def serialize_for_erp(data: dict) -> dict:
    for key, value in data.items():
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return data

# Helper to construct full ERPNext URLs
def erp_url(resource: str, path: Optional[str] = None, params: Optional[str] = None) -> str:
    url = f"{settings.ERP_API_URL}/{resource}"
    if path:
        url += f"/{path}"
    if params:
        url += f"?{params}"
    return url

async def submit_issue_to_erp(issue_data: dict, is_update: bool = False) -> Dict[str, Any]:
    if not settings.ERP_API_URL or not settings.ERP_SID:
        logger.error("ERPNext API URL or SID is not configured.")
        raise HTTPException(status_code=500, detail="ERPNext API not configured.")

    erp_payload = {
        "subject": issue_data.get("subject"),
        "raised_by": issue_data.get("raised_by"),
        "status": issue_data.get("status", "Open").capitalize()
    }

    if is_update and "name" in issue_data:
        erp_payload["name"] = issue_data["name"]

    serialized_data = serialize_for_erp(erp_payload)

    async with httpx.AsyncClient() as client:
        if is_update and "name" in issue_data:
            url = erp_url("resource/Issue", issue_data["name"])
            response = await client.put(url, cookies={"sid": settings.ERP_SID}, json={"data": serialized_data})
            logger.info(f"📤 ERP PUT response for {issue_data.get('name', 'N/A')}: {response.status_code} - {response.text}")
        else:
            url = erp_url("resource/Issue")
            response = await client.post(url, cookies={"sid": settings.ERP_SID}, json={"data": serialized_data})
            logger.info(f"📤 ERP POST response: {response.status_code} - {response.text}")

        response.raise_for_status()
        return response.json().get("data", {})

async def delete_issue_in_erp(erp_issue_name: str) -> bool:
    if not settings.ERP_API_URL or not settings.ERP_SID:
        logger.error("ERPNext API URL or SID is not configured for deletion.")
        return False

    url = erp_url("resource/Issue", erp_issue_name)
    async with httpx.AsyncClient() as client:
        try:
            response = await client.delete(url, cookies={"sid": settings.ERP_SID})
            response.raise_for_status()
            logger.info(f"✅ Issue {erp_issue_name} deleted successfully in ERPNext.")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to delete issue {erp_issue_name} in ERP: {e}")
            return False

async def fetch_issues_from_erp(start: int, batch_size: int) -> List[Dict[str, Any]]:
    if not settings.ERP_API_URL or not settings.ERP_SID:
        logger.error("ERPNext API URL or SID is not configured.")
        raise HTTPException(status_code=500, detail="ERPNext API not configured.")

    params = f'fields=["name","subject","raised_by","status"]&limit_start={start}&limit_page_length={batch_size}'
    url = erp_url("resource/Issue", params=params)

    async with httpx.AsyncClient() as client:
        response = await client.get(url, cookies={"sid": settings.ERP_SID})
        response.raise_for_status()
        return response.json().get("data", [])

async def get_doctype_count() -> int:
    if not settings.ERP_API_URL or not settings.ERP_SID:
        logger.error("ERPNext API URL or SID is not configured.")
        raise HTTPException(status_code=500, detail="ERPNext API not configured.")

    url = erp_url("method/frappe.client.get_count", params="doctype=DocType")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, cookies={"sid": settings.ERP_SID})
            response.raise_for_status()
            return response.json().get("message", 0)
    except httpx.RequestError as e:
        logger.error(f"🌐 Network error: {e}")
        raise HTTPException(status_code=503, detail=f"ERPNext unreachable: {e}")
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error: {e.response.status_code} - {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)

async def get_doctype_list_from_erp(limit_start: int = 0, limit_page_length: int = 100) -> List[Dict[str, Any]]:
    if not settings.ERP_API_URL or not settings.ERP_SID:
        logger.error("ERPNext API URL or SID is not configured.")
        raise HTTPException(status_code=500, detail="ERPNext API not configured.")

    params = f'doctype=DocType&fields=["name"]&limit_start={limit_start}&limit_page_length={limit_page_length}'
    url = erp_url("method/frappe.client.get_list", params=params)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, cookies={"sid": settings.ERP_SID})
            response.raise_for_status()
            return response.json().get("message", [])
    except Exception as e:
        logger.error(f"❌ Error fetching DocType list: {e}")
        raise HTTPException(status_code=500, detail="Internal error fetching DocType list")

async def get_doctype_schema_from_erp(doctype_name: str) -> Dict[str, Any]:
    if not settings.ERP_API_URL or not settings.ERP_SID:
        logger.error("ERPNext API URL or SID is not configured.")
        raise HTTPException(status_code=500, detail="ERPNext API not configured.")

    url = erp_url("resource/DocType", path=doctype_name)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, cookies={"sid": settings.ERP_SID})
            response.raise_for_status()
            data = response.json().get("data")
            if not data:
                raise HTTPException(status_code=404, detail=f"DocType '{doctype_name}' not found.")
            return data
    except Exception as e:
        logger.error(f"❌ Error fetching DocType schema: {e}")
        raise HTTPException(status_code=500, detail="Internal error fetching DocType schema")
