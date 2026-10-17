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
from datetime import datetime, timezone

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
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
        await ctx.bot.send_message(
            target_chat,
            offer_text,
            parse_mode=ParseMode.HTML,
            reply_markup=offer_kb(offer_id),
            disable_web_page_preview=False,
        )
        if buyer:
            await update.message.reply_text(
                f"✅ Оффер отправлен <b>@{buyer}</b>.",
                parse_mode=ParseMode.HTML,
            )
    except Exception as e:
        await update.message.reply_text(
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
#  BUSINESS MESSAGE HANDLER
# ─────────────────────────────────────────────
async def on_business_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    logger.info(
        "Business msg from %s in connection %s: %s",
        msg.from_user.id if msg.from_user else "?",
        msg.business_connection_id,
        msg.text or "<non-text>",
    )
    try:
        await ctx.bot.send_message(
            chat_id=msg.chat.id,
            text="👋 Привет! Напиши /start чтобы создать оффер на подарок.",
            business_connection_id=msg.business_connection_id,
        )
    except Exception as e:
        logger.warning("Business reply failed: %s", e)

# ─────────────────────────────────────────────
#  MAIN — Web Service (webhook + aiohttp health port)
# ─────────────────────────────────────────────
async def healthz(request):
    return web.Response(text="ok")

async def run():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("offer", cmd_offer))
    application.add_handler(CallbackQueryHandler(on_callback))
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
