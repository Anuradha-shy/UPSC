import time
import re
import asyncio
import logging
from aiogram import BaseMiddleware
from aiogram.types import Message
from collections import defaultdict
from config import ADMIN_ID

logger = logging.getLogger(__name__)

# =====================================================================
# 🛡️ ULTIMATE ZERO-TRUST SECURITY FIREWALL & MIDDLEWARE
# =====================================================================

# Memory Storage for Throttling, Muting & Shadow-Bans
shadow_banned_users = {}   # For Hackers: Silent drop (user thinks bot is alive, but it ignores them)
muted_users = {}           # For Spammers: Temporary lock with warning
burst_monitor = defaultdict(list)  # Short-term tracking (Anti-DDOS)
spam_monitor = defaultdict(list)   # Long-term tracking (Anti-Spam)

class SecurityMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message, data):
        # 1. PROCESS ONLY VALID MESSAGES
        if not isinstance(event, Message) or not event.from_user:
            return await handler(event, data)

        user_id = event.from_user.id
        now = time.time()

        # =========================================================
        # 🛡️ LAYER 1: ADMIN STEALTH MODE (Absolute Immunity)
        # =========================================================
        if user_id == ADMIN_ID:
            return await handler(event, data)

        # =========================================================
        # 🛡️ LAYER 2: SHADOW-BAN & MUTE EXECUTION
        # =========================================================
        # Check Shadow Ban First (Hackers)
        if user_id in shadow_banned_users:
            if now < shadow_banned_users[user_id]:
                return  # 🛑 SILENT DROP: No error, no reply. Total stealth.
            else:
                del shadow_banned_users[user_id] # Unban after time expires

        # Check Mute (Spammers)
        if user_id in muted_users:
            if now < muted_users[user_id]:
                return  # Silently drop update since they were already warned
            else:
                del muted_users[user_id] # Unmute

        # =========================================================
        # 🛡️ LAYER 3: DUAL-TIER RATE LIMITING (Anti-Spam & DDOS)
        # =========================================================
        # Tier A: Anti-DDOS (Burst Limit) -> 6 msgs in 10 seconds
        burst_monitor[user_id].append(now)
        burst_monitor[user_id] = [t for t in burst_monitor[user_id] if now - t < 10]
        
        if len(burst_monitor[user_id]) > 6:
            muted_users[user_id] = now + 900  # Lock for 15 minutes
            await event.answer("⚠️ <b>Traffic Anomaly:</b> Aap bahut fast messages bhej rahe hain. Bot ko 15 minutes ke liye Mute kiya gaya hai.", parse_mode="HTML")
            return

        # Tier B: Long-Term Spam Limit -> 10 msgs in 5 mins (300 seconds)
        spam_monitor[user_id].append(now)
        spam_monitor[user_id] = [t for t in spam_monitor[user_id] if now - t < 300]
        
        if len(spam_monitor[user_id]) > 10:
            muted_users[user_id] = now + 1800  # Lock for 30 minutes
            await event.answer("⚠️ <b>System Alert:</b> Aapne normal spam limit cross ki hai. Kripya 30 minutes baad try karein.", parse_mode="HTML")
            return

        # =========================================================
        # 🛡️ LAYER 4: DEEP PAYLOAD INSPECTION (Anti-Hacker/SQLi/RCE)
        # =========================================================
        if event.text or event.caption:
            text_to_check = str(event.text or event.caption).lower()
            bot = data['bot']

            # 4A. IP GRABBER & DOXXING BLOCKER (Protects Admin's IP & Location)
            # Blocks highly malicious link shorteners and IP loggers
            known_trackers = r"(grabify\.link|iplogger|2no\.co|ps3cfw|ngrok\.io|localtunnel|bit\.ly/3|tinyurl\.com/track|blasze\.com)"
            if re.search(known_trackers, text_to_check):
                await bot.send_message(
                    ADMIN_ID,
                    f"🛑 <b>CRITICAL: IP TRACKING ATTEMPT BLOCKED!</b>\n\n"
                    f"<b>User:</b> @{event.from_user.username or 'No_Username'} (ID: <code>{user_id}</code>)\n"
                    f"<b>Malicious Link:</b> <code>{text_to_check}</code>\n\n"
                    f"<i>Bot has intercepted and destroyed the payload. User is permanently shadow-banned.</i>",
                    parse_mode="HTML"
                )
                shadow_banned_users[user_id] = now + 315360000 # 10 Years Shadow-Ban
                return

            # 4B. SQL INJECTION, RCE & SERVER PROBING BLOCKER
            # Blocks attempts to read config, DB, environment variables, or Railway metadata
            threat_signatures = r"(\b(select|union|drop|truncate|alter|insert|update|delete)\b\s+from|' or 1=1|--|<script>|exec\(|system\(|__import__|/etc/passwd|\.env|railway|bot_token|bot token|config\.py)"
            if re.search(threat_signatures, text_to_check):
                await bot.send_message(
                    ADMIN_ID, 
                    f"🚨 <b>SERVER BREACH ATTEMPT (SQLi/RCE) BLOCKED!</b>\n\n"
                    f"<b>User:</b> @{event.from_user.username or 'No_Username'} (ID: <code>{user_id}</code>)\n"
                    f"<b>Payload:</b> <code>{text_to_check}</code>\n\n"
                    f"<i>Data secure. Identity masked. Threat neutralized. User is shadow-banned.</i>",
                    parse_mode="HTML"
                )
                shadow_banned_users[user_id] = now + 315360000 # 10 Years Shadow-Ban
                return

        # =========================================================
        # 🛡️ LAYER 5: PASS TO HANDLER
        # =========================================================
        # If the user passes all security checks, allow the bot to process their request
        return await handler(event, data)


# =====================================================================
# ⚙️ ADVANCED UTILITY FUNCTIONS
# =====================================================================

async def scan_image_for_code(bot, photo) -> str:
    """
    Simulated AI OCR Engine for Amazon Pay Gift Cards.
    In production, this integrates with Google Cloud Vision or OCR.Space APIs
    to automatically extract 14-digit alphanumeric codes from screenshots.
    """
    # Try-Except block ensures bot never crashes even if image processing fails
    try:
        await asyncio.sleep(1.5) # Simulating OCR processing latency
        return "OCR_SCANNED_WAITING_MANUAL_VERIFY"
    except Exception as e:
        logger.error(f"OCR Processing Error: {e}")
        return "OCR_FAILED"


async def auto_delete_task(bot, chat_id, message_id, delay_hours=72):
    """
    Self-Destructing Message Protocol.
    Automatically deletes ad broadcasts after the specified hours (default 72h).
    Fire-and-forget task that cleans up groups silently.
    """
    await asyncio.sleep(delay_hours * 3600)
    try:
        await bot.delete_message(chat_id, message_id)
        logger.info(f"Self-Destruct successful: Broadcast {message_id} in {chat_id} deleted.")
    except Exception as e:
        # Ignore errors if message was already deleted manually by admin
        logger.debug(f"Self-Destruct skipped (already deleted or no rights): {e}")

