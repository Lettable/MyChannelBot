from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message
import config
from shield import app
from shield.database import db
import re
import ipaddress

channels = db["channels"]
captcha = db["captcha"]
channel_configs = db['channel_configs']

admin_states = {}

@app.on_message(filters.private & filters.command("config"))
async def config_handler(client: Client, message):
    user_id = message.from_user.id

    docs = channels.find({"owner_id": user_id}).to_list(length=None)
    if not docs:
        return await message.reply_text("❌ You don’t own any channels where I’m admin.")

    buttons = []
    for d in docs:
        title = d.get("title", "") or str(d["chat_id"])
        label = (title[:7] + "...") if len(title) > 7 else title
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"select_chat_{d['chat_id']}")
        ])

    buttons.append([InlineKeyboardButton("Back", callback_data="back_to_config")])
    markup = InlineKeyboardMarkup(buttons)
    await message.reply_text("Select a channel to configure:", reply_markup=markup)


@app.on_callback_query(filters.regex(r"^select_chat_(-?\d+)$"))
async def select_chat(_, query: CallbackQuery):
    await query.answer()
    chat_id = int(query.data.split('_',2)[2])
    chat = await app.get_chat(chat_id)
    title = chat.title or str(chat_id)

    buttons = [
        [InlineKeyboardButton("Captcha ON", callback_data=f"captcha_on_{chat_id}"),
         InlineKeyboardButton("Captcha OFF", callback_data=f"captcha_off_{chat_id}")],
        [InlineKeyboardButton("Deny Access", callback_data=f"dn_ya_{chat_id}")],
        [InlineKeyboardButton("Back", callback_data="back_to_config")]
    ]
    await query.edit_message_text(
        f"Configure `{title}`",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


@app.on_callback_query(filters.regex(r"^back_to_config$"))
async def back_to_config(client: Client, query: CallbackQuery):
    await config_handler(client, query.message)

def generate_telegram_link(chat_id):
    chat_id_str = str(chat_id)
    if chat_id_str.startswith("-100"):
        chat_id_str = chat_id_str[4:]

    link = f"t.me/{app.me.username}?start=c{chat_id_str}"
    return link

@app.on_callback_query(filters.regex(r"^captcha_on_(-?\d+)$"))
async def captcha_on(client: Client, query: CallbackQuery):
    chat_id = int(query.data.split("_", 2)[2])
    captcha.update_one(
        {"channel_id": chat_id},
        {"$set": {"channel_id": chat_id, "captcha_on": True}},
        upsert=True
    )
    channel_configs.update_one(
        {"channel_id": chat_id},
        {"$set": {"channel_id": chat_id, "owner_id": query.from_user.id, "captcha_on": True}},
        upsert=True
    )
    await query.answer("✅ Captcha enabled")
    await query.edit_message_text(
        f"✅ Captcha is now enabled for: {(await app.get_chat(chat_id)).title or chat_id}\n\n"
        f"🔹 CHAT ID: `{chat_id}`\n"
        f"🔗 LINK: {generate_telegram_link(chat_id)}\n\n"
        f"⚠️ Share this link with users who want to join, instead of the actual group/channel link."
    )


@app.on_callback_query(filters.regex(r"^captcha_off_(-?\d+)$"))
async def captcha_off(client: Client, query: CallbackQuery):
    chat_id = int(query.data.split("_", 2)[2])
    captcha.update_one(
        {"channel_id": chat_id},
        {"$set": {"channel_id": chat_id, "captcha_on": False}},
        upsert=True
    )
    channel_configs.update_one(
        {"channel_id": chat_id},
        {"$set": {"captcha_on": False}},
        upsert=True
    )
    await query.answer("❌ Captcha disabled")
    # await query.edit_message_text(
    #     f"❌ Captcha has been disabled for {(await app.get_chat(chat_id)).title or chat_id}"
    # )


@app.on_callback_query(filters.regex(r"^dn_ya_(-?\d+)$"))
async def deny_access(_, query: CallbackQuery):
    await query.answer()
    chat_id = int(query.data.split("_", 2)[2])
    chat = await app.get_chat(chat_id)
    title = chat.title or str(chat_id)

    admin_states[query.from_user.id] = {}
    buttons = [
        [InlineKeyboardButton("Banned IPs", callback_data=f"ban_ips_{chat_id}"),
         InlineKeyboardButton("Banned IDs", callback_data=f"ban_ids_{chat_id}")],
        [InlineKeyboardButton("Back", callback_data=f"select_chat_{chat_id}")]
    ]
    await query.edit_message_text(
        f"Deny Access Settings for: __{title}__",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_callback_query(filters.regex(r"^ban_ips_(-?\d+)$"))
async def banned_ips(_, query: CallbackQuery):
    await query.answer()
    chat_id = int(query.data.split('_',2)[2])
    chat = await app.get_chat(chat_id)
    title = chat.title or str(chat_id)

    admin_states[query.from_user.id] = {"action": None, "channel_id": chat_id}
    buttons = [
        [InlineKeyboardButton("Add New List", callback_data=f"ban_ipa_{chat_id}" )],
        [InlineKeyboardButton("Append List", callback_data=f"ban_ipap_{chat_id}")],
        [InlineKeyboardButton("Clear List", callback_data=f"ban_ipc_{chat_id}")],
        [InlineKeyboardButton("Back", callback_data=f"dn_ya_{chat_id}")]
    ]
    await query.edit_message_text(
        f"Manage Banned IPs for: __{title}__",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_callback_query(filters.regex(r"^ban_ids_(-?\d+)$"))
async def banned_tgids(_, query: CallbackQuery):
    await query.answer()
    chat_id = int(query.data.split('_',2)[2])
    chat = await app.get_chat(chat_id)
    title = chat.title or str(chat_id)

    admin_states[query.from_user.id] = {"action": None, "channel_id": chat_id}
    buttons = [
        [InlineKeyboardButton("Add New List", callback_data=f"ban_ida_{chat_id}" )],
        [InlineKeyboardButton("Append List", callback_data=f"bani_dap_{chat_id}")],
        [InlineKeyboardButton("Clear List", callback_data=f"ban_idc_{chat_id}")],
        [InlineKeyboardButton("Back", callback_data=f"dn_ya_{chat_id}")]
    ]
    await query.edit_message_text(
        f"Manage Banned IDs for: __{title}__",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_callback_query(filters.regex(r"^ban_ipa_(-?\d+)$"))
async def banned_ips_add(_, query: CallbackQuery):
    chat_id = int(query.data.split('_',2)[2])
    admin_states[query.from_user.id] = {"action": "banned_ips_add", "channel_id": chat_id}
    await query.answer()
    await query.edit_message_text("Send IPs (one per line) to *overwrite* the banned IPs list.")

@app.on_callback_query(filters.regex(r"^ban_ipap_(-?\d+)$"))
async def banned_ips_append(_, query: CallbackQuery):
    chat_id = int(query.data.split('_',2)[2])
    admin_states[query.from_user.id] = {"action": "banned_ips_append", "channel_id": chat_id}
    await query.answer()
    await query.edit_message_text("Send IPs (one per line) to *append* to the banned IPs list.")

@app.on_callback_query(filters.regex(r"^ban_ipc_(-?\d+)$"))
async def banned_ips_clear(_, query: CallbackQuery):
    chat_id = int(query.data.split('_',2)[2])
    channel_configs.update_one({"channel_id": chat_id}, {"$set": {"banned_ips": []}})
    await query.answer("✅ Banned IPs list cleared")
    await banned_ips(_, query)

@app.on_callback_query(filters.regex(r"^ban_ida_(-?\d+)$"))
async def banned_tgids_add(_, query: CallbackQuery):
    chat_id = int(query.data.split('_',2)[2])
    admin_states[query.from_user.id] = {"action": "banned_tgids_add", "channel_id": chat_id}
    await query.answer()
    await query.edit_message_text("Send IDs (one per line) to *overwrite* the banned IDs list.")

@app.on_callback_query(filters.regex(r"^bani_dap_(-?\d+)$"))
async def banned_tgids_append(_, query: CallbackQuery):
    chat_id = int(query.data.split('_',2)[2])
    admin_states[query.from_user.id] = {"action": "banned_tgids_append", "channel_id": chat_id}
    await query.answer()
    await query.edit_message_text("Send IDs (one per line) to *append* to the banned IDs list.")

@app.on_callback_query(filters.regex(r"^ban_idc_(-?\d+)$"))
async def banned_tgids_clear(_, query: CallbackQuery):
    chat_id = int(query.data.split('_',2)[2])
    channel_configs.update_one({"channel_id": chat_id}, {"$set": {"banned_tgids": []}})
    await query.answer("✅ Banned IDs list cleared")
    await banned_tgids(_, query)

@app.on_message(filters.private & ~filters.command("config", "start"))
async def handle_admin_input(client, message: Message):
    state = admin_states.get(message.from_user.id)
    if not state:
        return

    action = state.get("action")
    chat_id = state.get("channel_id")
    lines = message.text.splitlines()

    invalid_inputs = []

    if action in ("banned_ips_add", "banned_ips_append"):
        valid_ips = []
        for line in lines:
            line = line.strip()
            try:
                ip = ipaddress.ip_address(line)
                if ip.version == 4:
                    valid_ips.append(str(ip))
                else:
                    invalid_inputs.append(line)
            except ValueError:
                invalid_inputs.append(line)

        if not valid_ips:
            await message.reply_text("🚫 You absolute donkey, you didn't even give a SINGLE valid IPv4 address. Try again, fuckface.")
            return

        if action == "banned_ips_add":
            new_list = valid_ips
        else:
            cfg = channel_configs.find_one({"channel_id": chat_id}) or {}
            old = cfg.get("banned_ips", [])
            new_list = old + valid_ips

        channel_configs.update_one({"channel_id": chat_id}, {"$set": {"banned_ips": new_list}}, upsert=True)
        await message.reply_text(f"✅ Banned IPs updated. {len(valid_ips)} added.")

    if action in ("banned_tgids_add", "banned_tgids_append"):
        valid_ids = []
        for line in lines:
            line = line.strip()
            if line.isdigit() and 1 <= len(line) <= 15:
                valid_ids.append(int(line))
            else:
                invalid_inputs.append(line)

        if not valid_ids:
            await message.reply_text("🚫 How the fuck did you manage to NOT send a SINGLE valid Telegram ID? Fix your life.")
            return

        if action == "banned_tgids_add":
            new_ids = valid_ids
        else:
            cfg = channel_configs.find_one({"channel_id": chat_id}) or {}
            old = cfg.get("banned_tgids", [])
            new_ids = old + valid_ids

        channel_configs.update_one({"channel_id": chat_id}, {"$set": {"banned_tgids": new_ids}}, upsert=True)
        await message.reply_text(f"✅ Banned IDs updated. {len(valid_ids)} added.")

    if invalid_inputs:
        msg = "**👿 Invalid Inputs Detected!**\n\n"
        for trash in invalid_inputs:
            msg += f"❌ `{trash}` — what the actual fuck is this?\n"
        msg += "\n🔴 Send proper IPv4 addresses or numeric Telegram IDs, you walking brainfart."
        await message.reply_text(msg)

    admin_states.pop(message.from_user.id, None)
