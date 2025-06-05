from fastapi import FastAPI, HTTPException, status
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger # Import IntervalTrigger explicitly

# Import settings and database functions
from config import settings
from database import connect_to_mongo, close_mongo_connection, get_database, get_issues_collection

# Import routers
from routes import auth, issues # Import the routers from the new files
from services.sync_service import sync_pending_issues_task # Corrected import path for the task

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
    """
    Handles startup events for the FastAPI application.
    Connects to MongoDB, ensures necessary indexes, and starts the background scheduler.
    """
    await connect_to_mongo() # Establish MongoDB connection

    # Get the collections for indexing after connection is established
    issues_coll = get_issues_collection()
    users_coll = get_database()["users"]

    # Create indexes (if not already created) for efficient querying
    await issues_coll.create_index("created_at")
    await issues_coll.create_index("synced")
    await users_coll.create_index("google_id", unique=True)
    logger.info("MongoDB indexes ensured.")

    # Start the background sync scheduler to periodically sync pending issues
    # Using a faster interval (e.g., 1 minute) for more "real-time" sync simulation
    scheduler.add_job(sync_pending_issues_task, IntervalTrigger(minutes=1))
    scheduler.start()
    logger.info("🔁 Background sync scheduler started.")

# Shutdown event: Shut down scheduler, close MongoDB connection
@app.on_event("shutdown")
async def shutdown_event():
    """
    Handles shutdown events for the FastAPI application.
    Shuts down the scheduler and closes the MongoDB connection.
    """
    scheduler.shutdown()
    logger.info("🔁 Background sync scheduler stopped.")
    await close_mongo_connection()

# Root endpoint for basic application check
@app.get("/", summary="Root endpoint")
async def root():
    """
    A simple root endpoint to confirm the application is running.
    """
    return {"message": "Welcome to ERPNext FastAPI Bridge! Check /docs for API endpoints."}
