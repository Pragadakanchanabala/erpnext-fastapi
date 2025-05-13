<<<<<<< HEAD
import os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

MONGO_URI="mongodb+srv://pragadakanchana:Kanchana01p@cluster0.d2nmvpn.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
=======

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI="mongodb+srv://<username>:<password>@cluster0.d2nmvpn.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
>>>>>>> efdb084018bed60b255789dd4ab79a365e276a72

client = AsyncIOMotorClient(MONGO_URI)

db = client.kisanmitra
issues_collection = db.issues




