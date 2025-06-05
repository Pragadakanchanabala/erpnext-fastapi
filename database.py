import os
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ConnectionFailure
from config import settings
from typing import Optional

# Global client and database instances
client: Optional[AsyncIOMotorClient] = None
db: Optional[AsyncIOMotorDatabase] = None

async def connect_to_mongo():
    """
    Establishes an asynchronous connection to MongoDB using Motor.
    """
    global client, db
    try:
        # Use MONGO_DB_URL from settings
        client = AsyncIOMotorClient(settings.MONGO_DB_URL)
        # Use MONGO_DB_NAME from settings
        db = client[settings.MONGO_DB_NAME]
        # The ping command is cheap and does not require auth, useful for connection test
        await client.admin.command('ping')
        print(f"MongoDB connected successfully to database '{settings.MONGO_DB_NAME}'!")
    except ConnectionFailure as e:
        print(f"MongoDB connection failed: {e}")
        client = None
        db = None
        raise # Re-raise the exception to indicate connection failure

async def close_mongo_connection():
    """
    Closes the MongoDB connection.
    """
    global client, db
    if client:
        client.close()
        print("MongoDB connection closed.")
    client = None
    db = None

def get_database() -> AsyncIOMotorDatabase:
    """
    Returns the MongoDB database instance. Raises an error if not connected.
    """
    if db is None:
        raise ConnectionFailure("MongoDB connection not established. Call connect_to_mongo() first.")
    return db

def get_issues_collection():
    """
    Returns the 'issues' collection.
    """
    if db is None: # Check if db is initialized
        raise ConnectionFailure("MongoDB database not initialized. Cannot get 'issues' collection.")
    return db.issues # Directly return the collection from the global db object
