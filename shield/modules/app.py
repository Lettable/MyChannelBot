import config
from pyrogram import filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from shield import app
from shield.database import db

users = db['users']
invite_requests = db['invite_requests']
channel_configs = db['channel_configs']

start_button = InlineKeyboardMarkup([
    [InlineKeyboardButton(text='Add me', url=f't.me/{app.me.username}?startgroup=true')],
    [InlineKeyboardButton(text='Help', callback_data='help_cb_fuck'),
     InlineKeyboardButton(text='Privacy Policy', callback_data='pp_cb_fuck')]
])


@app.on_message(filters.command('start') & filters.private)
async def startcmd(_, message: Message):
    user_id = message.from_user.id
    user_mention = message.from_user.mention
    payload = message.command[1] if len(message.command) > 1 else None

    if not payload or not payload.startswith('c'):
        await users.update_one(
            {"user_id": user_id},
            {"$set": {"user_id": user_id}},
            upsert=true
        )
        
        await message.reply_photo(
            config.START_IMG,
            caption = (
                f"Hello {user_mention}, welcome to {app.me.mention}!\n\n"
                f"➻ Your ultimate tool for managing and protecting your Telegram spaces.\n"
                f"──────────────────\n"
                f"➻ Press 'Help' to discover all available features."
            ),
            reply_markup=start_button
        )

    chan_short = int(payload[1:])
    channel_id = -100 * (10**len(str(chan_short))) + chan_short
    cfg = channel_configs.find_one({"channel_id": channel_id})
    if not cfg or not cfg.get("captcha_on"):
        return await message.reply_text("⚠️ That channel is not currently protected.")

    now = datetime.utcnow()
    uid = hashlib.sha1(f"{now.timestamp()}_{message.from_user.id}_{channel_id}".encode()).hexdigest()
    entry = {
      "uid":        uid,
      "channel_id": channel_id,
      "owner_id":   cfg["owner_id"],
      "requester":  message.from_user.id,
      "created_at": now,
      "expires_at": now + timedelta(hours=1),
      "used":       False,
      "invite_link": None
    }
    await invite_requests.insert_one(entry)

    try:
        omg = await app.get_chat(channel_id)
    except Exception as e:
        print('Error while getting channel', e)

    await app.send_message(
      cfg["owner_id"],
      f"🔔 New access request for `{omg.title}`\n"
      f"User: {message.from_user.mention}\n"
      f"EID: `{uid}`\n"
      f"Time: {now.isoformat()}",
      parse_mode="markdown"
    )

    verify_url = f"https://your.site/verify?uid={uid}"
    await message.reply_photo(
      photo=config.VERIFY_IMG,
      caption=(
        "🔒 **Access Verification Required**\n\n"
        "To join, please complete the CAPTCHA below."
      ),
      reply_markup=InlineKeyboardMarkup([[
        InlineKeyboardButton("🔗 Verify Now", url=verify_url)
      ]])
    )

@app.on_callback_query(filters.regex('help_cb_fuck'))
async def help_callback(_, query: CallbackQuery):
    text = (
        "🛠 **Help Menu**\n\n"
        "These are the available commands:\n\n"
        "➻ /config : to list all channels where bot is admin\n\n"
    )

    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(text='Back', callback_data='back_cb_fuck')]
    ])

    await query.edit_message_text(text=text, reply_markup=reply_markup)


@app.on_callback_query(filters.regex('pp_cb_fuck'))
async def privacy_policy(_, query: CallbackQuery):
    text = (
        "**Privacy Policy**\n\n"
        "We respect your privacy and only store data necessary to operate the bot. "
        "No personal data is shared or sold. By using the bot, you agree to this policy."
    )

    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(text='Back', callback_data='back_cb_fuck')]
    ])

    await query.edit_message_text(text=text, reply_markup=reply_markup)


@app.on_callback_query(filters.regex('back_cb_fuck'))
async def back_callback(_, query: CallbackQuery):
    text = (
        f"Hello {query.from_user.mention}, welcome to {app.me.mention}!\n\n"
        f"➻ Your ultimate tool for managing and protecting your Telegram spaces.\n"
        f"──────────────────\n"
        f"➻ Press 'Help' to discover all available features."
    )

    start_button = InlineKeyboardMarkup([
        [InlineKeyboardButton("Add me", url=f't.me/{app.me.username}?startgroup=true')],
        [InlineKeyboardButton("Help", callback_data="help_cb_fuck"),
         InlineKeyboardButton("Privacy Policy", callback_data="pp_cb_fuck")]
    ])

    await query.edit_message_text(
        text=text,
        reply_markup=start_button,
        disable_web_page_preview=True
    )
