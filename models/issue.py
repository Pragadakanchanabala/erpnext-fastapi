from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class IssueEntry(BaseModel):
    """
    Pydantic model representing an issue entry in MongoDB.
    Includes fields for synchronization status with ERPNext.
    """
    # Unique identifier from ERPNext (if synced)
    name: Optional[str] = None # 'name' field is ERPNext's primary key for a DocType

    subject: str
    raised_by: str
    status: Optional[str] = None # Made status optional to handle missing data from ERPNext
    created_at: Optional[datetime] = None # Timestamp of creation in FastAPI
    synced: bool = False # Flag indicating if the issue has been successfully synced with ERPNext
    synced_at: Optional[datetime] = None # Timestamp of last successful sync with ERPNext

    class Config:
        # Allows Pydantic to handle non-dict inputs, e.g., MongoDB ObjectId
        arbitrary_types_allowed = True
        # Aliases for field names (e.g., '_id' in MongoDB to 'id' in Pydantic)
        json_encoders = {datetime: lambda dt: dt.isoformat()} # Ensure datetime is ISO formatted
        # Allow population by field name or alias for MongoDB compatibility
        populate_by_name = True
