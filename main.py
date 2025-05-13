<<<<<<< HEAD
from fastapi import FastAPI
from models.issue import IssueEntry
from database import issues_collection
from pydantic import BaseModel
from datetime import datetime
from typing import List
import httpx, os
from dotenv import load_dotenv
from bson import ObjectId
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging
from httpx import RequestError
# Load environment variables
load_dotenv()

# FastAPI app
app = FastAPI()

# ERP and MongoDB config
ERP_API_URL = "https://erp.kisanmitra.net/api/resource/Issue"
COOKIES = {"sid": os.getenv("ERP_SID")}

# Logger setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# APScheduler
scheduler = AsyncIOScheduler()

# 🔧 Handle datetime serialization
def serialize_for_erp(data: dict) -> dict:
    for key, value in data.items():
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return data

# 🔁 Shared sync function
# 🔁 Shared sync function with detailed logging
async def sync_pending_issues_task():
    synced_count = 0
    unsynced_cursor = issues_collection.find({"synced": False})

    # Log number of pending issues
    pending_issues = await unsynced_cursor.to_list(length=None)
    logger.info(f"Found {len(pending_issues)} pending issues.")

    for issue in pending_issues:
        issue_id = issue["_id"]
        logger.info(f"🔄 Syncing issue: {issue_id}")
        
        issue_data = {
            "subject": issue["subject"],
            "raised_by": issue["raised_by"],
            "status": issue["status"].capitalize()  # ensure "Open" not "open"
        }

        try:
            serialized_data = serialize_for_erp(issue_data)

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    ERP_API_URL,
                    cookies=COOKIES,
                    json={"data": serialized_data}
                )
                logger.info(f"📤 ERP response for {issue_id}: {response.status_code} - {response.text}")
                response.raise_for_status()

            await issues_collection.update_one(
                {"_id": issue_id},
                {"$set": {"synced": True, "synced_at": datetime.utcnow()}}
            )
            synced_count += 1
            logger.info(f"✅ Issue {issue_id} synced successfully.")

        except httpx.RequestError as re:
            logger.error(f"🌐 Request error while syncing {issue_id}: {re}")
        except Exception as e:
            logger.error(f"❌ Failed to sync issue {issue_id}: {e}")

    return synced_count


# 🔃 Run on startup
@app.on_event("startup")
async def startup_event():
    await issues_collection.create_index("created_at")
    await issues_collection.create_index("synced")

    # Schedule background sync every 5 minutes
    scheduler.add_job(sync_pending_issues_task, IntervalTrigger(minutes=5))
    scheduler.start()
    logger.info("🔁 Background sync scheduler started.")

# 📥 Submit Issue
@app.post("/submit-issue")
async def submit_issue(issue: IssueEntry):
    issue_data = issue.dict()
    issue_data["created_at"] = datetime.utcnow()

    try:
        serialized_data = serialize_for_erp(issue_data)

        async with httpx.AsyncClient() as client:
            response = await client.post(ERP_API_URL, cookies=COOKIES, json={"data": serialized_data})
            response.raise_for_status()
        
        issue_data["synced"] = True
        issue_data["synced_at"] = datetime.utcnow()

    except RequestError as e:
        print(f"[Offline] ERP unreachable: {e}")
        issue_data["synced"] = False
        issue_data["synced_at"] = None

    except Exception as e:
        print(f"[Error] Unexpected: {e}")
        issue_data["synced"] = False
        issue_data["synced_at"] = None

    await issues_collection.insert_one(issue_data)
    return {"status": "stored", "synced": issue_data["synced"]}

# 🧾 Get unsynced issues
@app.get("/unsynced-issues")
async def get_unsynced():
    issues = await issues_collection.find({"synced": False}).to_list(100)
    for issue in issues:
        issue["_id"] = str(issue["_id"])
    return issues

# 🔄 Manual Sync Trigger
@app.post("/sync-pending")
async def sync_pending():
    synced = await sync_pending_issues_task()
    return {"status": f"Manual sync attempt completed. Synced {synced} issues."}
# ✅ Get synced issues
@app.get("/synced-issues")
async def get_synced_issues():
    issues = await issues_collection.find({"synced": True}).to_list(100)
    for issue in issues:
        issue["_id"] = str(issue["_id"])  # Convert ObjectId to string
    return issues

=======
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from database import issues_collection
import httpx
import os
from dotenv import load_dotenv

app = FastAPI()
load_dotenv()

ERP_API_URL = "https://erp.kisanmitra.net/api/resource/Issue"
COOKIES = {
    "sid": os.getenv("ERP_SID")
}

# Fetch and Insert Endpoint
@app.get("/fetch-all")
async def fetch_all_and_insert():
    batch_size = 500
    inserted_total = 0
    updated_total = 0
    failed_batches = []

    async with httpx.AsyncClient() as client:
        for start in range(0, 35000, batch_size):
            url = (
                f"{ERP_API_URL}"
                f"?fields=[\"name\",\"subject\",\"raised_by\"]"
                f"&limit_start={start}&limit_page_length={batch_size}"
            )

            try:
                response = await client.get(url, cookies=COOKIES)
                if response.status_code != 200:
                    failed_batches.append({"start": start, "status": response.status_code})
                    break

                batch = response.json().get("data", [])
                if not batch:
                    break

                for issue in batch:
                    result = await issues_collection.update_one(
                        {"name": issue["name"]},
                        {"$set": issue},
                        upsert=True
                    )
                    if result.upserted_id:
                        inserted_total += 1
                    elif result.modified_count > 0:
                        updated_total += 1

            except Exception as e:
                failed_batches.append({"start": start, "error": str(e)})
                continue

    return {
        "inserted_total": inserted_total,
        "updated_total": updated_total,
        "failed_batches": failed_batches
    }

@app.delete("/delete-issues")
async def delete_issues():
    result = await issues_collection.delete_many({})
    return {"deleted_count": result.deleted_count}


# ----------------------- CRUD Operations -----------------------

class Issue(BaseModel):
    name: str
    subject: str
    raised_by: Optional[str] = None
    #status: Optional[str] = None
    #km_state_case: Optional[str] = None
    #km_district_case: Optional[str] = None
    #km_mandal_case: Optional[str] = None
    #km_village_case: Optional[str] = None
    #raised_by_phone: Optional[str] = None

@app.get("/issues", response_model=List[Issue])
async def get_all_issues():
    issues = await issues_collection.find().to_list(length=100)
    return issues

@app.get("/issues/{name}", response_model=Issue)
async def get_issue(name: str):
    issue = await issues_collection.find_one({"name": name})
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue

@app.post("/issues", response_model=Issue)
async def create_issue(issue: Issue):
    await issues_collection.insert_one(issue.dict())
    return issue

@app.put("/issues/{name}", response_model=Issue)
async def update_issue(name: str, updated_issue: Issue):
    result = await issues_collection.replace_one({"name": name}, updated_issue.dict())
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Issue not found")
    return updated_issue

@app.delete("/issues/{name}")
async def delete_issue(name: str):
    result = await issues_collection.delete_one({"name": name})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Issue not found")
    return {"message": f"Issue '{name}' deleted successfully"}
>>>>>>> efdb084018bed60b255789dd4ab79a365e276a72

