from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class IssueCreate(BaseModel):
    """
    Pydantic model for creating a new issue.
    Contains only the fields a user should provide.
    """
    subject: str
    raised_by: str
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
        - `populate_by_name`: Allows creating the model using either field name or alias (e.g., 'id' or '_id').
        - `arbitrary_types_allowed`: Allows handling types like MongoDB's ObjectId.
        - `json_encoders`: Ensures datetime objects are converted to ISO 8601 string format in JSON.
        """
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {datetime: lambda dt: dt.isoformat()}