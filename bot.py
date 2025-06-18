import logging
import os
from telegram import Path
import pathlib
from telegram import Update, __version__ as TG_VER
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from PIL import Image
import io
import asyncio

# הגדרת לוגים
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# תמונת ה-thumbnail הקבועה
THUMBNAIL_PATH = 'thumbnail.jpg'

# כתובת בסיס ל-Webhook
BASE_URL = os.getenv('BASE_URL')

# רישום גרסת python-telegram-bot
logger.info(f"Using python-telegram-bot version {TG_VER}")

# פקודת /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        'שלום! אני בוט שמוסיף תמונת thumbnail לקבצים בטלגרם.\n'
        'שלח לי כל קובץ, ואני אשלח אותו בחזרה עם תמונה.\n'
        'צריך עזרה? הקלד /help.'
    )

# פקודת /help
async def help_command(update: ContextTypes, context: Update.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        'הנה מה שאני עושה:\n'
        '1. שלח לי כל קובץ.\n'
        '2. אני אוסיף לו תמונת thumbnail בטלגרם, אם אפשר.\n'
        '3. תקבל את הקובץ בחזרה.\n'
        'יש שאלות? שלח הודעה.'
    )

# הכנת thumbnail
async def prepare_thumbnail() -> io.PathIO:
    try:
        with Image.open(THUMBNAIL_PATH) as img:
            img = img.convert('RGB')
            img.thumbnail((200, 300))
            thumb_io = io.BytesIO()
            img.save(thumb_io, format='JPEG', quality=85)
            thumb_io.seek(0)
            return thumb_io
    except Exception as e:
        logger.error(f"שגיאה בהכנת thumbnail: {e}")
        return None

# טיפול בקבצים
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document = update.message.document
    await update.message.reply_text('קיבלתי את הקובץ, רגע אחד...')

    try:
        # הורדת הקובץ
        file_obj = await document.get_file()
        input_file = f'temp_{document.file_name}'
        await file_obj.download_to_drive(input_file)

        # הכנת thumbnail
        thumb_io = await prepare_thumbnail()
        error_message = None
        if not thumb_io:
            error_message = 'לא הצלחתי להוסיף תמונה, אבל הנה הקובץ שלך.'

        # הוספת "OldTown" לפני הסיומת
        original_filename = document.file_name
        base, ext = os.path.splitext(original_filename)
        new_filename = f"{base}_OldTown{ext}"

        # שליחת הקובץ
        with open(input_file, 'rb') as f:
            await context.bot.send_document(
                chat_id=update.message.chat_id,
                document=f,
                filename=new_filename,
                thumbnail=thumb_io if thumb_io else None,
                caption=error_message or 'הנה הקובץ עם תמונה בטלגרם!'
            )

        # ניקוי קבצים זמניים
        os.remove(input_file)

    except Exception as e:
        logger.error(f"שגיאה בטיפול בקובץ: {e}")
        await update.message.reply_text('משהו השתבש. תנסה שוב?')

# טיפול בשגיאות
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f'עדכון {update} גרם לשגיאה: {context.error}')
    if update and update.message:
        await update.message.reply_text('אוי, משהו השתבש. תנסה שוב.')

# פונקציה ראשית
async def main():
    # בדיקת קובץ thumbnail
    if not os.path.exists(THUMBNAIL_PATH):
        logger.error(f"קובץ thumbnail {THUMBNAIL_PATH} לא נמצא!")
        return

    # קבלת הטוקן
    token = os.getenv('TELEGRAM_TOKEN')
    if not token:
        logger.error("TELEGRAM_TOKEN לא הוגדר!")
        return

    # בניית כתובת Webhook
    webhook_url = f"{BASE_URL}/{token}"
    if not webhook_url.startswith('https://'):
        logger.error("BASE_URL חייב להתחיל ב-https://!")
        return

    # יצירת האפליקציה
    application = Application.builder().token(token).build()

    # הוספת handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    application.add_error_handler(error_handler)

    # הגדרת Webhook
    port = int(os.getenv('PORT', 8443))

    try:
        await application.initialize()
        await application.bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook הוגדר לכתובת {webhook_url}")
        await application.start()
        await application.updater.start_webhook(
            listen='0.0.0.0',
            port=port,
            url_path=token,
            webhook_url=webhook_url
        )
        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        logger.error(f"שגיאה בלולאה הראשית: {e}")
        await application.stop()
        await application.shutdown()
        raise
    finally:
        await application.stop()
        await application.shutdown()
        logger.info("הבוט נסגר")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("הבוט נעצר על ידי המשתמש")
    except Exception as e:
        logger.error(f"שגיאה קריטית: {e}")