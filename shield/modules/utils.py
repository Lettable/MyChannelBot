from datetime import datetime, timedelta
import pytz
from pyrogram import Client, enums
import config
from shield import app
from pyrogram.types import ChatMemberUpdated
from shield.database import db

channels = db["channels"]

@app.on_chat_member_updated()
async def trackEvent(client: Client, update: ChatMemberUpdated):
    old = update.old_chat_member
    new = update.new_chat_member
    chat = update.chat

    if not new.user.is_self:
        return
    if chat.type != enums.ChatType.CHANNEL:
        return

    if old.status != enums.ChatMemberStatus.ADMINISTRATOR and \
       new.status == enums.ChatMemberStatus.ADMINISTRATOR:
        inviter = update.from_user

        info = await client.get_chat_member(chat.id, inviter.id)
        if info.status == enums.ChatMemberStatus.OWNER:
            await channels.update_one(
                {"chat_id": chat.id},
                {"$set": {
                    "chat_id":   chat.id,
                    "owner_id":  inviter.id,
                    "title":     chat.title or ""
                }},
                upsert=True
            )
            await app.send_message(
                config.LOG_ID,
                f"✅ Added to channel `{chat.id}` by user {inviter.mention} titled `{chat.title}`"
            )

    elif old.status == enums.ChatMemberStatus.ADMINISTRATOR and \
         new.status != enums.ChatMemberStatus.ADMINISTRATOR:
        await channels.delete_one({"chat_id": chat.id})
        await app.send_message(
            config.LOG_ID,
            f"🗑️ Removed from channel `{chat.id}`"
        )
