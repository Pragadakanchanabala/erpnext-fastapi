import os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

MONGO_URI="mongodb+srv://pragadakanchana:Kanchana01p@cluster0.d2nmvpn.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

client = AsyncIOMotorClient(MONGO_URI)

db = client.kisanmitra
issues_collection = db.issues




