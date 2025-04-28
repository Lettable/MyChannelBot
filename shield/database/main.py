
import config
from pymongo import MongoClient

mongo = MongoClient(config.MONGO_DB_URI)

db = mongo["MAIN"]
