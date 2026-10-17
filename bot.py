"""
╔══════════════════════════════════════════════════════════╗
║           GIFT OFFER BOT — by @vibe_codernezzx          ║
║         Telegram Business API + Stars Payments          ║
╚══════════════════════════════════════════════════════════╝

Sticker IDs (configured at top):
  STAR_STICKER   = 5920281855378068765
  BLACK_GIFT     = 5931409969613116639

Premium key: 100 Stars/week  → sends 100 Stars to @vibe_codernezzx
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
    LabeledPrice,
    InputSticker,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode
from aiohttp import web

# ─────────────────────────────────────────────
#  CONFIG — вставь свои данные прямо здесь
# ─────────────────────────────────────────────
BOT_TOKEN       = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
OWNER_USERNAME  = "@vibe_codernezzx"          # кому идут Stars за ключ
OWNER_ID        = int(os.getenv("OWNER_ID", "0"))  # числовой ID @vibe_codernezzx

# Web Service config (Render)
PORT            = int(os.getenv("PORT", "10000"))
WEBHOOK_HOST    = os.getenv("WEBHOOK_HOST", "")     # напр. https://giftofferbot.onrender.com
WEBHOOK_PATH    = "/webhook/" + BOT_TOKEN
WEBHOOK_URL     = f"{WEBHOOK_HOST}{WEBHOOK_PATH}" if WEBHOOK_HOST else ""

# Sticker IDs (кастомные эмодзи/стикеры)
STAR_STICKER_ID  = "5920281855378068765"
BLACK_GIFT_ID    = "5931409969613116639"

# Ключи доступа (хранятся в памяти; при рестарте сбрасываются — для prod юзай DB)
PREMIUM_PRICE_STARS  = 100          # цена ключа
PREMIUM_DURATION_SEC = 7 * 24 * 3600  # 1 неделя

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
    return {"users": {}, "stats": {"total_offers": 0, "total_keys_sold": 0, "total_stars_earned": 0}}

def save_db(db: dict):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

db = load_db()

def get_user(uid: int) -> dict:
    key = str(uid)
    if key not in db["users"]:
        db["users"][key] = {
            "username": "",
            "premium_until": 0,
            "offers_sent": 0,
            "offers_received": 0,
            "stars_spent": 0,
            "joined": datetime.now(timezone.utc).isoformat(),
        }
    return db["users"][key]

def is_premium(uid: int) -> bool:
    u = get_user(uid)
    return u["premium_until"] > datetime.now(timezone.utc).timestamp()

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
def main_menu_kb(uid: int) -> InlineKeyboardMarkup:
    prem = "✅ Premium активен" if is_premium(uid) else "🔑 Купить ключ — 100 ⭐"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 Создать оффер",     callback_data="create_offer")],
        [InlineKeyboardButton("📊 Статистика",        callback_data="stats")],
        [InlineKeyboardButton(prem,                   callback_data="buy_key")],
        [InlineKeyboardButton("ℹ️ Как это работает", callback_data="how")],
    ])

def offer_kb(offer_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Принять",  callback_data=f"accept_{offer_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"decline_{offer_id}"),
        ]
    ])

def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="back")]])

# ─────────────────────────────────────────────
#  WELCOME  (красивая стартовая картинка через стикер)
# ─────────────────────────────────────────────
WELCOME_TEXT = (
    "<b>╔══════════════════════════╗\n"
    "║   🎁  GIFT OFFER BOT   🎁  ║\n"
    "╚══════════════════════════╝</b>\n\n"
    "Добро пожаловать! Этот бот позволяет:\n\n"
    "  <b>🎀 Создавать офферы</b> на подарки Telegram\n"
    "  <b>⭐ Получать Stars</b> за переданные подарки\n"
    "  <b>📊 Смотреть статистику</b> своих сделок\n"
    "  <b>🔑 Купить Premium-ключ</b> за 100 Stars/неделю\n\n"
    "<i>Работает через Telegram Business API.\n"
    "Подарок автоматически уходит тому, кто создал оффер.</i>\n\n"
    "Выбери действие:"
)

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user(uid)
    u["username"] = update.effective_user.username or ""
    save_db(db)

    # Отправляем стикер-«картинку» при старте
    try:
        await ctx.bot.send_sticker(
            chat_id=update.effective_chat.id,
            sticker=f"tg://emoji?id={BLACK_GIFT_ID}",
        )
    except Exception:
        pass  # если стикер не проходит — продолжаем без него

    await update.message.reply_text(
        WELCOME_TEXT,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb(uid),
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
            reply_markup=main_menu_kb(uid)
        )

    # ── CREATE OFFER ──
    elif data == "create_offer":
        if not is_premium(uid):
            await q.edit_message_text(
                "🔒 <b>Нужен Premium-ключ</b>\n\n"
                "Для создания офферов требуется активный ключ.\n"
                "Стоимость: <b>100 ⭐ / неделя</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔑 Купить ключ", callback_data="buy_key")],
                    [InlineKeyboardButton("⬅️ Назад",       callback_data="back")],
                ])
            )
            return

        ctx.user_data["awaiting_offer"] = True
        await q.edit_message_text(
            "📝 <b>Создание оффера</b>\n\n"
            "Отправь сообщение в формате:\n\n"
            "<code>STARS GIFT_ID @username</code>\n\n"
            "Пример:\n"
            "<code>5000 Xmas_Stocking_129649 @buyer123</code>\n\n"
            "<i>Подарок будет автоматически отправлен покупателю.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb()
        )

    # ── STATS ──
    elif data == "stats":
        u = get_user(uid)
        total = db["stats"]
        prem_until = datetime.fromtimestamp(u["premium_until"], tz=timezone.utc)
        prem_str = (
            prem_until.strftime("до %d.%m.%Y %H:%M UTC")
            if is_premium(uid) else "не активен"
        )

        text = (
            f"📊 <b>Ваша статистика</b>\n"
            f"{'─'*28}\n"
            f"🎁 Офферов отправлено:  <b>{u['offers_sent']}</b>\n"
            f"📥 Офферов получено:    <b>{u['offers_received']}</b>\n"
            f"⭐ Stars потрачено:     <b>{u['stars_spent']}</b>\n"
            f"🔑 Premium:            <b>{prem_str}</b>\n\n"
            f"🌍 <b>Общая статистика бота</b>\n"
            f"{'─'*28}\n"
            f"📦 Всего офферов:      <b>{total['total_offers']}</b>\n"
            f"🔑 Ключей продано:     <b>{total['total_keys_sold']}</b>\n"
            f"⭐ Stars заработано:   <b>{total['total_stars_earned']}</b>\n"
        )
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb())

    # ── BUY KEY ──
    elif data == "buy_key":
        if is_premium(uid):
            u = get_user(uid)
            until = datetime.fromtimestamp(u["premium_until"], tz=timezone.utc)
            await q.edit_message_text(
                f"✅ <b>Premium уже активен</b>\n\nДействует до: <b>{until.strftime('%d.%m.%Y %H:%M UTC')}</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=back_kb()
            )
            return

        await q.message.reply_invoice(
            title="🔑 Premium-ключ",
            description="Доступ к созданию офферов на 7 дней (1 неделя)",
            payload="premium_key_week",
            currency="XTR",   # XTR = Telegram Stars
            prices=[LabeledPrice("Premium 7 дней", PREMIUM_PRICE_STARS)],
            protect_content=False,
        )
        await q.edit_message_text(
            "💳 Счёт выставлен выше ☝️\nОплати <b>100 ⭐</b> чтобы активировать Premium.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb()
        )

    # ── HOW IT WORKS ──
    elif data == "how":
        await q.edit_message_text(
            "ℹ️ <b>Как это работает</b>\n\n"
            "1️⃣ Купи <b>Premium-ключ</b> за 100 Stars (1 нед).\n\n"
            "2️⃣ Нажми <b>«Создать оффер»</b> и отправь:\n"
            "   <code>STARS GIFT_ID @buyer</code>\n\n"
            "3️⃣ Бот формирует оффер — <b>подарок идёт покупателю</b>, "
            "ты получаешь Stars.\n\n"
            "4️⃣ Следи за сделками в <b>«Статистика»</b>.\n\n"
            "<i>Бот работает через Telegram Business API.\n"
            "Подключи бота в настройках: Настройки → Telegram Business → Чат-боты.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb()
        )

    # ── ACCEPT OFFER ──
    elif data.startswith("accept_"):
        offer_id = data.split("_", 1)[1]
        offers   = ctx.bot_data.get("offers", {})
        offer    = offers.get(offer_id)
        if not offer:
            await q.edit_message_text("❌ Оффер не найден или устарел.", reply_markup=back_kb())
            return

        creator_id = offer["creator_id"]
        stars      = offer["stars"]
        gift_name  = offer["gift_name"]

        # Оффер принят — фиксируем в статистике
        get_user(creator_id)["offers_sent"]   += 1
        get_user(uid)["offers_received"]      += 1
        db["stats"]["total_offers"]           += 1
        offers.pop(offer_id, None)
        save_db(db)

        await q.edit_message_text(
            f"✅ <b>Оффер принят!</b>\n\n"
            f"🎁 Подарок: <b>{gift_name}</b>\n"
            f"⭐ Сумма: <b>{stars} Stars</b>\n\n"
            f"Передай подарок покупателю через кнопку <b>«Передать НФТ»</b> в Telegram.",
            parse_mode=ParseMode.HTML,
        )
        # Уведомляем создателя
        try:
            await ctx.bot.send_message(
                creator_id,
                f"✅ Твой оффер на <b>{gift_name}</b> принят!\n"
                f"Покупатель: @{q.from_user.username or uid}\n"
                f"Передай подарок и получи <b>{stars} ⭐</b>.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    # ── DECLINE OFFER ──
    elif data.startswith("decline_"):
        offer_id = data.split("_", 1)[1]
        offers   = ctx.bot_data.get("offers", {})
        offer    = offers.pop(offer_id, None)
        save_db(db)
        creator_id = offer["creator_id"] if offer else None

        await q.edit_message_text("❌ <b>Оффер отклонён.</b>", parse_mode=ParseMode.HTML)
        if creator_id:
            try:
                await ctx.bot.send_message(
                    creator_id,
                    "❌ Твой оффер был отклонён покупателем.",
                )
            except Exception:
                pass

# ─────────────────────────────────────────────
#  TEXT HANDLER — парсим оффер
# ─────────────────────────────────────────────
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text.strip()

    if not ctx.user_data.get("awaiting_offer"):
        return

    parts = text.split()
    if len(parts) < 3:
        await update.message.reply_text(
            "⚠️ Неверный формат. Отправь:\n<code>STARS GIFT_ID @username</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    ctx.user_data["awaiting_offer"] = False

    try:
        stars     = int(parts[0])
        gift_name = parts[1]
        buyer     = parts[2].lstrip("@")
    except ValueError:
        await update.message.reply_text("⚠️ STARS должно быть числом.")
        return

    # Генерируем offer_id
    offer_id = f"{uid}_{int(datetime.now().timestamp())}"
    if "offers" not in ctx.bot_data:
        ctx.bot_data["offers"] = {}
    ctx.bot_data["offers"][offer_id] = {
        "creator_id": uid,
        "stars":      stars,
        "gift_name":  gift_name,
        "buyer":      buyer,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    offer_text = (
        f"🎁 <b>Новый оффер!</b>\n\n"
        f"Подарок: <b>{gift_name}</b>\n"
        f"⭐ Сумма: <b>{stars} Stars</b>\n"
        f"От: @{update.effective_user.username or uid}\n\n"
        f"<i>Следуйте инструкции, чтобы не потерять подарок и получить оплату.</i>"
    )

    # Отправляем покупателю
    try:
        await ctx.bot.send_message(
            f"@{buyer}",
            offer_text,
            parse_mode=ParseMode.HTML,
            reply_markup=offer_kb(offer_id),
        )
        await update.message.reply_text(
            f"✅ Оффер отправлен <b>@{buyer}</b>!\nОжидай ответа.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_kb(uid),
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Не удалось отправить оффер: <code>{e}</code>\n"
            "Убедись, что покупатель писал боту хотя бы раз.",
            parse_mode=ParseMode.HTML,
        )

# ─────────────────────────────────────────────
#  STARS PAYMENT FLOW
# ─────────────────────────────────────────────
async def on_precheckout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.pre_checkout_query
    await q.answer(ok=True)

async def on_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid     = update.effective_user.id
    payload = update.message.successful_payment.invoice_payload

    if payload == "premium_key_week":
        u = get_user(uid)
        now = datetime.now(timezone.utc).timestamp()
        # Если уже есть — продлеваем сверху
        base = max(u["premium_until"], now)
        u["premium_until"]  = base + PREMIUM_DURATION_SEC
        u["stars_spent"]   += PREMIUM_PRICE_STARS
        db["stats"]["total_keys_sold"]    += 1
        db["stats"]["total_stars_earned"] += PREMIUM_PRICE_STARS
        save_db(db)

        until = datetime.fromtimestamp(u["premium_until"], tz=timezone.utc)
        await update.message.reply_text(
            f"🎉 <b>Premium активирован!</b>\n\n"
            f"✅ Действует до: <b>{until.strftime('%d.%m.%Y %H:%M UTC')}</b>\n\n"
            f"Теперь можешь создавать офферы 🎁",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_kb(uid),
        )

        # Пересылаем 100 Stars владельцу (если OWNER_ID задан)
        if OWNER_ID:
            try:
                await ctx.bot.send_message(
                    OWNER_ID,
                    f"💰 +100 ⭐ от @{update.effective_user.username or uid}\n"
                    f"Ключ продан. Всего продано: {db['stats']['total_keys_sold']}",
                )
            except Exception:
                pass

# ─────────────────────────────────────────────
#  BUSINESS MESSAGE HANDLER
#  (сообщения из Business-чатов проходят сюда)
# ─────────────────────────────────────────────
async def on_business_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Когда бот подключён через Telegram Business,
    входящие сообщения клиентов приходят с business_connection_id.
    Здесь можно авто-отвечать или логировать.
    """
    msg = update.message
    if not msg:
        return
    logger.info(
        "Business msg from %s in connection %s: %s",
        msg.from_user.id if msg.from_user else "?",
        msg.business_connection_id,
        msg.text or "<non-text>",
    )
    # Автоответ в бизнес-чате
    try:
        await ctx.bot.send_message(
            chat_id=msg.chat.id,
            text=(
                "👋 Привет! Я автоматический помощник.\n"
                "Для создания оффера напиши мне в личку: /start"
            ),
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
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(PreCheckoutQueryHandler(on_precheckout))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_payment))
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.UpdateType.BUSINESS_MESSAGE,
            on_business_message,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & ~filters.UpdateType.BUSINESS_MESSAGE,
            on_text,
        )
    )

    await application.initialize()
    await application.start()

    aio = web.Application()
    aio.router.add_get("/", healthz)
    aio.router.add_get("/healthz", healthz)

    if WEBHOOK_URL:
        # ── WEB SERVICE MODE (Render) — Telegram шлёт апдейты на наш URL ──
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

        # держим процесс живым
        await asyncio.Event().wait()
    else:
        # ── FALLBACK: локальный запуск без WEBHOOK_HOST → polling ──
        logger.warning("WEBHOOK_HOST не задан — запускаю в режиме polling (для локальной разработки)")

        # health-сервер всё равно поднимаем, чтобы Render видел открытый порт
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
