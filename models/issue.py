from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class IssueEntry(BaseModel):
    subject: str
    raised_by: str
    status: Optional[str] = None  # <--- THIS IS THE CRUCIAL CHANGE: Made status optional
    created_at: Optional[datetime] = None
    synced: bool = False
    synced_at: Optional[datetime] = None
