from os import getenv

API_ID = int(getenv("API_ID", ))
API_HASH = str(getenv("API_HASH", ""))
BOT_TOKEN = str(getenv("BOT_TOKEN", ""))
SUDOERS = list(map(int, getenv("SUDOERS", "").split()))
MONGO_DB_URI = str(getenv("MONGO_DB_URI", ""))
LOG_ID = str(getenv("LOG_ID", ""))
START_IMG = str(getenv("START_IMG", ""))