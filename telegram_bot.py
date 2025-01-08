import asyncio
import json
import os
import re
import csv
from pathlib import Path
from getpass import getpass
import logging

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
    filters,
)

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    filename='logs/bot.log',
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "")
ADMIN_USERS = [int(uid) for uid in os.getenv("ADMIN_USERS", "").split(",") if uid.strip().isdigit()]

# Initialize Telethon client
telethon_client = TelegramClient('session_name', API_ID, API_HASH)

# Global variable to store processed results
last_results = {}

def get_human_readable_user_status(status: types.TypeUserStatus) -> str:
    """Convert Telegram user status to a human-readable format in Persian."""
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

async def authenticate_telethon():
    """Authenticate the Telethon client."""
    await telethon_client.connect()
    if not await telethon_client.is_user_authorized():
        try:
            await telethon_client.send_code_request(PHONE_NUMBER)
            code = input("Please enter the code you received: ")
            await telethon_client.sign_in(PHONE_NUMBER, code)
        except errors.SessionPasswordNeededError:
            pw = getpass("Two-step verification is enabled. Please enter your password: ")
            await telethon_client.sign_in(password=pw)
    logger.info("Telethon client authenticated.")

async def get_user_info(client: TelegramClient, phone_number: str, download_profile_photos: bool = False) -> dict:
    """
    Check if a phone number is associated with a Telegram account and retrieve user information.

    Args:
        client (TelegramClient): Telethon client.
        phone_number (str): Phone number to check.
        download_profile_photos (bool): Whether to download the user's profile photo.

    Returns:
        dict: Dictionary containing user information or error messages.
    """
    result = {}
    logger.info(f"Checking phone number: {phone_number}")
    try:
        contact = types.InputPhoneContact(
            client_id=0, phone=phone_number, first_name="", last_name=""
        )
        contacts = await client(functions.contacts.ImportContactsRequest([contact]))
        users = contacts.users
        number_of_matches = len(users)

        if number_of_matches == 0:
            result.update(
                {
                    "error": "هیچ پاسخی دریافت نشد، شماره تلفن در تلگرام وجود ندارد یا دسترسی اضافه کردن مخاطب مسدود شده است."
                }
            )
        elif number_of_matches == 1:
            # Clean up by deleting the contact
            await client(functions.contacts.DeleteContactsRequest(id=[users[0].id]))
            user = users[0]
            result.update(
                {
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
                }
            )
            if download_profile_photos:
                try:
                    photo_output_path = Path(f"photos/{user.id}_{phone_number}_photo.jpeg")
                    photo_output_path.parent.mkdir(parents=True, exist_ok=True)
                    logger.info(f"Attempting to download profile photo for user {user.id} ({phone_number})")
                    photo = await client.download_profile_photo(
                        user, file=photo_output_path, download_big=True
                    )
                    if photo is not None:
                        logger.info(f"Photo downloaded at '{photo}'")
                        result["photo_path"] = str(photo)
                    else:
                        logger.info(f"No photo found for user {user.id} ({phone_number})")
                except Exception as e:
                    logger.exception(f"Failed to download profile photo for {phone_number}. Error: {e}")
        else:
            result.update(
                {
                    "error": "این شماره تلفن با چند حساب تلگرام مطابقت دارد، که غیرمنتظره است."
                }
            )

    except TypeError as e:
        result.update(
            {
                "error": f"TypeError: {e}. احتمالاً به دلیل ناتوانی در حذف مخاطب رخ داده است."
            }
        )
    except Exception as e:
        result.update({"error": f"خطای غیرمنتظره: {e}."})
        logger.exception(f"Error checking phone number {phone_number}: {e}")
    logger.info(f"Finished checking phone number: {phone_number}")
    return result

async def validate_users(client: TelegramClient, phone_numbers: list, download_profile_photos: bool) -> dict:
    """
    Validate a list of phone numbers.

    Args:
        client (TelegramClient): Telethon client.
        phone_numbers (list): List of phone numbers to validate.
        download_profile_photos (bool): Whether to download profile photos.

    Returns:
        dict: Dictionary with phone numbers as keys and validation results as values.
    """
    result = {}
    try:
        total = len(phone_numbers)
        for idx, phone in enumerate(phone_numbers, 1):
            phone = re.sub(r"\s+", "", phone, flags=re.UNICODE)
            if phone not in result:
                res = await get_user_info(client, phone, download_profile_photos)
                result[phone] = res
                # Prevent hitting rate limits
                await asyncio.sleep(1)  # Adjust as needed
                # Log progress
                progress = f"🔄 Processing phone number {idx} of {total}"
                logger.info(progress)
    except Exception as e:
        logger.error(f"Error during validation: {e}")
    return result

def save_results(output: str, res: dict) -> None:
    """Save results to a JSON file."""
    with open(output, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=4, ensure_ascii=False)
    logger.info(f"Results saved to {output}")

async def process_csv(file_path: str, download_photos: bool) -> dict:
    """
    Process the uploaded CSV file and validate phone numbers.

    Args:
        file_path (str): Path to the CSV file.
        download_photos (bool): Whether to download profile photos.

    Returns:
        dict: Validation results.
    """
    phone_numbers = []
    with open(file_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile)
        header = next(reader, None)
        for row in reader:
            if row:
                phone = row[0].strip()
                if phone:
                    phone_numbers.append(phone)

    logger.info(f"Total phone numbers to process: {len(phone_numbers)}")
    results = await validate_users(
        telethon_client, phone_numbers, download_profile_photos=download_photos
    )
    return results

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle adding a new admin."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_USERS:
        await update.message.reply_text("❌ شما اجازه استفاده از این ربات را ندارید.")
        return

    if not context.args:
        await update.message.reply_text("❌ لطفاً شناسه کاربری تلگرام کاربر جدید را ارسال کنید. به صورت: /add_admin <user_id>")
        return

    try:
        new_admin_id = int(context.args[0])
        if new_admin_id not in ADMIN_USERS:
            ADMIN_USERS.append(new_admin_id)
            # Update the .env file
            admin_users_str = ",".join(map(str, ADMIN_USERS))
            env_path = Path(".env")
            if env_path.exists():
                with env_path.open("r+", encoding="utf-8") as f:
                    lines = f.readlines()
                    f.seek(0)
                    for line in lines:
                        if line.startswith("ADMIN_USERS="):
                            f.write(f"ADMIN_USERS={admin_users_str}\n")
                        else:
                            f.write(line)
                    f.truncate()
            else:
                with env_path.open("w", encoding="utf-8") as f:
                    f.write(f"ADMIN_USERS={admin_users_str}\n")
            await update.message.reply_text("✅ کاربر جدید به لیست ادمین‌ها اضافه شد.")
        else:
            await update.message.reply_text("🔍 این کاربر قبلاً ادمین است.")
    except ValueError:
        await update.message.reply_text("❌ شناسه کاربری باید یک عدد باشد.")

# Telegram bot handlers

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message and display the keyboard options."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_USERS:
        await update.message.reply_text("❌ شما اجازه استفاده از این ربات را ندارید.")
        return

    keyboard = [
        [InlineKeyboardButton("🔑 ورود به حساب تلگرام", callback_data="login")],
        [InlineKeyboardButton("📂 آپلود مخاطبین CSV", callback_data="upload_csv")],
        [InlineKeyboardButton("➕ افزودن کاربران به گروه/کانال", callback_data="add_to_group")],
        [InlineKeyboardButton("➕ افزودن ادمین جدید", callback_data="add_admin")],
        [InlineKeyboardButton("🔒 خروج از حساب تلگرام", callback_data="logout")],
        [InlineKeyboardButton("❌ خروج کامل", callback_data="exit")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "سلام! لطفاً یکی از گزینه‌های زیر را انتخاب کنید:", reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a help message."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_USERS:
        await update.message.reply_text("❌ شما اجازه استفاده از این ربات را ندارید.")
        return

    help_text = (
        "📄 **دستورات و گزینه‌ها:**\n\n"
        "/start - شروع ربات و نمایش گزینه‌ها\n"
        "/help - نمایش پیام راهنما\n"
        "/add_admin - افزودن ادمین جدید (استفاده: /add_admin <user_id>)\n\n"
        "**گزینه‌ها از طریق دکمه‌ها:**\n"
        "• 🔑 ورود به حساب تلگرام\n"
        "• 📂 آپلود مخاطبین CSV\n"
        "• ➕ افزودن کاربران به گروه/کانال\n"
        "• ➕ افزودن ادمین جدید\n"
        "• 🔒 خروج از حساب تلگرام\n"
        "• ❌ خروج کامل\n\n"
        "**نکات:**\n"
        "- اطمینان حاصل کنید که فایل‌های CSV حاوی شماره تلفن‌ها در فرمت بین‌المللی (مثلاً +1234567890) هستند.\n"
        "- فقط ادمین‌های تعریف شده می‌توانند از این ربات استفاده کنند."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button presses."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id not in ADMIN_USERS:
        await query.edit_message_text("❌ شما اجازه استفاده از این ربات را ندارید.")
        return

    if query.data == "login":
        await query.edit_message_text(
            "🔑 **کلاینت تلگرام قبلاً احراز هویت شده است.**\n"
            "اگر نیاز به احراز هویت مجدد دارید، لطفاً ربات را مجدداً راه‌اندازی کنید."
        )
    elif query.data == "upload_csv":
        await query.edit_message_text(
            "📂 لطفاً فایل CSV حاوی شماره تلفن‌ها را ارسال کنید."
        )
    elif query.data == "add_to_group":
        await query.edit_message_text(
            "➕ لطفاً نام کاربری گروه یا کانالی که می‌خواهید کاربران را به آن اضافه کنید وارد کنید (مثلاً @yourgroup)."
        )
    elif query.data == "add_admin":
        await query.edit_message_text(
            "➕ لطفاً شناسه کاربری تلگرام کاربر جدید را ارسال کنید. به صورت عددی و با فرمت: /add_admin <user_id>"
        )
    elif query.data == "logout":
        await telethon_client.disconnect()
        await query.edit_message_text("🔒 از حساب تلگرام خارج شدید.")
    elif query.data == "exit":
        await query.edit_message_text("❌ ربات با موفقیت متوقف شد.")
        await telethon_client.disconnect()
        # Optionally, you can stop the bot here
        # sys.exit()

async def handle_csv_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle CSV file uploads."""
    global last_results
    user_id = update.effective_user.id
    if user_id not in ADMIN_USERS:
        await update.message.reply_text("❌ شما اجازه استفاده از این ربات را ندارید.")
        return

    if update.message.document:
        file = update.message.document
        if not (file.file_name.endswith(".csv") or file.mime_type == "text/csv"):
            await update.message.reply_text("❌ لطفاً یک فایل CSV معتبر ارسال کنید.")
            return

        file_path = await file.get_file().download()
        await update.message.reply_text("🔄 در حال پردازش فایل CSV شما. لطفاً صبر کنید...")

        try:
            results = await process_csv(file_path, download_photos=False)
            last_results = results  # Store results for later use

            # Prepare summary
            total = len(results)
            valid = len([v for v in results.values() if "id" in v])
            invalid = total - valid
            summary = f"✅ **پردازش کامل شد!**\n\nکل مخاطبین: {total}\nکاربران معتبر تلگرام: {valid}\nنامعتبر/یافت نشده: {invalid}"

            # Save results to JSON
            result_file = Path("results.json")
            with result_file.open("w", encoding="utf-8") as f:
                json.dump(results, f, indent=4, ensure_ascii=False)

            # Send summary and results file
            await update.message.reply_text(summary, parse_mode="Markdown")
            await update.message.reply_document(
                document=InputFile(result_file),
                filename="results.json",
                caption="📁 این نتایج بررسی شماره تلفن‌های شما است."
            )
        except Exception as e:
            logger.error(f"Error processing CSV: {e}")
            await update.message.reply_text("❌ هنگام پردازش فایل CSV خطایی رخ داد.")
    else:
        await update.message.reply_text("❌ لطفاً یک فایل CSV ارسال کنید.")

async def add_to_group_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle adding users to a group/channel."""
    global last_results
    user_id = update.effective_user.id
    if user_id not in ADMIN_USERS:
        await update.message.reply_text("❌ شما اجازه استفاده از این ربات را ندارید.")
        return

    if not last_results:
        await update.message.reply_text("⚠️ هیچ نتایجی یافت نشد. لطفاً ابتدا یک فایل CSV ارسال و پردازش کنید.")
        return

    if update.message.text:
        group_username = update.message.text.strip()
        if not group_username.startswith("@"):
            await update.message.reply_text("❌ لطفاً نام کاربری گروه/کانال را با @ شروع کنید (مثلاً @yourgroup).")
            return

        await update.message.reply_text(f"🔄 در حال افزودن کاربران به {group_username}. لطفاً صبر کنید...")

        try:
            group = await telethon_client.get_entity(group_username)
        except Exception as e:
            await update.message.reply_text(f"❌ یافتن گروه/کانال `{group_username}` ناموفق بود. خطا: {e}")
            return

        added_users = []
        failed_users = []
        valid_users = [v for v in last_results.values() if "id" in v]
        total_valid = len(valid_users)
        current = 0

        for phone, data in last_results.items():
            if "id" in data:
                user_id_telegram = data["id"]
                try:
                    user = await telethon_client.get_entity(user_id_telegram)
                    await telethon_client(functions.channels.InviteToChannelRequest(
                        channel=group,
                        users=[user]
                    ))
                    added_users.append(user.username or str(user.id))
                    current += 1
                    # Send progress update every 5 users or on completion
                    if current % 5 == 0 or current == total_valid:
                        progress = f"✅ افزودن {current} از {total_valid} کاربران موفقیت‌آمیز بود."
                        await update.message.reply_text(progress)
                    # Prevent hitting rate limits
                    await asyncio.sleep(1)  # Adjust as needed
                except errors.UserPrivacyRestrictedError:
                    logger.error(f"Adding user {user_id_telegram} to group encountered privacy restrictions.")
                    failed_users.append(phone)
                    await asyncio.sleep(1)
                except errors.UserAlreadyParticipantError:
                    logger.info(f"User {user_id_telegram} is already a member of the group.")
                except Exception as e:
                    logger.error(f"Failed to add user {user_id_telegram} to group: {e}")
                    failed_users.append(phone)
                    await asyncio.sleep(1)

        # Prepare summary
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

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages for actions like adding to a group."""
    if update.message.text.startswith("@"):
        await add_to_group_prompt(update, context)
    else:
        await update.message.reply_text("❓ لطفاً از دکمه‌های ارائه شده استفاده کنید یا یک دستور معتبر ارسال کنید.")

# Main function to run the bot and Telethon client

async def main():
    """Main function to run the bot and Telethon client."""
    # Authenticate Telethon client
    await authenticate_telethon()

    # Initialize Telegram bot
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("add_admin", add_admin))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.Document.MIME_TYPE("text/csv"), handle_csv_upload))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))

    # Run the bot
    logger.info("Bot is running...")
    await application.run_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user.")
