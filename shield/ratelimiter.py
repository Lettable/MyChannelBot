import asyncio
from pyrogram import filters
from pyrogram.errors import MessageDeleteForbidden
from promo.modules.sudo import sudo_users

sudo_user_documents = sudo_users.find({})
SUDO = [doc["user_id"] for doc in sudo_user_documents]

data = {}

async def task(message, warn=False, sec=None):
    if warn:
        user = message.from_user or message.sender_chat
        aos = await message.reply(
            f"**You Must Wait For {sec} Seconds Cooldown Before Using Again...**"
        )
        
        await asyncio.sleep(sec)
        await aos.edit(
            f"**Alright Cooldown Over !**"
        )

def wait(sec):
    async def ___(flt, _, message):
        user_id = message.from_user.id if message.from_user else message.sender_chat.id
        if user_id in data:
            if message.date.timestamp() >= data[user_id]["timestamp"] + flt.data:
                data[user_id] = {"timestamp": message.date.timestamp(), "warned": False}
                return True
            else:
                if not data[user_id]["warned"]:
                    data[user_id]["warned"] = True
                    asyncio.ensure_future(
                        task(message, True, flt.data)
                    )
                    return False  #Cause we dont need delete again !

                asyncio.ensure_future(task(message))
                return False
        else:
            data.update({user_id: {"timestamp": message.date.timestamp(), "warned": False}})
            return True

    return filters.create(___, data=sec)
