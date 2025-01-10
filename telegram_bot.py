import asyncio
import json
import os
import re
import csv
from pathlib import Path
import logging
from datetime import datetime

from telethon import TelegramClient, errors, functions, types
from telethon.sessions import StringSession

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
)

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    filename='bot.log',
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USERS = [int(uid) for uid in os.getenv("ADMIN_USERS", "").split(",") if uid.strip().isdigit()]

if not BOT_TOKEN:
    logger.error("BOT_TOKEN is not set in the .env file.")
    exit("BOT_TOKEN is not set in the .env file.")

# File to store sessions
SESSIONS_FILE = 'sessions.json'

# Load existing sessions
if os.path.exists(SESSIONS_FILE):
    with open(SESSIONS_FILE, 'r') as f:
        sessions = json.load(f)
else:
    sessions = {}

# Helper functions to manage sessions
def save_sessions():
    with open(SESSIONS_FILE, 'w') as f:
        json.dump(sessions, f, indent=4)

def get_session(user_id):
    return sessions.get(str(user_id), {})

def set_session(user_id, session_data):
    sessions[str(user_id)] = session_data
    save_sessions()

def remove_session(user_id):
    if str(user_id) in sessions:
        del sessions[str(user_id)]
        save_sessions()

# Define states for ConversationHandler
(
    API_ID, API_HASH, PHONE_NUMBER, CODE, PASSWORD,
    BLOCK_USER_ID
) = range(6)

# Initialize the Telegram Bot application
application = ApplicationBuilder().token(BOT_TOKEN).concurrent_updates(True).build()

# Function to check if user is admin
def is_admin(user_id):
    return user_id in ADMIN_USERS

# Command Handler: /start
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ شما اجازه استفاده از این ربات را ندارید.")
        return

    # Check if user has a session
    session_data = get_session(user_id)
    if not session_data.get("string_session"):
        # Prompt to set up Telegram account
        keyboard = [
            [InlineKeyboardButton("🔑 تنظیم حساب تلگرام", callback_data="setup_telegram")],
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("📂 آپلود مخاطبین CSV", callback_data="upload_csv")],
            [InlineKeyboardButton("➕ افزودن کاربران به گروه/کانال", callback_data="add_to_group")],
            [InlineKeyboardButton("🛑 مدیریت کاربران مسدود شده", callback_data="manage_blocked")],
            [InlineKeyboardButton("📤 صادرات داده‌ها", callback_data="export_data")],
            [InlineKeyboardButton("🔒 خروج از حساب تلگرام", callback_data="logout")],
            [InlineKeyboardButton("❌ خروج کامل", callback_data="exit")],
        ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "سلام! لطفاً یکی از گزینه‌های زیر را انتخاب کنید:", reply_markup=reply_markup
    )

# Command Handler: /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ شما اجازه استفاده از این ربات را ندارید.")
        return

    help_text = (
        "📄 **دستورات و گزینه‌ها:**\n\n"
        "/start - شروع ربات و نمایش گزینه‌ها\n"
        "/help - نمایش پیام راهنما\n"
        "/add_admin - افزودن ادمین جدید\n\n"
        "**گزینه‌ها از طریق دکمه‌ها:**\n"
        "• 🔑 تنظیم حساب تلگرام\n"
        "• 📂 آپلود مخاطبین CSV\n"
        "• ➕ افزودن کاربران به گروه/کانال\n"
        "• 🛑 مدیریت کاربران مسدود شده\n"
        "• 📤 صادرات داده‌ها\n"
        "• 🔒 خروج از حساب تلگرام\n"
        "• ❌ خروج کامل\n\n"
        "**نکات:**\n"
        "- اطمینان حاصل کنید که فایل‌های CSV حاوی شماره تلفن‌ها در فرمت بین‌المللی (مثلاً +1234567890) هستند.\n"
        "- فقط ادمین‌های تعریف شده می‌توانند از این ربات استفاده کنند."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

# Callback Query Handler
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await query.edit_message_text("❌ شما اجازه استفاده از این ربات را ندارید.")
        return

    data = query.data

    if data == "setup_telegram":
        await query.edit_message_text("🔑 لطفاً `API_ID` خود را وارد کنید:")
        return API_ID

    elif data == "upload_csv":
        await query.edit_message_text("📂 لطفاً فایل CSV حاوی شماره تلفن‌ها را ارسال کنید.")
        return

    elif data == "add_to_group":
        await query.edit_message_text("➕ لطفاً نام کاربری گروه یا کانالی که می‌خواهید کاربران را به آن اضافه کنید وارد کنید (مثلاً @yourgroup).")
        return

    elif data == "manage_blocked":
        await manage_blocked_menu(update, context)
        return

    elif data == "export_data":
        await export_data_menu(update, context)
        return

    elif data == "logout":
        remove_session(user_id)
        await query.edit_message_text("🔒 از حساب تلگرام خارج شدید.")
        await start_command(update, context)
        return

    elif data == "exit":
        await query.edit_message_text("❌ ربات با موفقیت متوقف شد.")
        await context.application.stop()
        return

    elif data.startswith("unblock_user_"):
        target_user_id = int(data.split("_")[-1])
        await unblock_user(update, context, target_user_id)
        return

    elif data == "export_added_users":
        await export_added_users(update, context)
        return

    elif data == "export_progress":
        await export_progress(update, context)
        return

    elif data == "list_user_ids":
        await list_user_ids(update, context)
        return

    elif data == "block_user_prompt":
        await block_user_prompt(update, context)
        return BLOCK_USER_ID

    elif data.startswith("unblock_user_"):
        target_user_id = int(data.split("_")[-1])
        await unblock_user(update, context, target_user_id)
        return

    elif data == "back_to_main":
        await start_command(update, context)
        return

# Conversation Handler for setting up Telegram account
async def api_id_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    api_id_text = update.message.text.strip()
    if not api_id_text.isdigit():
        await update.message.reply_text("❌ لطفاً یک `API_ID` معتبر (عدد) وارد کنید:")
        return API_ID

    context.user_data['api_id'] = int(api_id_text)
    await update.message.reply_text("🔑 لطفاً `API_HASH` خود را وارد کنید:")
    return API_HASH

async def api_hash_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    api_hash = update.message.text.strip()
    if not api_hash:
        await update.message.reply_text("❌ لطفاً یک `API_HASH` معتبر وارد کنید:")
        return API_HASH

    context.user_data['api_hash'] = api_hash
    await update.message.reply_text("📱 لطفاً شماره تلفن خود را به فرمت بین‌المللی (مثلاً +1234567890) وارد کنید:")
    return PHONE_NUMBER

async def phone_number_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone_number = update.message.text.strip()
    phone_regex = re.compile(r'^\+\d{10,15}$')
    if not phone_regex.match(phone_number):
        await update.message.reply_text("❌ لطفاً یک شماره تلفن معتبر به فرمت بین‌المللی (مثلاً +1234567890) وارد کنید:")
        return PHONE_NUMBER

    context.user_data['phone_number'] = phone_number
    await update.message.reply_text("🔄 در حال احراز هویت با Telegram. لطفاً منتظر بمانید...")

    # Initialize Telethon client with the provided credentials
    user_id = update.effective_user.id
    api_id = context.user_data['api_id']
    api_hash = context.user_data['api_hash']
    phone = context.user_data['phone_number']

    client = TelegramClient(StringSession(), api_id, api_hash)

    try:
        await client.connect()
        if not await client.is_user_authorized():
            await client.send_code_request(phone)
            await update.message.reply_text("📩 یک کد تایید به شماره تلفن شما ارسال شد. لطفاً کد را وارد کنید:")
            context.user_data['client'] = client
            return CODE
        else:
            # Already authorized
            string_session = client.session.save()
            set_session(user_id, {
                "string_session": string_session,
                "api_id": api_id,
                "api_hash": api_hash,
                "blocked_users": []
            })
            await client.disconnect()
            await update.message.reply_text("✅ حساب تلگرام شما با موفقیت تنظیم شد!")
            await start_command(update, context)
            return ConversationHandler.END
    except errors.ApiIdInvalidError:
        await client.disconnect()
        await update.message.reply_text("❌ `API_ID` یا `API_HASH` نامعتبر است. لطفاً دوباره امتحان کنید:")
        return API_ID
    except Exception as e:
        await client.disconnect()
        logger.exception(f"Error during authentication: {e}")
        await update.message.reply_text("❌ خطایی رخ داد. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

async def code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    client = context.user_data.get('client')

    if not client:
        await update.message.reply_text("❌ خطا در دسترسی به جلسه. لطفاً دوباره تنظیم کنید.")
        return ConversationHandler.END

    try:
        await client.sign_in(phone=context.user_data['phone_number'], code=code)
    except errors.SessionPasswordNeededError:
        await update.message.reply_text("🔒 احراز هویت دو مرحله‌ای فعال است. لطفاً رمز عبور خود را وارد کنید:")
        return PASSWORD
    except errors.CodeInvalidError:
        await update.message.reply_text("❌ کد تایید نامعتبر است. لطفاً دوباره کد را وارد کنید:")
        return CODE
    except Exception as e:
        await client.disconnect()
        logger.exception(f"Error during sign in: {e}")
        await update.message.reply_text("❌ خطایی رخ داد. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

    # Authentication successful
    string_session = client.session.save()
    user_id = update.effective_user.id
    api_id = context.user_data['api_id']
    api_hash = context.user_data['api_hash']
    set_session(user_id, {
        "string_session": string_session,
        "api_id": api_id,
        "api_hash": api_hash,
        "blocked_users": []
    })
    await client.disconnect()
    await update.message.reply_text("✅ حساب تلگرام شما با موفقیت تنظیم شد!")
    await start_command(update, context)
    return ConversationHandler.END

async def password_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    client = context.user_data.get('client')

    if not client:
        await update.message.reply_text("❌ خطا در دسترسی به جلسه. لطفاً دوباره تنظیم کنید.")
        return ConversationHandler.END

    try:
        await client.sign_in(password=password)
    except errors.PasswordHashInvalidError:
        await update.message.reply_text("❌ رمز عبور نادرست است. لطفاً دوباره وارد کنید:")
        return PASSWORD
    except Exception as e:
        await client.disconnect()
        logger.exception(f"Error during password sign in: {e}")
        await update.message.reply_text("❌ خطایی رخ داد. لطفاً دوباره امتحان کنید.")
        return ConversationHandler.END

    # Authentication successful
    string_session = client.session.save()
    user_id = update.effective_user.id
    api_id = context.user_data['api_id']
    api_hash = context.user_data['api_hash']
    set_session(user_id, {
        "string_session": string_session,
        "api_id": api_id,
        "api_hash": api_hash,
        "blocked_users": []
    })
    await client.disconnect()
    await update.message.reply_text("✅ حساب تلگرام شما با موفقیت تنظیم شد!")
    await start_command(update, context)
    return ConversationHandler.END

# Conversation Handler Setup
setup_telegram_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(button_handler, pattern='^setup_telegram$')],
    states={
        API_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, api_id_handler)],
        API_HASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, api_hash_handler)],
        PHONE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_number_handler)],
        CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, code_handler)],
        PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, password_handler)],
        BLOCK_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, block_user_input)],
    },
    fallbacks=[],
    allow_reentry=True
)

# Handler to add new admin via command
async def add_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ شما اجازه استفاده از این ربات را ندارید.")
        return

    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("❌ لطفاً شناسه کاربری تلگرام کاربر جدید را به صورت عددی و با فرمت: /add_admin <user_id> ارسال کنید.")
        return

    new_admin_id = int(context.args[0])
    if new_admin_id in ADMIN_USERS:
        await update.message.reply_text("🔍 این کاربر قبلاً ادمین است.")
        return

    ADMIN_USERS.append(new_admin_id)
    await update.message.reply_text(f"✅ کاربر با شناسه {new_admin_id} به لیست ادمین‌ها اضافه شد.")

    # Update the .env file
    env_path = Path('.env')
    if env_path.exists():
        with open(env_path, 'r') as f:
            lines = f.readlines()
        with open(env_path, 'w') as f:
            for line in lines:
                if line.startswith("ADMIN_USERS="):
                    admin_users_str = ",".join(map(str, ADMIN_USERS))
                    f.write(f"ADMIN_USERS={admin_users_str}\n")
                else:
                    f.write(line)
    else:
        with open(env_path, 'w') as f:
            admin_users_str = ",".join(map(str, ADMIN_USERS))
            f.write(f"ADMIN_USERS={admin_users_str}\n")

# Handler to upload CSV
async def upload_csv_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ شما اجازه استفاده از این ربات را ندارید.")
        return

    if update.message.document:
        file = update.message.document
        if not file.file_name.endswith(".csv"):
            await update.message.reply_text("❌ لطفاً یک فایل CSV معتبر ارسال کنید.")
            return

        file_path = await file.get_file().download()
        await update.message.reply_text("🔄 در حال پردازش فایل CSV شما. لطفاً صبر کنید...")

        try:
            results = await process_csv(user_id, file_path, download_photos=False)
            # Save results to JSON
            result_file = Path(f"results_{user_id}.json")
            with open(result_file, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=4, ensure_ascii=False)

            # Prepare a summary
            total = len(results)
            valid = len([v for v in results.values() if "id" in v])
            invalid = total - valid
            summary = f"✅ **پردازش کامل شد!**\n\nکل مخاطبین: {total}\nکاربران معتبر تلگرام: {valid}\nنامعتبر/یافت نشده: {invalid}"

            # Send summary and the results file
            await update.message.reply_text(summary, parse_mode="Markdown")
            await update.message.reply_document(
                document=InputFile(result_file),
                filename=f"results_{user_id}.json",
                caption="📁 این نتایج بررسی شماره تلفن‌های شما است."
            )
        except Exception as e:
            logger.error(f"Error processing CSV: {e}")
            await update.message.reply_text("❌ هنگام پردازش فایل CSV خطایی رخ داد.")
    else:
        await update.message.reply_text("❌ لطفاً یک فایل CSV ارسال کنید.")

# Function to validate and process CSV
async def process_csv(user_id: int, file_path: str, download_photos: bool):
    """Process a CSV file with phone numbers."""
    phone_numbers = []
    with open(file_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile)
        header = next(reader, None)  # Skip header if exists
        for row in reader:
            if row:
                phone = row[0].strip()
                if phone:
                    phone_numbers.append(phone)

    results = {}
    for phone in phone_numbers:
        # Check if user is blocked
        session_data = get_session(user_id)
        blocked_users = session_data.get("blocked_users", [])
        if phone in blocked_users:
            results[phone] = {"error": "کاربر مسدود شده است."}
            continue
        results[phone] = await get_names(user_id, phone, download_photos)
        await asyncio.sleep(1)  # Avoid hitting API rate limits
    return results

async def get_names(user_id: int, phone_number: str, download_profile_photos: bool) -> dict:
    """Check if a phone number is associated with a Telegram account."""
    result = {}
    try:
        session_data = get_session(user_id)
        if not session_data.get("string_session") or not session_data.get("api_id") or not session_data.get("api_hash"):
            result.update({"error": "حساب تلگرام شما تنظیم نشده است."})
            return result

        string_session = session_data.get("string_session")
        api_id = session_data.get("api_id")
        api_hash = session_data.get("api_hash")

        client = TelegramClient(StringSession(string_session), api_id, api_hash)
        await client.connect()

        contact = types.InputPhoneContact(
            client_id=0, phone=phone_number, first_name="", last_name=""
        )
        contacts = await client(functions.contacts.ImportContactsRequest([contact]))
        users = contacts.users
        number_of_matches = len(users)

        if number_of_matches == 0:
            result.update({
                "error": "هیچ پاسخی دریافت نشد، شماره تلفن در تلگرام وجود ندارد یا دسترسی اضافه کردن مخاطب مسدود شده است."
            })
        elif number_of_matches == 1:
            user = users[0]
            result.update({
                "id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "fake": user.fake,
                "verified": user.verified,
                "premium": user.premium,
                "mutual_contact": user.mutual_contact,
                "bot": user.bot,
                "bot_chat_history": user.bot_chat_history,
                "restricted": user.restricted,
                "restriction_reason": user.restriction_reason,
                "user_was_online": get_human_readable_user_status(user.status),
                "phone": user.phone,
            })
            if download_profile_photos and user.photo:
                try:
                    photo_output_path = Path(f"photos/{user.id}_{phone_number}_photo.jpeg")
                    photo_output_path.parent.mkdir(parents=True, exist_ok=True)
                    logger.info(f"Attempting to download profile photo for {user.id} ({phone_number})")
                    photo = await client.download_profile_photo(
                        user, file=photo_output_path, download_big=True
                    )
                    if photo is not None:
                        logger.info(f"Photo downloaded at '{photo}'")
                        result["photo_path"] = str(photo)
                    else:
                        logger.info(f"No photo found for {user.id} ({phone_number})")
                except Exception as e:
                    logger.exception(f"Unable to download profile photo for {phone_number}. Error: {e}")
        else:
            result.update({
                "error": "این شماره تلفن با چندین حساب تلگرام مطابقت دارد، که غیرمنتظره است."
            })

        # Clean up by deleting the imported contact
        try:
            if "id" in result:
                await client(functions.contacts.DeleteContactsRequest(id=[user.id]))
            else:
                await client(functions.contacts.DeleteContactsRequest(id=[]))
        except Exception as e:
            logger.warning(f"Failed to delete contact {phone_number}: {e}")

        await client.disconnect()
    except Exception as e:
        logger.exception(f"Unhandled exception for phone {phone_number}: {e}")
        result.update({"error": f"خطای غیرمنتظره: {e}."})
    return result

def get_human_readable_user_status(status: types.TypeUserStatus):
    """Convert Telegram user status to a human-readable format."""
    if isinstance(status, types.UserStatusOnline):
        return "آنلاین است"
    elif isinstance(status, types.UserStatusOffline):
        return status.was_online.strftime("%Y-%m-%d %H:%M:%S")
    elif isinstance(status, types.UserStatusRecently):
        return "به تازگی دیده شده"
    elif isinstance(status, types.UserStatusLastWeek):
        return "هفته گذشته دیده شده"
    elif isinstance(status, types.UserStatusLastMonth):
        return "ماه گذشته دیده شده"
    else:
        return "ناشناس"

# Function to export added users
async def export_added_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export the list of added users as a JSON file."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ شما اجازه استفاده از این ربات را ندارید.")
        return

    result_file = Path(f"results_{user_id}.json")
    if not result_file.exists():
        await update.message.reply_text("❌ فایل نتایج موجود نیست. لطفاً ابتدا یک فایل CSV آپلود کنید.")
        return

    await update.message.reply_document(
        document=InputFile(result_file),
        filename=f"results_{user_id}.json",
        caption="📁 لیست کاربران اضافه شده شما"
    )

# Function to export progress phone
async def export_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export the progress of phone processing as a JSON file."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ شما اجازه استفاده از این ربات را ندارید.")
        return

    result_file = Path(f"results_{user_id}.json")
    if not result_file.exists():
        await update.message.reply_text("❌ فایل نتایج موجود نیست. لطفاً ابتدا یک فایل CSV آپلود کنید.")
        return

    await update.message.reply_document(
        document=InputFile(result_file),
        filename=f"progress_{user_id}.json",
        caption="📁 پیشرفت پردازش شماره تلفن‌های شما"
    )

# List user IDs
async def list_user_ids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all user IDs processed."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ شما اجازه استفاده از این ربات را ندارید.")
        return

    result_file = Path(f"results_{user_id}.json")
    if not result_file.exists():
        await update.message.reply_text("❌ فایل نتایج موجود نیست. لطفاً ابتدا یک فایل CSV آپلود کنید.")
        return

    with open(result_file, "r", encoding="utf-8") as f:
        results = json.load(f)

    user_ids = [str(data["id"]) for data in results.values() if "id" in data]
    user_ids_str = ", ".join(user_ids) if user_ids else "هیچ کاربری اضافه نشده است."

    await update.message.reply_text(f"🔢 **لیست شناسه‌های کاربران اضافه شده:**\n{user_ids_str}")

# Function to manage blocked users menu
async def manage_blocked_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display the manage blocked users menu."""
    query = update.callback_query
    user_id = update.effective_user.id

    # Fetch blocked users
    blocked_users = sessions.get(str(user_id), {}).get("blocked_users", [])

    if not blocked_users:
        blocked_text = "🛑 **لیست کاربران مسدود شده خالی است.**"
    else:
        blocked_text = "🛑 **لیست کاربران مسدود شده:**\n\n" + "\n".join([f"• {uid}" for uid in blocked_users])

    # Options to block a new user or unblock existing ones
    keyboard = [
        [InlineKeyboardButton("➕ مسدود کردن کاربر جدید", callback_data="block_user_prompt")],
    ]

    if blocked_users:
        for uid in blocked_users:
            keyboard.append([
                InlineKeyboardButton(f"🔓 بازگشایی مسدودیت کاربر {uid}", callback_data=f"unblock_user_{uid}")
            ])

    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(blocked_text, reply_markup=reply_markup)

# Handler to add users to group/channel
async def add_to_group_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ شما اجازه استفاده از این ربات را ندارید.")
        return

    group_username = update.message.text.strip()
    if not group_username.startswith("@"):
        await update.message.reply_text("❌ لطفاً نام کاربری گروه/کانال را با @ شروع کنید (مثلاً @yourgroup).")
        return

    await update.message.reply_text(f"🔄 در حال افزودن کاربران به {group_username}. لطفاً صبر کنید...")

    try:
        # Initialize Telethon client for this user
        session_data = get_session(user_id)
        if not session_data.get("string_session") or not session_data.get("api_id") or not session_data.get("api_hash"):
            await update.message.reply_text("❌ حساب تلگرام شما تنظیم نشده است.")
            return

        string_session = session_data.get("string_session")
        api_id = session_data.get("api_id")
        api_hash = session_data.get("api_hash")

        client = TelegramClient(StringSession(string_session), api_id, api_hash)
        await client.connect()

        group = await client.get_entity(group_username)

        # Load last results
        result_file = Path(f"results_{user_id}.json")
        if not result_file.exists():
            await update.message.reply_text("❌ فایل نتایج موجود نیست. لطفاً ابتدا یک فایل CSV آپلود کنید.")
            await client.disconnect()
            return

        with open(result_file, "r", encoding="utf-8") as f:
            results = json.load(f)

        added_users = []
        failed_users = []
        total_valid = len([v for v in results.values() if "id" in v])
        current = 0

        for phone, data in results.items():
            if "id" in data:
                # Check if the user is blocked
                blocked_users = session_data.get("blocked_users", [])
                if data["id"] in blocked_users:
                    logger.info(f"User {data['id']} is blocked and will not be added.")
                    continue

                try:
                    user = await client.get_entity(data["id"])
                    await client(functions.messages.AddChatUserRequest(
                        chat_id=group.id,
                        user_id=user,
                        fwd_limit=10  # Number of recent messages to forward
                    ))
                    added_users.append(user.username or str(user.id))
                    current += 1
                    # Send progress update
                    progress = f"✅ افزودن {current} از {total_valid} کاربران موفقیت‌آمیز بود."
                    await update.message.reply_text(progress)
                    # To avoid hitting rate limits
                    await asyncio.sleep(1)  # Adjust as necessary
                except Exception as e:
                    logger.error(f"افزودن کاربر {data['id']} به گروه ناموفق بود: {e}")
                    failed_users.append(phone)
                    await asyncio.sleep(1)  # Adjust as necessary

        # Prepare a summary
        success_count = len(added_users)
        failure_count = len(failed_users)
        summary = f"✅ **افزودن کاربران به گروه/کانال کامل شد!**\n\nتعداد موفق: {success_count}\nتعداد ناموفق: {failure_count}"

        await update.message.reply_text(summary, parse_mode="Markdown")

        if added_users:
            added_list = ", ".join(added_users)
            await update.message.reply_text(f"🟢 **کاربران اضافه شده:**\n{added_list}")

        if failed_users:
            failed_list = ", ".join(failed_users)
            await update.message.reply_text(f"🔴 **کاربران اضافه نشده:**\n{failed_list}")

        await client.disconnect()

    except Exception as e:
        logger.error(f"Error adding users to group: {e}")
        await update.message.reply_text(f"❌ خطایی رخ داد: {e}")

# Handler to unblock a user
async def unblock_user(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int):
    """Unblock a user."""
    user_id = update.effective_user.id
    session = get_session(user_id)
    blocked_users = session.get("blocked_users", [])

    if target_user_id in blocked_users:
        blocked_users.remove(target_user_id)
        set_session(user_id, {
            "string_session": session.get("string_session"),
            "api_id": session.get("api_id"),
            "api_hash": session.get("api_hash"),
            "blocked_users": blocked_users
        })
        await update.callback_query.edit_message_text(f"✅ کاربر با شناسه {target_user_id} از لیست مسدود شده‌ها حذف شد.")
    else:
        await update.callback_query.edit_message_text(f"🔍 کاربر با شناسه {target_user_id} در لیست مسدود شده‌ها یافت نشد.")

    await manage_blocked_menu(update, context)

# Handler to prompt blocking a user
async def block_user_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt admin to enter a user ID to block."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("➕ لطفاً شناسه کاربری تلگرام کاربری که می‌خواهید مسدود کنید را وارد کنید (عدد):")
    return BLOCK_USER_ID

# Handler to handle blocking a user
async def block_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle input for blocking a new user."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ شما اجازه استفاده از این ربات را ندارید.")
        return

    target_user_id_text = update.message.text.strip()
    if not target_user_id_text.isdigit():
        await update.message.reply_text("❌ لطفاً یک شناسه کاربری تلگرام معتبر (عدد) وارد کنید:")
        return BLOCK_USER_ID

    target_user_id = int(target_user_id_text)
    session = get_session(user_id)
    blocked_users = session.get("blocked_users", [])

    if target_user_id in blocked_users:
        await update.message.reply_text(f"🔍 کاربر با شناسه {target_user_id} قبلاً مسدود شده است.")
    else:
        blocked_users.append(target_user_id)
        set_session(user_id, {
            "string_session": session.get("string_session"),
            "api_id": session.get("api_id"),
            "api_hash": session.get("api_hash"),
            "blocked_users": blocked_users
        })
        await update.message.reply_text(f"✅ کاربر با شناسه {target_user_id} با موفقیت مسدود شد.")

    # Return to manage blocked menu
    await manage_blocked_menu(update, context)
    return ConversationHandler.END

# Function to export added users
async def export_added_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export the list of added users as a JSON file."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ شما اجازه استفاده از این ربات را ندارید.")
        return

    result_file = Path(f"results_{user_id}.json")
    if not result_file.exists():
        await update.message.reply_text("❌ فایل نتایج موجود نیست. لطفاً ابتدا یک فایل CSV آپلود کنید.")
        return

    await update.message.reply_document(
        document=InputFile(result_file),
        filename=f"results_{user_id}.json",
        caption="📁 لیست کاربران اضافه شده شما"
    )

# Function to export progress phone
async def export_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export the progress of phone processing as a JSON file."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ شما اجازه استفاده از این ربات را ندارید.")
        return

    result_file = Path(f"results_{user_id}.json")
    if not result_file.exists():
        await update.message.reply_text("❌ فایل نتایج موجود نیست. لطفاً ابتدا یک فایل CSV آپلود کنید.")
        return

    await update.message.reply_document(
        document=InputFile(result_file),
        filename=f"progress_{user_id}.json",
        caption="📁 پیشرفت پردازش شماره تلفن‌های شما"
    )

# List user IDs
async def list_user_ids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all user IDs processed."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ شما اجازه استفاده از این ربات را ندارید.")
        return

    result_file = Path(f"results_{user_id}.json")
    if not result_file.exists():
        await update.message.reply_text("❌ فایل نتایج موجود نیست. لطفاً ابتدا یک فایل CSV آپلود کنید.")
        return

    with open(result_file, "r", encoding="utf-8") as f:
        results = json.load(f)

    user_ids = [str(data["id"]) for data in results.values() if "id" in data]
    user_ids_str = ", ".join(user_ids) if user_ids else "هیچ کاربری اضافه نشده است."

    await update.message.reply_text(f"🔢 **لیست شناسه‌های کاربران اضافه شده:**\n{user_ids_str}")

# Handler to manage text messages for blocking
async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages for prompts like adding to group or blocking users."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ شما اجازه استفاده از این ربات را ندارید.")
        return

    text = update.message.text.strip()

    if text.startswith("@"):
        await add_to_group_handler(update, context)
    elif text.isdigit():
        # Assume it's a user ID to block
        await block_user_input(update, context)
    else:
        await update.message.reply_text("❓ لطفاً از دکمه‌های ارائه شده استفاده کنید یا یک دستور معتبر ارسال کنید.")

# Main function to run the bot
async def main_bot():
    """Main function to run the bot."""
    # Register handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("add_admin", add_admin_command))
    application.add_handler(setup_telegram_conv)
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.Document.ALL, upload_csv_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))

    # Start the bot
    logger.info("Bot is running...")
    await application.run_polling()

if __name__ == "__main__":
    try:
        # Start the main_bot coroutine
        asyncio.run(main_bot())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.exception(f"Unhandled exception: {e}")
