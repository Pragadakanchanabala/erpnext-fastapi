from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime

class DocTypeListItem(BaseModel):
    """Schema for a simplified DocType list item."""
    name: str

class FieldSchema(BaseModel):
    """Schema for a field within a DocType."""
    field_name: str
    input_type: str # Corresponds to 'fieldtype' in Frappe

class DocTypeSchema(BaseModel):
    """Schema for a full DocType definition."""
    doctype_name: str
    last_modified: datetime
    fields: List[FieldSchema]

    class Config:
        json_encoders = {datetime: lambda dt: dt.isoformat()}
        arbitrary_types_allowed = True # Allow non-Pydantic types if needed (e.g. for internal Frappe objects)
