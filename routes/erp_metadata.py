from fastapi import APIRouter, HTTPException, status
from typing import List
import logging
import httpx
from datetime import datetime # Needed for timestamp conversion

from models.erp_schemas import DocTypeListItem, DocTypeSchema, FieldSchema
from services import erp_service # Only need erp_service for metadata fetching

router = APIRouter(prefix="/metadata", tags=["ERPNext Metadata"])

logger = logging.getLogger(__name__)

@router.get("/doctypes", response_model=List[DocTypeListItem], summary="Get a list of all ERPNext DocType names")
async def get_all_doctypes():
    """
    Fetches the count and then the full list of DocType names from ERPNext.
    """
    try:
        # Step 1: Get the total count of DocTypes
        total_doctypes = await erp_service.get_doctype_count()
        if total_doctypes == 0:
            return []

        all_doctype_names = []
        limit_page_length = 500 # Fetch in batches
        
        # Step 2: Fetch all DocType names in batches
        for start in range(0, total_doctypes, limit_page_length):
            batch = await erp_service.get_doctype_list_from_erp(start, limit_page_length)
            for item in batch:
                if "name" in item:
                    all_doctype_names.append(DocTypeListItem(name=item["name"]))
                else:
                    logger.warning(f"DocType list item missing 'name' field: {item}")
        
        logger.info(f"Successfully fetched {len(all_doctype_names)} DocTypes from ERPNext.")
        return all_doctype_names

    except HTTPException as e:
        logger.error(f"Error fetching DocType list: {e.detail}")
        raise e
    except Exception as e:
        logger.error(f"Unexpected error fetching DocType list: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to fetch DocType list: {e}")
@router.get("/metadata/doctype/{doctype_name}")
async def get_doctype_metadata(doctype_name: str):
    """
    Fetches DocType metadata from ERPNext and transforms it into simplified schema
    for frontend dynamic form rendering.
    """
    url = f"{settings.ERP_API_URL}/resource/DocType/{doctype_name}"
    headers = {"Cookie": f"sid={settings.ERP_SID}"}

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch DocType metadata")

    data = response.json().get("data")
    if not data:
        raise HTTPException(status_code=500, detail="Invalid response from ERP")

    doctype_schema = {
        "doctype_name": data.get("name"),
        "last_modified": data.get("modified"),
        "fields": [
            {
                "field_name": field.get("fieldname"),
                "input_type": field.get("fieldtype")
            }
            for field in data.get("fields", [])
            if field.get("fieldname") and field.get("fieldtype")
        ]
    }

    return doctype_schema

@router.get("/doctype/{doctype_name}", response_model=DocTypeSchema, summary="Get the schema (field definitions) for a specific ERPNext DocType")
async def get_doctype_schema(doctype_name: str):
    """
    Fetches the full definition (schema) for a given DocType from ERPNext.
    """
    try:
        raw_doctype_data = await erp_service.get_doctype_schema_from_erp(doctype_name)

        # Parse fields from the raw DocType data
        fields = []
        for field in raw_doctype_data.get("fields", []):
            if "fieldname" in field and "fieldtype" in field:
                fields.append(FieldSchema(
                    field_name=field["fieldname"],
                    input_type=field["fieldtype"]
                ))
            else:
                logger.warning(f"DocType '{doctype_name}' field missing 'fieldname' or 'fieldtype': {field}")
        
        # Ensure 'modified' field (last_modified) is present and can be converted
        last_modified_str = raw_doctype_data.get("modified")
        last_modified_dt = None
        if last_modified_str:
            try:
                # Assuming ISO format like "YYYY-MM-DD HH:MM:SS.microseconds" or similar
                # Frappe uses UTC, so it's good to be explicit
                last_modified_dt = datetime.fromisoformat(last_modified_str.replace("Z", "+00:00")) # Handle Z suffix
            except ValueError:
                logger.warning(f"Could not parse 'modified' timestamp for DocType '{doctype_name}': {last_modified_str}")
                # Fallback to current time or None if parsing fails
                last_modified_dt = datetime.now(datetime.timezone.utc)
        else:
            logger.warning(f"No 'modified' timestamp found for DocType '{doctype_name}'.")
            last_modified_dt = datetime.now(datetime.timezone.utc)


        return DocTypeSchema(
            doctype_name=doctype_name,
            last_modified=last_modified_dt,
            fields=fields
        )

    except HTTPException as e:
        logger.error(f"Error fetching schema for {doctype_name}: {e.detail}")
        raise e
    except Exception as e:
        logger.error(f"Unexpected error fetching schema for {doctype_name}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to fetch schema: {e}")
@router.get("/erp", summary="Check if ERP server is reachable")
async def check_erp_connectivity():
    """
    Checks if the ERPNext server is reachable by attempting to access its base URL.
    This does not require authentication.
    """
    # Construct the base URL from ERP_API_URL by removing the resource part
    base_erp_url = "https://erp.kisanmitra.net/" # Direct base URL
    
    try:
        async with httpx.AsyncClient() as client:
            # Use the base URL for a simple connectivity check
            response = await client.get(base_erp_url, timeout=5)
            # We are checking for *any* successful response from the server, even a redirect or login page
            if response.is_success or response.is_redirect:
                return {"status": "online", "message": "ERP server is reachable"}
            else:
                # If it's not a success or redirect (e.g., 4xx, 5xx other than connection error)
                return {"status": "offline", "message": f"ERP server returned status {response.status_code}"}
    except httpx.RequestError as e:
        # Catch network-related errors specifically
        logger.error(f"Network error checking ERP connectivity: {e}")
        return {"status": "offline", "message": f"ERP server is not reachable: {e}"}
    except Exception as e:
        # Catch any other unexpected errors
        logger.error(f"Unexpected error checking ERP connectivity: {e}")
        return {"status": "offline", "message": f"An unexpected error occurred: {e}"}

