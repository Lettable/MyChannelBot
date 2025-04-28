from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
import config
from shield import app
from shield.database import db

channels = db["channels"]
captcha = db["captcha"]

@app.on_message(filters.private & filters.command("config"))
async def config_handler(client: Client, message):
    user_id = message.from_user.id

    docs = await channels.find({"owner_id": user_id}).to_list(length=None)
    if not docs:
        return await message.reply_text("❌ You don’t own any channels where I’m admin.")

    buttons = []
    for d in docs:
        title = d.get("title", "") or str(d["chat_id"])
        label = (title[:7] + "...") if len(title) > 7 else title
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"select_chat_{d['chat_id']}")
        ])

    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_config")])
    markup = InlineKeyboardMarkup(buttons)
    await message.reply_text("Select a channel to configure:", reply_markup=markup)


@app.on_callback_query(filters.regex(r"^select_chat_(\d+)$"))
async def select_chat(client: Client, query: CallbackQuery):
    chat_id = int(query.data.split("_")[2])
    try:
        chat = await app.get_chat(chat_id)
        title = chat.title or str(chat.id)
    except:
        title = str(chat_id)

    buttons = [
        [
            InlineKeyboardButton("Captcha ON",  callback_data=f"captcha_on_{chat_id}"),
            InlineKeyboardButton("Captcha OFF", callback_data=f"captcha_off_{chat_id}")
        ],
        [InlineKeyboardButton("Back", callback_data="back_to_config")]
    ]
    markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text(
        f"*Configure Captcha for:* __{title}__",
        reply_markup=markup,
        parse_mode="markdown"
    )


@app.on_callback_query(filters.regex(r"^back_to_config$"))
async def back_to_config(client: Client, query: CallbackQuery):
    await config_handler(client, query.message)


@app.on_callback_query(filters.regex(r"^captcha_on_(\d+)$"))
async def captcha_on(client: Client, query: CallbackQuery):
    chat_id = int(query.data.split("_")[2])
    await captcha.update_one(
        {"channel_id": chat_id},
        {"$set": {"channel_id": chat_id, "captcha_on": True}},
        upsert=True
    )
    await query.answer("✅ Captcha enabled")
    await query.edit_message_text(
        f"✅ Captcha has been *enabled* for __{(await app.get_chat(chat_id)).title or chat_id}__",
        parse_mode="markdown"
    )


@app.on_callback_query(filters.regex(r"^captcha_off_(\d+)$"))
async def captcha_off(client: Client, query: CallbackQuery):
    chat_id = int(query.data.split("_")[2])
    await captcha.update_one(
        {"channel_id": chat_id},
        {"$set": {"channel_id": chat_id, "captcha_on": False}},
        upsert=True
    )
    await query.answer("❌ Captcha disabled")
    await query.edit_message_text(
        f"❌ Captcha has been *disabled* for __{(await app.get_chat(chat_id)).title or chat_id}__",
        parse_mode="markdown"
    )





