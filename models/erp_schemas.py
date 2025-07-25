# File: models/erp_schemas.py
from pydantic import BaseModel
from typing import List, Optional

class DocTypeListItem(BaseModel):
    """Schema for a simplified DocType list item from ERPNext."""
    name: str

class FieldSchema(BaseModel):
    """Schema for a single field within a DocType."""
    fieldname: str
    fieldtype: str
    label: str
    options: Optional[str] = None
    reqd: int = 0 # Is the field required? (1 for yes, 0 for no)

class DocTypeSchema(BaseModel):
    """Schema for a full DocType definition, used for dynamic form generation."""
    name: str
    fields: List[FieldSchema]