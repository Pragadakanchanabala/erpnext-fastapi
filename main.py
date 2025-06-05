from fastapi import FastAPI, HTTPException, status
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Import settings and database functions
from config import settings
from database import connect_to_mongo, close_mongo_connection, get_database, get_issues_collection

# Import routers
from routes import auth, issues # Import the routers from the new files
from routes.issues import sync_pending_issues_task # Import the task directly for scheduler

# FastAPI app
app = FastAPI(title="ERPNext FastAPI Bridge")

# Logger setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# APScheduler instance
scheduler = AsyncIOScheduler()

# Include routers
app.include_router(auth.router)
app.include_router(issues.router) # Issues routes will be under /issues by default due to prefix in router

# Startup event: Connect to MongoDB, ensure indexes, start scheduler
@app.on_event("startup")
async def startup_event():
    await connect_to_mongo() # Establish MongoDB connection

    # Get the collections for indexing after connection is established
    issues_coll = get_issues_collection()
    users_coll = get_database()["users"]

    # Create indexes (if not already created)
    await issues_coll.create_index("created_at")
    await issues_coll.create_index("synced")
    await users_coll.create_index("google_id", unique=True)
    logger.info("MongoDB indexes ensured.")

    # Start the background sync scheduler
    # Use the sync_pending_issues_task from the issues router module
    scheduler.add_job(sync_pending_issues_task, 'interval', minutes=5)
    scheduler.start()
    logger.info("🔁 Background sync scheduler started.")

# Shutdown event: Shut down scheduler, close MongoDB connection
@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown()
    logger.info("🔁 Background sync scheduler stopped.")
    await close_mongo_connection()

# You can keep a simple root endpoint or remove it if not needed
@app.get("/", summary="Root endpoint")
async def root():
    return {"message": "Welcome to ERPNext FastAPI Bridge! Check /docs for API endpoints."}
