import certifi
from motor.motor_asyncio import AsyncIOMotorClient
import config

mongo = AsyncIOMotorClient(
    config.MONGO_DB_URI,
    tls=True,
    tlsAllowInvalidCertificates=True,
    tlsAllowInvalidHostnames=True
)

db = mongo["MAIN"]
