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

