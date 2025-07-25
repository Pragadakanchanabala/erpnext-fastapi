from fastapi import APIRouter
from utils.network import is_internet_connected

router = APIRouter(prefix="/health", tags=["Health Check"])

@router.get("/internet", summary="Check if internet is connected")
async def check_internet():
    if is_internet_connected():
        return {"status": "online", "message": "Internet connection is active"}
    else:
        return {"status": "offline", "message": "Internet connection is not available"}
