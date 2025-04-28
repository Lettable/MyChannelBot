from os import getenv

API_ID = int(getenv("API_ID", 23129036))
API_HASH = str(getenv("API_HASH", "34efb38c74d5e6b25d1bb6234396a8af"))
BOT_TOKEN = str(getenv("BOT_TOKEN", "7200600693:AAHSOpMY6lZmn4EfDQf_EAjPRmlGc1akclM"))
SUDOERS = list(map(int, getenv("SUDOERS", "6586350542 7208410467 6717765982 5896960462").split()))
MONGO_DB_URI = str(getenv("MONGO_DB_URI", "mongodb+srv://nigga:nigga@cluster0.kz8dnb3.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"))
LOG_ID = str(getenv("LOG_ID", "-1002519094633"))
START_IMG = str(getenv("START_IMG", "https://i.ibb.co/LDNRYXyD/photo-2025-04-24-14-22-18-1.jpg"))