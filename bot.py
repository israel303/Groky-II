import logging
import os
from telegram import Update, __version__ as TG_VER
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from ebooklib import epub
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
BASE_URL = os.getenv('BASE_URL', 'https://groky.onrender.com')

# רישום גרסת python-telegram-bot, למען הבהירות
logger.info(f"Using python-telegram-bot version {TG_VER}")

# פקודת /start - קבלת פנים מנומסת
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        'שלום רב, אני הבוט לטיפול ב-thumbnails של אולדטאון 📜\n'
        'אנא שלחו לי כל קובץ, ואדאג שיוצג בטלגרם עם הלוגו. \n'
        'זקוקים לסיוע? הקלידו /help, ואסייע במהירות הראויה.'
    )

# פקודת /help - 
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        'קצת מבולבלים, מה? הנה ההנחיות בקצרה:\n'
        '1. שלחו לי כל קובץ שתרצו.\n'
        '2. אדאג שיופיע עם לוגו הספריה בטלגרם, אם הדבר אפשרי.\n'
        '3. תקבלו את הקובץ בחזרה, מוכן להרשים! 📚\n'
        
    )

# הכנת thumbnail עבור טלגרם
async def prepare_thumbnail() -> io.BytesIO:
    try:
        with Image.open(THUMBNAIL_PATH) as img:
            img = img.convert('RGB')
            # שינוי גודל לתמונה מתאימה לטלגרם
            img.thumbnail((200, 300))
            thumb_io = io.BytesIO()
            img.save(thumb_io, format='JPEG', quality=85)
            thumb_io.seek(0)
            return thumb_io
    except Exception as e:
        logger.error(f"שגיאה בהכנת ה-thumbnail: {e}")
        return None

# עיבוד EPUB להחלפת ה-cover
async def process_epub(input_path: str, output_path: str) -> bool:
    try:
        logger.info(f"מעבד EPUB: {input_path}")
        # קריאת ה-EPUB
        book = epub.read_epub(input_path)

        # הסרת כל תמונות cover קיימות ומטא-דאטה ישן
        for item in list(book.get_items()):
            if item.get_name().lower() in ['cover.jpg', 'cover.jpeg', 'cover.png', 'cover.xhtml']:
                book.items.remove(item)
        for item in list(book.get_items_of_type(ebooklib.ITEM_IMAGE)):
            if 'cover' in item.get_name().lower():
                book.items.remove(item)
        # הסרת מטא-דאטה ישן של cover
        for meta in list(book.metadata.get('') or []):
            if isinstance(meta, tuple) and meta[1].get('name') == 'cover':
                book.metadata[''].remove(meta)

        # הכנת התמונה כ-cover
        with Image.open(THUMBNAIL_PATH) as img:
            img = img.convert('RGB')
            img.thumbnail((200, 300))  # גודל מתאים
            thumb_io = io.BytesIO()
            img.save(thumb_io, format='JPEG', quality=85)
            thumb_data = thumb_io.getvalue()

        # יצירת פריט תמונה עבור ה-cover
        cover_item = epub.EpubImage()
        cover_item.id = 'cover-img'
        cover_item.file_name = 'cover.jpg'
        cover_item.media_type = 'image/jpeg'
        cover_item.set_content(thumb_data)
        book.add_item(cover_item)

        # יצירת דף HTML עבור ה-cover
        cover_html = epub.EpubHtml(title='Cover', file_name='cover.xhtml', lang='en')
        cover_html.content = '''
            <!DOCTYPE html>
            <html xmlns="http://www.w3.org/1999/xhtml">
            <head>
                <title>Cover</title>
                <meta charset="utf-8"/>
            </head>
            <body>
                <img src="cover.jpg" alt="Cover Image" style="width:100%;height:auto;"/>
            </body>
            </html>
        '''.encode('utf-8')
        book.add_item(cover_html)

        # עדכון spine ו-TOC
        book.spine = ['cover', cover_html, 'nav'] + [item for item in book.spine if item != 'nav' and item != 'cover']
        book.toc = [epub.Link('cover.xhtml', 'Cover', 'cover')] + book.toc

        # חילוץ כותרת תקינה
        title = 'Book'
        title_metadata = book.get_metadata('DC', 'title')
        if title_metadata:
            title = title_metadata[0][0] if isinstance(title_metadata[0], tuple) else title_metadata[0]
        
        # עדכון מטא-דאטה
        book.set_identifier(book.get_unique_id())
        book.add_metadata('DC', 'title', title)
        book.add_metadata(None, 'meta', '', {'name': 'cover', 'content': 'cover-img'})

        # הוספת container.xml לתקינות
        book.add_item(epub.EpubItem(
            file_name='META-INF/container.xml',
            content=b'''<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
    <rootfiles>
        <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
    </rootfiles>
</container>'''
        ))
        book.guide = [{'href': 'cover.xhtml', 'type': 'cover', 'title': 'Cover'}]

        # שמירת ה-EPUB החדש
        epub.write_epub(output_path, book)
        logger.info(f"עיבוד EPUB הסתיים בהצלחה: {output_path}")
        return True
    except Exception as e:
        logger.error(f"שגיאה בעיבוד EPUB: {e}")
        return False

# טיפול בקבצים נכנסים
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document = update.message.document
    await update.message.reply_text('קיבלתי את הקובץ, תודה. תנו לי רגע להלביש אותו בתמונה ... 🖼️')

    try:
        # הורדת הקובץ
        file_obj = await document.get_file()
        input_file = f'temp_{document.file_name}'
        await file_obj.download_to_drive(input_file)

        output_file = input_file  # ברירת מחדל: שליחת הקובץ המקורי
        thumb_io = None
        error_message = None

        # הכנת thumbnail לכל קובץ
        thumb_io = await prepare_thumbnail()
        if not thumb_io:
            error_message = 'פאק, התמונה שלי התבלבלה. אשלח את הקובץ בלי thumbnail, לצערי...'

        # ניסיון לעבד כ-EPUB אם זה EPUB
        if document.file_name.lower().endswith('.epub'):
            output_file = f'output_{document.file_name}'
            success = await process_epub(input_file, output_file)
            if not success:
                error_message = 'הו לא, משהו השתבש בעיבוד ה-EPUB. הנה הקובץ המקורי, בכל זאת...'
                output_file = input_file

        # שליחת הקובץ
        with open(output_file, 'rb') as f:
            await context.bot.send_document(
                chat_id=update.message.chat_id,
                document=f,
                filename=document.file_name,
                thumbnail=thumb_io if thumb_io else None,
                caption=error_message or 'הנה !הקובץ עם התמונה בטלגרם 📖'
            )

        # ניקוי קבצים זמניים
        os.remove(input_file)
        if output_file != input_file and os.path.exists(output_file):
            os.remove(output_file)

    except Exception as e:
        logger.error(f"שגיאה בטיפול בקובץ: {e}")
        await update.message.reply_text('שיט, נראה שמעדתי על המקלדת! משהו השתבש. תנסו שוב, בבקשה? 😅')

# טיפול בשגיאות, בנימוס
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f'עדכון {update} גרם לשגיאה: {context.error}')
    if update and update.message:
        await update.message.reply_text('אוי ואבוי, התרחשה תקלה מביכה! אנא נסו שוב, ואתאושש במהרה. 🛠️')

# פונקציה ראשית להפעלת הבוט
async def main():
    # בדיקת קובץ ה-thumbnail
    if not os.path.exists(THUMBNAIL_PATH):
        logger.error(f"קובץ thumbnail {THUMBNAIL_PATH} לא נמצא! איני יכול להמשיך ללא התמונה הראויה!")
        return

    # קבלת הטוקן ממשתנה סביבה
    token = os.getenv('TELEGRAM_TOKEN')
    if not token:
        logger.error("TELEGRAM_TOKEN לא הוגדר! אני אבוד ללא האישורים שלי!")
        return

    # בניית כתובת Webhook
    webhook_url = f"{BASE_URL}/{token}"
    if not webhook_url.startswith('https://'):
        logger.error("BASE_URL חייב להתחיל ב-https://! אני זקוק לכתובת מאובטחת!")
        return

    # יצירת האפליקציה של הבוט
    application = Application.builder().token(token).build()

    # הוספת handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    application.add_error_handler(error_handler)

    # הגדרת Webhook
    port = int(os.getenv('PORT', 8443))

    try:
        # אתחול האפליקציה
        await application.initialize()
        # הגדרת ה-Webhook
        await application.bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook הוגדר לכתובת {webhook_url} - מוכן לעבודה מכובדת!")

        # הפעלת הבוט במצב Webhook
        await application.start()
        await application.updater.start_webhook(
            listen='0.0.0.0',
            port=port,
            url_path=token,
            webhook_url=webhook_url
        )

        # שמירה על ריצה עד לסיום מסודר
        while True:
            await asyncio.sleep(3600)  # המתנה ארוכה לשמירת התהליך פעיל

    except Exception as e:
        logger.error(f"שגיאה בלולאה הראשית: {e}")
        await application.stop()
        await application.shutdown()
        raise

    finally:
        # סגירה מסודרת
        await application.stop()
        await application.shutdown()
        logger.info("הבוט נסגר כראוי - זמן לכוס תה!")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("הבוט נעצר על ידי המשתמש!")
    except Exception as e:
        logger.error(f"שגיאה קריטית: {e}")