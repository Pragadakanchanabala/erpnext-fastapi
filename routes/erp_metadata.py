from fastapi import APIRouter, HTTPException, status
from typing import List
import logging
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
