import logging
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import aiosmtplib
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, ConversationHandler, filters
)

CONFIG = {
    "BOT_TOKEN":     "8855518135:AAHnj0hRROX_BI3Sk_g5FSQLDZhfjvsKX1Y",
    "SMTP_HOST":     "smtp.yandex.ru",
    "SMTP_PORT":     587,
    "SMTP_USER":     "e.barakovskaya@betoneagency.ru",
    "SMTP_PASSWORD": "czznyusxlolaftow",
    "MEDIA_EMAIL":   "info@mperspektiva.ru",
    "YOUR_EMAIL":    "e.barakovskaya@betoneagency.ru",
    "FROM_NAME":     "Пресс-служба",
    "EMAIL_SUBJECT": "Пресс-релиз",
}

WAITING_TEXT  = 1
WAITING_FILES = 2
CONFIRMING    = 3
sessions: dict[int, dict] = {}

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

async def send_email(release_text: str, attachments: list[dict]) -> bool:
    msg = MIMEMultipart()
    msg["From"]    = f"{CONFIG['FROM_NAME']} <{CONFIG['SMTP_USER']}>"
    msg["To"]      = CONFIG["MEDIA_EMAIL"]
    msg["Cc"]      = CONFIG["YOUR_EMAIL"]
    msg["Subject"] = CONFIG["EMAIL_SUBJECT"]
    msg.attach(MIMEText(release_text, "plain", "utf-8"))
    for att in attachments:
        part = MIMEBase(*att["mime"].split("/"))
        part.set_payload(att["data"])
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{att["filename"]}"')
        msg.attach(part)
    try:
        await aiosmtplib.send(
            msg,
            hostname=CONFIG["SMTP_HOST"],
            port=CONFIG["SMTP_PORT"],
            start_tls=True,
            username=CONFIG["SMTP_USER"],
            password=CONFIG["SMTP_PASSWORD"],
        )
        return True
    except Exception as e:
        log.error("Ошибка отправки: %s", e)
        return False

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    sessions[update.effective_user.id] = {"text": "", "files": []}
    await update.message.reply_text(
        "👋 Привет!\n\nЯ отправляю пресс-релизы в редакцию «Московской перспективы».\n\n📝 *Шаг 1.* Напиши или вставь текст пресс-релиза:",
        parse_mode="Markdown"
    )
    return WAITING_TEXT

async def receive_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    sessions[update.effective_user.id]["text"] = update.message.text
    keyboard = [
        [InlineKeyboardButton("📎 Прикреплю фото/файлы", callback_data="add_files")],
        [InlineKeyboardButton("✅ Отправить без вложений", callback_data="send_now")],
    ]
    await update.message.reply_text(
        "✅ Текст получен!\n\n📁 *Шаг 2.* Хочешь прикрепить фото или документы?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CONFIRMING

async def ask_files(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📎 Отправляй фото и документы — по одному или все сразу.\n\nКогда закончишь — нажми кнопку ниже 👇",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Готово, отправить", callback_data="send_now")]])
    )
    return WAITING_FILES

async def receive_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    msg = update.message
    if msg.photo:
        photo = msg.photo[-1]
        file  = await ctx.bot.get_file(photo.file_id)
        data  = await file.download_as_bytearray()
        sessions[user_id]["files"].append({"filename": f"photo_{photo.file_id[-6:]}.jpg", "data": bytes(data), "mime": "image/jpeg"})
    elif msg.document:
        doc  = msg.document
        file = await ctx.bot.get_file(doc.file_id)
        data = await file.download_as_bytearray()
        ext  = Path(doc.file_name or "file").suffix.lower()
        mime_map = {".pdf": "application/pdf", ".doc": "application/msword", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
        sessions[user_id]["files"].append({"filename": doc.file_name or f"file{ext}", "data": bytes(data), "mime": mime_map.get(ext, "application/octet-stream")})
    count = len(sessions[user_id]["files"])
    await msg.reply_text(
        f"✅ Файл добавлен ({count} шт. всего). Отправляй ещё или нажми «Готово».",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Готово, отправить", callback_data="send_now")]])
    )
    return WAITING_FILES

async def send_now(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    session = sessions.get(user_id, {})
    release_text = session.get("text", "")
    attachments  = session.get("files", [])
    if not release_text:
        await query.edit_message_text("❌ Текст пресс-релиза пустой. Начни заново: /start")
        return ConversationHandler.END
    await query.edit_message_text("⏳ Отправляю письмо в редакцию...")
    ok = await send_email(release_text, attachments)
    if ok:
        att_info = f" + {len(attachments)} вложений" if attachments else ""
        await ctx.bot.send_message(chat_id=user_id, text=f"✅ *Готово!*\n\nПресс-релиз{att_info} отправлен в «Московскую перспективу».\nКопия пришла тебе на {CONFIG['YOUR_EMAIL']}.\n\nХочешь отправить ещё? → /start", parse_mode="Markdown")
    else:
        await ctx.bot.send_message(chat_id=user_id, text="❌ Ошибка отправки. Попробуй ещё раз: /start")
    sessions.pop(user_id, None)
    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    sessions.pop(update.effective_user.id, None)
    await update.message.reply_text("❌ Отменено. Начать заново: /start")
    return ConversationHandler.END

def main():
    app = Application.builder().token(CONFIG["BOT_TOKEN"]).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_TEXT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text)],
            CONFIRMING:    [CallbackQueryHandler(ask_files, pattern="^add_files$"), CallbackQueryHandler(send_now, pattern="^send_now$")],
            WAITING_FILES: [MessageHandler(filters.PHOTO | filters.Document.ALL, receive_file), CallbackQueryHandler(send_now, pattern="^send_now$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    app.add_handler(conv)
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
