"""
╔══════════════════════════════════════════════════════════╗
║           GIFT OFFER BOT — by @vibe_codernezzx          ║
║         Telegram Business API — Gift Offer Flow          ║
╚══════════════════════════════════════════════════════════╝

Команда создания оффера:
  /offer <stars> <nft_ссылка> [@buyer]

Пример:
  /offer 5000 https://t.me/nft/XmasStocking-129649 @buyer123

Оффер приходит как карточка с кнопками ✅ Принять / ❌ Отклонить,
как у настоящих подарочных офферов в Telegram.

Premium-стикеры (вставлены в /start и в карточку оффера):
  STAR_STICKER_ID  = 5920281855378068765   — звезда (главный экран)
  BLACK_GIFT_ID    = 5931409969613116639   — чёрный подарок (карточка оффера)
"""

import os
import json
import logging
import asyncio
import re
from html import escape
from datetime import datetime, timezone

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BusinessConnection,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    BusinessConnectionHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode
from aiohttp import web

# ─────────────────────────────────────────────
#  CONFIG — вставь свои данные прямо здесь
# ─────────────────────────────────────────────
BOT_TOKEN      = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
OWNER_USERNAME = "@vibe_codernezzx"
OWNER_ID       = int(os.getenv("OWNER_ID", "0"))   # числовой ID @vibe_codernezzx — у владельца нет ограничений

# Web Service config (Render)
PORT         = int(os.getenv("PORT", "10000"))
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "")        # напр. https://giftofferbot.onrender.com
WEBHOOK_PATH = "/webhook/" + BOT_TOKEN
WEBHOOK_URL  = f"{WEBHOOK_HOST}{WEBHOOK_PATH}" if WEBHOOK_HOST else ""

# Premium custom emoji IDs (встраиваются прямо в HTML-текст через <tg-emoji>)
STAR_STICKER_ID = "5920281855378068765"   # звезда — на старте
BLACK_GIFT_ID   = "5931409969613116639"   # чёрный подарок — в карточке оффера

# ─────────────────────────────────────────────
#  PERSISTENCE  (JSON-файл, хватает для Render)
# ─────────────────────────────────────────────
DB_FILE = "db.json"

def load_db() -> dict:
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"users": {}, "offers": {}, "stats": {"total_offers": 0, "accepted": 0, "declined": 0}}

def save_db(d: dict):
    with open(DB_FILE, "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

db = load_db()
db.setdefault("offers", {})
db.setdefault("business_chats", {})
db.setdefault("business_connections", {})
db.setdefault("stats", {"total_offers": 0, "accepted": 0, "declined": 0})

def get_user(uid: int) -> dict:
    key = str(uid)
    if key not in db["users"]:
        db["users"][key] = {
            "username": "",
            "offers_created": 0,
            "offers_accepted": 0,
            "offers_declined": 0,
            "joined": datetime.now(timezone.utc).isoformat(),
        }
    return db["users"][key]

def is_owner(uid: int) -> bool:
    return OWNER_ID != 0 and uid == OWNER_ID

# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  KEYBOARDS
# ─────────────────────────────────────────────
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 Скан чатов", callback_data="scan")],
        [InlineKeyboardButton("🎁 Как создать оффер", callback_data="how")],
        [InlineKeyboardButton("📊 Статистика",         callback_data="stats")],
    ])

def offer_kb(offer_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Принять",   callback_data=f"accept_{offer_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"decline_{offer_id}"),
        ]
    ])

def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="back")]])

# ─────────────────────────────────────────────
#  WELCOME
# ─────────────────────────────────────────────
WELCOME_TEXT = (
    "<tg-emoji emoji-id=\"5920281855378068765\">⭐</tg-emoji> "
    "<b>╔══════════════════════════╗\n"
    "║   🎁  GIFT OFFER BOT   🎁  ║\n"
    "╚══════════════════════════╝</b>\n\n"
    "Создавай офферы на подарки Telegram прямо в чате:\n\n"
    "<code>/offer 5000 https://t.me/nft/XmasStocking-129649 @buyer</code>\n\n"
    "<i>Покупатель получит карточку оффера с кнопками\n"
    "«Принять» / «Отклонить» — как настоящий NFT-оффер.</i>"
)

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user(uid)
    u["username"] = update.effective_user.username or ""
    save_db(db)

    await update.message.reply_text(
        WELCOME_TEXT,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb(),
    )

# ─────────────────────────────────────────────
#  /offer <stars> <nft_link> [@buyer]
# ─────────────────────────────────────────────
async def cmd_offer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    args = ctx.args

    if len(args) < 2:
        await update.message.reply_text(
            "⚠️ <b>Формат команды:</b>\n\n"
            "<code>/offer STARS NFT_ССЫЛКА [@buyer]</code>\n\n"
            "Пример:\n"
            "<code>/offer 5000 https://t.me/nft/XmasStocking-129649 @buyer123</code>\n\n"
            "Если <code>@buyer</code> не указан — оффер постится прямо в этот чат.",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        stars = int(args[0])
        if stars <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ STARS должно быть положительным числом.")
        return

    nft_link = args[1]
    buyer    = args[2].lstrip("@") if len(args) > 2 else None

    # имя подарка из ссылки — последний сегмент URL
    gift_name = nft_link.rstrip("/").split("/")[-1].replace("-", " ").replace("_", " ")
    if not gift_name:
        gift_name = "NFT Gift"

    offer_id = f"{uid}_{int(datetime.now().timestamp())}"
    db["offers"][offer_id] = {
        "creator_id": uid,
        "creator_username": update.effective_user.username or str(uid),
        "stars": stars,
        "gift_name": gift_name,
        "nft_link": nft_link,
        "buyer": buyer,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db["stats"]["total_offers"] += 1
    get_user(uid)["offers_created"] += 1
    save_db(db)

    # Удаляем сообщение с командой /offer — сразу, до постинга карточки
    try:
        await ctx.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=update.message.message_id,
        )
    except Exception as e:
        logger.warning("delete /offer message failed: %s", e)

    offer_text = (
        f"<tg-emoji emoji-id=\"{BLACK_GIFT_ID}\">🎁</tg-emoji> "
        f"<a href=\"{nft_link}\">{gift_name}</a>\n\n"
        f"Пользователь предлагает Вам <b>{stars} "
        f"<tg-emoji emoji-id=\"{STAR_STICKER_ID}\">⭐</tg-emoji></b> за подарок "
        f"<a href=\"{nft_link}\">{gift_name}</a>.\n\n"
        f"Предложение действует ещё <b>6 ч. 0 мин.</b>\n\n"
        f"<i>Следуйте инструкции, чтобы не потерять подарок и получить оплату.</i>"
    )

    target_chat = f"@{buyer}" if buyer else update.effective_chat.id

    try:
        sent = await ctx.bot.send_message(
            target_chat,
            offer_text,
            parse_mode=ParseMode.HTML,
            reply_markup=offer_kb(offer_id),
            disable_web_page_preview=False,
        )
        db["offers"][offer_id]["message_id"] = sent.message_id
        db["offers"][offer_id]["chat_id"]    = sent.chat.id
        save_db(db)
    except Exception as e:
        await ctx.bot.send_message(
            update.effective_chat.id,
            f"❌ Не удалось отправить оффер: <code>{e}</code>\n"
            "Если указан @buyer — убедись, что он писал боту хотя бы раз.",
            parse_mode=ParseMode.HTML,
        )

# ─────────────────────────────────────────────
#  CALLBACK HANDLERS
# ─────────────────────────────────────────────
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    uid  = q.from_user.id
    data = q.data
    await q.answer()

    if data == "scan":
        await show_chats(q, uid)
        return
    if data.startswith("pick:"):
        await select_chat(q, uid, data[5:])
        return
    if data == "cancel_flow":
        ctx.user_data.pop("offer_flow", None)
        await q.edit_message_text("Создание отменено.", reply_markup=main_menu_kb())
        return

    # ── BACK ──
    if data == "back":
        await q.edit_message_text(
            WELCOME_TEXT, parse_mode=ParseMode.HTML,
            reply_markup=main_menu_kb()
        )

    # ── STATS ──
    elif data == "stats":
        u = get_user(uid)
        total = db["stats"]
        text = (
            f"📊 <b>Ваша статистика</b>\n"
            f"{'─'*28}\n"
            f"🎁 Офферов создано:   <b>{u['offers_created']}</b>\n"
            f"✅ Принято:           <b>{u['offers_accepted']}</b>\n"
            f"❌ Отклонено:         <b>{u['offers_declined']}</b>\n\n"
            f"🌍 <b>Общая статистика бота</b>\n"
            f"{'─'*28}\n"
            f"📦 Всего офферов:     <b>{total['total_offers']}</b>\n"
            f"✅ Принято всего:     <b>{total['accepted']}</b>\n"
            f"❌ Отклонено всего:   <b>{total['declined']}</b>\n"
        )
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb())

    # ── HOW IT WORKS ──
    elif data == "how":
        await q.edit_message_text(
            "ℹ️ <b>Как создать оффер</b>\n\n"
            "<code>/offer STARS NFT_ССЫЛКА [@buyer]</code>\n\n"
            "Пример:\n"
            "<code>/offer 5000 https://t.me/nft/XmasStocking-129649 @buyer</code>\n\n"
            "Если <code>@buyer</code> не указан — оффер публикуется в текущем чате.\n\n"
            "Покупатель видит карточку с кнопками <b>✅ Принять / ❌ Отклонить</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb()
        )

    # ── ACCEPT OFFER ──
    elif data.startswith("accept_"):
        offer_id = data.split("_", 1)[1]
        offer = db["offers"].get(offer_id)
        if not offer or offer["status"] != "pending":
            await q.edit_message_text("❌ Оффер не найден или уже закрыт.")
            return

        offer["status"] = "accepted"
        creator_id = offer["creator_id"]
        stars      = offer["stars"]
        gift_name  = offer["gift_name"]
        nft_link   = offer["nft_link"]

        get_user(creator_id)["offers_accepted"] += 1
        db["stats"]["accepted"] += 1
        save_db(db)

        await q.edit_message_text(
            f"✅ <b>Оффер принят!</b>\n\n"
            f"🎁 <a href=\"{nft_link}\">{gift_name}</a>\n"
            f"⭐ Сумма: <b>{stars} Stars</b>\n\n"
            f"Передайте подарок создателю оффера, чтобы получить оплату.",
            parse_mode=ParseMode.HTML,
        )
        try:
            await ctx.bot.send_message(
                creator_id,
                f"✅ Твой оффер на <b>{gift_name}</b> принят!\n"
                f"Покупатель: @{q.from_user.username or uid}\n"
                f"Жди подарок — после получения отправь <b>{stars} ⭐</b>.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    # ── DECLINE OFFER ──
    elif data.startswith("decline_"):
        offer_id = data.split("_", 1)[1]
        offer = db["offers"].get(offer_id)
        if not offer or offer["status"] != "pending":
            await q.edit_message_text("❌ Оффер не найден или уже закрыт.")
            return

        offer["status"] = "declined"
        creator_id = offer["creator_id"]
        get_user(creator_id)["offers_declined"] += 1
        db["stats"]["declined"] += 1
        save_db(db)

        await q.edit_message_text("❌ <b>Оффер отклонён.</b>", parse_mode=ParseMode.HTML)
        try:
            await ctx.bot.send_message(creator_id, "❌ Твой оффер был отклонён покупателем.")
        except Exception:
            pass

# ─────────────────────────────────────────────
#  BUSINESS CONNECTION DETECT — уведомление владельцу
# ─────────────────────────────────────────────
async def on_business_connection(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    conn: BusinessConnection = update.business_connection
    if not conn:
        return

    user = conn.user
    status = "✅ подключён" if conn.is_enabled else "❌ отключён"
    db["business_connections"][str(user.id)] = {"id": conn.id, "enabled": conn.is_enabled}
    save_db(db)
    text = (
        f"🏢 <b>Business-аккаунт {status}</b>\n\n"
        f"👤 Пользователь: {user.full_name}"
        + (f" (@{user.username})" if user.username else "")
        + f"\n🆔 ID: <code>{user.id}</code>\n"
        f"🔗 Connection ID: <code>{conn.id}</code>\n"
        f"📨 Может отвечать: <b>{'да' if getattr(getattr(conn, 'rights', None), 'can_reply', False) else 'нет'}</b>"
    )

    logger.info("Business connection event: user=%s enabled=%s", user.id, conn.is_enabled)

    if OWNER_ID:
        try:
            await ctx.bot.send_message(OWNER_ID, text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.warning("owner notify failed: %s", e)

# ─────────────────────────────────────────────
#  BUSINESS MESSAGE HANDLER
# ─────────────────────────────────────────────
async def on_business_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.business_message
    if not msg or not msg.business_connection_id:
        return
    # Business Bot API provides updates, not a list of all Telegram dialogs.
    try:
        conn = await ctx.bot.get_business_connection(msg.business_connection_id)
    except Exception as exc:
        logger.warning("Business connection lookup failed: %s", exc)
        return
    if not conn.is_enabled or msg.chat.type != "private" or msg.chat.id == conn.user.id:
        return
    key = f"{conn.user.id}:{msg.chat.id}"
    db["business_chats"][key] = {
        "owner": conn.user.id, "chat_id": msg.chat.id,
        "connection_id": msg.business_connection_id,
        "name": msg.chat.full_name or msg.chat.username or str(msg.chat.id),
        "seen_at": datetime.now(timezone.utc).isoformat(),
    }
    save_db(db)


def flow_cancel_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="cancel_flow")]])


async def show_chats(q, uid):
    chats = [v for v in db["business_chats"].values() if v.get("owner") == uid]
    chats.sort(key=lambda c: c.get("seen_at", ""), reverse=True)
    buttons = []
    for chat in chats[:40]:
        key = f"{uid}:{chat['chat_id']}"
        buttons.append([InlineKeyboardButton(chat["name"][:45], callback_data=f"pick:{key}")])
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="back")])
    await q.edit_message_text(
        "🔎 <b>Доступные Business-чаты</b>\n\n"
        + ("Выбери диалог:" if chats else "Пока нет чатов. Они появятся после получения ботом Business-сообщений."),
        parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))


async def select_chat(q, uid, key):
    chat = db["business_chats"].get(key)
    if not chat or chat["owner"] != uid:
        await q.answer("Чат недоступен", show_alert=True)
        return
    try:
        conn = await q.get_bot().get_business_connection(chat["connection_id"])
        if not conn.is_enabled or conn.user.id != uid or not getattr(getattr(conn, "rights", None), "can_reply", False):
            raise ValueError("Нет активного разрешения на ответы")
    except Exception as exc:
        await q.edit_message_text(f"Не удалось проверить Business-подключение: {escape(str(exc))}")
        return
    # Selection state is stored by scan_callback.
    await q.edit_message_text("Выбран чат: <b>" + escape(chat["name"]) + "</b>\n\nПришли NFT-ссылку формата https://t.me/nft/Name-123", parse_mode=ParseMode.HTML, reply_markup=flow_cancel_kb())


async def scan_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.data.startswith("pick:"):
        uid = q.from_user.id
        key = q.data[5:]
        chat = db["business_chats"].get(key)
        if not chat or chat.get("owner") != uid:
            await q.answer("Чат недоступен", show_alert=True)
            return
        ctx.user_data["offer_flow"] = {"step": "link", "key": key}
    await on_callback(update, ctx)


async def on_flow_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    flow = ctx.user_data.get("offer_flow")
    if not flow or not update.message or update.effective_chat.type != "private":
        return
    uid = update.effective_user.id
    value = (update.message.text or "").strip()
    if flow["step"] == "link":
        if not re.fullmatch(r"https://t\.me/nft/[A-Za-z0-9_-]+", value):
            await update.message.reply_text("Неверная NFT-ссылка. Пример: https://t.me/nft/XmasStocking-129649")
            return
        flow["link"] = value
        flow["step"] = "stars"
        await update.message.reply_text("⭐ Введи количество звёзд (целое положительное число):", reply_markup=flow_cancel_kb())
        return
    if flow["step"] != "stars":
        return
    try:
        stars = int(value)
        if not 1 <= stars <= 1000000000:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("Введи число от 1 до 1000000000.")
        return
    chat = db["business_chats"].get(flow["key"])
    if not chat or chat["owner"] != uid:
        ctx.user_data.pop("offer_flow", None)
        await update.message.reply_text("Чат больше недоступен.")
        return
    try:
        conn = await ctx.bot.get_business_connection(chat["connection_id"])
        if not conn.is_enabled or conn.user.id != uid or not getattr(getattr(conn, "rights", None), "can_reply", False):
            raise ValueError("Business-подключение отключено или нет права отправлять сообщения")
        link = flow["link"]
        name = link.rsplit("/", 1)[-1]
        text = (f"🎁 <b>Предложение от пользователя</b>\n\n"
                f"NFT: <a href=\"{escape(link, quote=True)}\">{escape(name)}</a>\n"
                f"Предложенная сумма: <b>{stars} ⭐</b>\n\n"
                "Это предложение не является официальной сделкой Telegram. "
                "Нажатие кнопки не переводит NFT или звёзды.")
        offer_id = f"{uid}_{int(datetime.now(timezone.utc).timestamp() * 1000000)}"
        sent = await ctx.bot.send_message(chat_id=chat["chat_id"], text=text,
            business_connection_id=chat["connection_id"], parse_mode=ParseMode.HTML,
            reply_markup=offer_kb(offer_id))
        db["offers"][offer_id] = {"creator_id": uid, "creator_username": update.effective_user.username or str(uid),
            "stars": stars, "gift_name": name, "nft_link": link, "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(), "message_id": sent.message_id,
            "chat_id": chat["chat_id"], "connection_id": chat["connection_id"]}
        db["stats"]["total_offers"] += 1
        get_user(uid)["offers_created"] += 1
        save_db(db)
        ctx.user_data.pop("offer_flow", None)
        await update.message.reply_text("✅ Предложение отправлено в чат: " + chat["name"])
    except Exception as exc:
        logger.exception("Offer delivery failed")
        await update.message.reply_text("❌ Отправка не удалась: " + str(exc) + "\nПроверь права Business и активность диалога.")


# ─────────────────────────────────────────────
#  MAIN — Web Service (webhook + aiohttp health port)
# ─────────────────────────────────────────────
async def healthz(request):
    return web.Response(text="ok")

async def run():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", cmd_start))
    
    application.add_handler(CallbackQueryHandler(scan_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, on_flow_message), group=0)
    application.add_handler(BusinessConnectionHandler(on_business_connection))
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.UpdateType.BUSINESS_MESSAGE,
            on_business_message,
        )
    )

    await application.initialize()
    await application.start()

    aio = web.Application()
    aio.router.add_get("/", healthz)
    aio.router.add_get("/healthz", healthz)

    if WEBHOOK_URL:
        async def telegram_webhook(request: web.Request):
            data = await request.json()
            update = Update.de_json(data, application.bot)
            await application.process_update(update)
            return web.Response(text="ok")

        aio.router.add_post(WEBHOOK_PATH, telegram_webhook)

        await application.bot.set_webhook(
            url=WEBHOOK_URL,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        logger.info("Webhook set: %s", WEBHOOK_URL)

        runner = web.AppRunner(aio)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", PORT)
        await site.start()
        logger.info("Web service listening on port %s", PORT)

        await asyncio.Event().wait()
    else:
        logger.warning("WEBHOOK_HOST не задан — запускаю в режиме polling")

        # Снимаем возможный webhook с прошлого деплоя — иначе 409 Conflict
        try:
            await application.bot.delete_webhook(drop_pending_updates=True)
        except Exception as e:
            logger.warning("delete_webhook failed: %s", e)

        runner = web.AppRunner(aio)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", PORT)
        await site.start()

        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        await asyncio.Event().wait()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
