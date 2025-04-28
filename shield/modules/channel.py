from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message
import config
from shield import app
from shield.database import db

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
        f"✅ Captcha has been enabled for {(await app.get_chat(chat_id)).title or chat_id}"
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
    await query.edit_message_text(
        f"❌ Captcha has been disabled for {(await app.get_chat(chat_id)).title or chat_id}"
    )


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
    if action in ("banned_ips_add", "banned_ips_append"):
        if action == "banned_ips_add":
            new_list = lines
        else:
            cfg = channel_configs.find_one({"channel_id": chat_id})
            old = cfg.get("banned_ips", [])
            new_list = old + lines
        channel_configs.update_one({"channel_id": chat_id}, {"$set": {"banned_ips": new_list}}, upsert=True)
        await message.reply_text("✅ Banned IPs updated.")
        admin_states.pop(message.from_user.id, None)
    if action in ("banned_tgids_add", "banned_tgids_append"):
        ids = [int(x) for x in lines if x.isdigit()]
        if action == "banned_tgids_add":
            new_ids = ids
        else:
            cfg = channel_configs.find_one({"channel_id": chat_id})
            old = cfg.get("banned_tgids", [])
            new_ids = old + ids
        channel_configs.update_one({"channel_id": chat_id}, {"$set": {"banned_tgids": new_ids}}, upsert=True)
        await message.reply_text("✅ Banned IDs updated.")
        admin_states.pop(message.from_user.id, None)
