import asyncio
import logging
import time
from pyrogram import Client, filters
from pyrogram.errors import PeerIdInvalid, ChannelInvalid, FloodWait
from pyrogram.types import BotCommand
from config import API_ID, API_HASH, BOT_TOKEN
import config

logging.basicConfig(
    format="[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s",
    level=logging.INFO,
    datefmt="%d-%b-%y %H:%M:%S",
)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
LOGGER = logging.getLogger(__name__)

app = Client(
    "Sheild",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

boot = time.time()
async def austinOG():
    try:
        await app.start()
        await asyncio.sleep(2)
    except FloodWait as ex:
        LOGGER.warning(ex)
        await asyncio.sleep(ex.value)

    print(1)
    try:
        LOGGER.info(f"Bot Started As {app.me.first_name}")
    except Exception as e:
        print(e)
        exit()

    from shield.modules.site import app as flask_app
    import threading
    threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=5679)).start()

asyncio.get_event_loop().run_until_complete(austinOG())
