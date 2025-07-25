# File: models/issue.py

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class IssueCreate(BaseModel):
    """
    Pydantic model for creating a new issue.
    Contains only the fields a user should provide.
    """
    subject: str
    raised_by: Optional[str] = None # <-- This is the required change
    status: str = "Open"

class IssueEntry(IssueCreate):
    """
    Pydantic model representing a full issue entry in MongoDB.
    Includes both user-provided fields and server-generated sync/ID fields.
    """
    id: Optional[str] = Field(alias="_id", default=None)
    name: Optional[str] = None # This is the ID from ERPNext, e.g., 'KM-19444'
    created_at: Optional[datetime] = None
    synced: bool = False
    synced_at: Optional[datetime] = None

    class Config:
        """
        Pydantic model configuration.
        """
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {datetime: lambda dt: dt.isoformat()}