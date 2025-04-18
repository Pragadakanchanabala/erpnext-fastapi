
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI="mongodb+srv://<username>:<password>@cluster0.d2nmvpn.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

client = AsyncIOMotorClient(MONGO_URI)

db = client.kisanmitra
issues_collection = db.issues




