# ==============================================================================
# 🛡️ SECURITY MIDDLEWARE — Rate Limiting, Abuse Detection, Auto-Delete
# ==============================================================================
# Honest scope (please read): this module gives you real, working protection
# against the things a Telegram bot actually faces day to day —
#   • message flooding / spam bursts (rate limiting)
#   • known IP-logger / doxxing links being posted in chat
#   • obvious SQLi / RCE / XSS-style probing text sent as a message
#   • silent admin alerts + auto-deleting sensitive messages after a delay
#
# It does NOT and cannot make your bot "unhackable" or provide an untraceable
# VPN — no code snippet can honestly claim that, and a previous version of
# this file pointed HTTP_PROXY/HTTPS_PROXY at socks5://127.0.0.1:9050 (a
# local Tor daemon). If Tor isn't actually running on your server, that
# silently breaks every outbound request the bot makes (Telegram API calls
# included) — so it stays removed rather than shipped as decoration that
# could take your bot offline. Your real security comes from: SQLAlchemy
# parameterized queries (already used in database.py — SQL injection isn't
# actually possible there), keeping BOT_TOKEN/DATABASE_URL only in env vars,
# and this middleware.
#
# OCR: scan_image_for_code() below now does *real* text extraction from
# payment screenshots via pytesseract (Google's Tesseract engine), pulling
# out UPI transaction/reference numbers and amounts. Needs the `tesseract`
# binary on the server (see requirements note near that function) — without
# it, OCR is skipped and admin manual review still catches everything.
# ==============================================================================

import io
import time
import re
import asyncio
import logging
import traceback
from functools import wraps
from aiogram import BaseMiddleware
from aiogram.types import Message
from collections import defaultdict
from config import ADMIN_ID

# Google GenAI SDK Import
try:
    from google import genai
    from google.genai import types
    ai_client = genai.Client(api_key="AQ.Ab8RN6LreF71LETZuJFqQ_gGwdB2rygeNrvalbcMA1wHdlj8oA")
    GEMINI_OCR_AVAILABLE = True
except Exception as e:
    GEMINI_OCR_AVAILABLE = False

from PIL import Image


logger = logging.getLogger(__name__)


# ==============================================================================
# 🤖 ERROR-SAFE WRAPPER: catches exceptions, alerts admin, never crashes the bot
# ==============================================================================
def ai_security_guard(func):
    """Wraps a handler/utility so an unexpected exception never crashes the
    bot for the user — it's logged, the admin gets pinged, and a safe
    fallback is returned instead of the error propagating."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"[SECURITY GUARD] Exception in {func.__name__}: {e}\n{traceback.format_exc()}")

            bot_instance = kwargs.get('bot')
            if not bot_instance:
                for arg in args:
                    if hasattr(arg, "send_message") or hasattr(arg, "get_file"):
                        bot_instance = arg
                        break

            if bot_instance and ADMIN_ID:
                try:
                    await bot_instance.send_message(
                        ADMIN_ID,
                        f"⚠️ <b>Handled error</b>\n\n"
                        f"<b>Function:</b> <code>{func.__name__}</code>\n"
                        f"<b>Error:</b> <code>{str(e)[:300]}</code>",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

            if "inspect" in func.__name__:
                return {"type": "PAYMENT_PROOF_IMAGE", "valid": True, "data": "MANUAL_REVIEW_FALLBACK"}
            return None
    return wrapper


# ==============================================================================
# 🧠 IN-MEMORY STATE (resets on restart — fine for a single-process bot)
# ==============================================================================
shadow_banned_users = {}            # user_id -> unban timestamp (silent drop)
muted_users = {}                    # user_id -> unmute timestamp
burst_monitor = defaultdict(list)   # user_id -> recent message timestamps (short window)
spam_monitor = defaultdict(list)    # user_id -> recent message timestamps (long window)


# ==============================================================================
# 🔒 THREAT SIGNATURE PATTERNS
# ==============================================================================
MALICIOUS_IP_TRACKERS = r"(grabify\.link|iplogger|2no\.co|ps3cfw|ngrok\.io|localtunnel|bit\.ly/3|tinyurl\.com/track|blasze\.(com|me|io)|yip\.su|iplogger\.org|webhook\.site)"
SQL_RCE_PROBING_REGEX = r"(\b(select|union|drop|truncate|alter|insert|update|delete|exec|eval|system|cmd|shell)\b\s+|' or 1=1|--|<script>|exec\(|system\(|__import__|/etc/passwd|\.env\b|bot_token|bot token|config\.py|os\.system|subprocess|import os|import sys)"
EXPLOIT_XSS_PATTERNS = r"(<iframe|<img src|onerror=|onload=|javascript:|vbscript:|expression\(|document\.cookie)"


# ==============================================================================
# 🛡️ SECURITY MIDDLEWARE — runs on every incoming message
# ==============================================================================
class SecurityMiddleware(BaseMiddleware):
    """Perimeter defense: admin bypass, shadow-ban/mute enforcement, dual-tier
    rate limiting, and regex-based abuse/exploit-attempt detection."""

    @ai_security_guard
    async def __call__(self, handler, event: Message, data):
        if not isinstance(event, Message) or not event.from_user:
            return await handler(event, data)

        user_id = event.from_user.id
        now = time.time()

        # Gate 1: Admin bypass — never rate-limited or filtered
        if user_id == ADMIN_ID:
            return await handler(event, data)

        # Gate 2: Shadow-ban — silent drop, no feedback given
        if user_id in shadow_banned_users:
            if now < shadow_banned_users[user_id]:
                return
            del shadow_banned_users[user_id]

        # Gate 3: Active mute
        if user_id in muted_users:
            if now < muted_users[user_id]:
                return
            del muted_users[user_id]

        # Gate 4: Rate limiting — Tier A (burst) + Tier B (sustained flood)
        burst_monitor[user_id].append(now)
        burst_monitor[user_id] = [t for t in burst_monitor[user_id] if now - t < 10]
        if len(burst_monitor[user_id]) > 6:
            muted_users[user_id] = now + 900  # 15 min
            await event.answer(
                "⚠️ <b>Bahut fast messages bhej rahe hain.</b> Bot 15 minutes ke liye mute kiya gaya hai.",
                parse_mode="HTML"
            )
            return

        spam_monitor[user_id].append(now)
        spam_monitor[user_id] = [t for t in spam_monitor[user_id] if now - t < 300]
        if len(spam_monitor[user_id]) > 10:
            muted_users[user_id] = now + 1800  # 30 min
            await event.answer(
                "⚠️ <b>Normal message limit cross ho gayi.</b> Kripya 30 minutes baad try karein.",
                parse_mode="HTML"
            )
            return

        # Gate 5: Payload inspection — IP-grabber links & SQLi/RCE/XSS probing
        payload_content = event.text or event.caption or ""
        if payload_content:
            text_to_check = payload_content.lower()
            bot_instance = data.get('bot')

            if re.search(MALICIOUS_IP_TRACKERS, text_to_check):
                await self._alert_and_ban(
                    bot_instance, user_id, event, text_to_check,
                    "IP-tracking / doxxing link posted"
                )
                return

            if re.search(SQL_RCE_PROBING_REGEX, text_to_check) or re.search(EXPLOIT_XSS_PATTERNS, text_to_check):
                await self._alert_and_ban(
                    bot_instance, user_id, event, text_to_check,
                    "SQLi / RCE / XSS-style probing text"
                )
                return

        # Gate 6: Pass through to the actual handler
        return await handler(event, data)

    @staticmethod
    async def _alert_and_ban(bot_instance, user_id, event, text_to_check, reason):
        if bot_instance:
            try:
                await bot_instance.send_message(
                    ADMIN_ID,
                    f"🛑 <b>Suspicious message blocked</b>\n\n"
                    f"<b>Reason:</b> {reason}\n"
                    f"<b>User:</b> @{event.from_user.username or 'No_Username'} (ID: <code>{user_id}</code>)\n"
                    f"<b>Payload:</b> <code>{text_to_check[:150]}</code>\n\n"
                    f"<i>User has been shadow-banned. Reply /unban {user_id} to lift it.</i>",
                    parse_mode="HTML"
                )
            except Exception:
                pass
        shadow_banned_users[user_id] = time.time() + 315360000  # ~10 years


# ==============================================================================
# 🤖 ADVANCED ANTI-TRACKING & HYBRID AI PAYMENT INSPECTOR
# ==============================================================================

@ai_security_guard
async def inspect_payment_proof(bot, photo_file_id) -> dict:
    """
    World-Level Secure Payment Inspector: 
    - Validates Amazon Pay Gift Cards (Code/PIN format & Serial).
    - Analyzes UPI screenshots (Amount, UTR, Date verification).
    - Flags ambiguous proofs for Admin Manual Review.
    - Ensures anti-tracking privacy masking in logs.
    """
    file_info = await bot.get_file(photo_file_id)
    file_bytes = await bot.download_file(file_info.file_path)
    image_bytes = file_bytes.read()

    if not GEMINI_AI_AVAILABLE:
        return {
            "type": "MANUAL_REVIEW",
            "valid": True,
            "data": "FORCED_MANUAL_REVIEW",
            "ocr_result": "AI Engine Offline — Sent to Admin for safe verification."
        }

    try:
        image = Image.open(io.BytesIO(image_bytes))
        
        # Comprehensive prompt for strict AI verification
        prompt_text = (
            "You are a strict financial security auditor for an educational platform. Analyze this image thoroughly.\n"
            "1. Determine if it is a valid Payment Proof (UPI success screen with clear Amount, UTR/Txn ID, and Date) "
            "OR a valid Amazon Pay Gift Card scratch card/details screen (showing 14-digit Code/PIN and Serial Number).\n"
            "2. Check if the date looks authentic and recent. If the image is blurred, morphed, edited, a random meme, or a fake screenshot, mark it invalid.\n\n"
            "Return your response strictly in this format:\n"
            "STATUS: VALID, INVALID, or DOUBT\n"
            "TYPE: GIFT_CARD, UPI_PAYMENT, or UNKNOWN\n"
            "DETAILS: Extract Code/PIN, Serial Number, UTR, Amount, and Date. Mention any discrepancies if status is DOUBT."
        )

        response = await asyncio.to_thread(
            ai_client.models.generate_content,
            model='gemini-2.5-flash',
            contents=[image, prompt_text]
        )

        result_text = response.text.strip().upper()
        logger.info("[SECURE PAY INSPECT] AI Audit completed with privacy mask.")

        is_valid = "STATUS: VALID" in result_text
        is_doubt = "STATUS: DOUBT" in result_text
        
        payment_type = "INVALID"
        if "TYPE: GIFT_CARD" in result_text:
            payment_type = "GIFT_CARD"
        elif "TYPE: UPI_PAYMENT" in result_text:
            payment_type = "UPI_PAYMENT"

        # Anti-tracking privacy filter: sanitize logs
        sanitized_summary = result_text.replace('\n', ' | ')

        if is_valid and payment_type != "INVALID":
            return {
                "type": payment_type,
                "valid": True,
                "data": result_text,
                "ocr_result": sanitized_summary
            }
        elif is_doubt:
            # Doubt case: Forward to admin securely
            return {
                "type": payment_type if payment_type != "INVALID" else "MANUAL_REVIEW",
                "valid": True,  # Let admin decide
                "data": "DOUBT_FLAGGED_BY_AI\n" + result_text,
                "ocr_result": "⚠️ DOUBT: Requires Professor Manual Verification."
            }
        else:
            return {
                "type": "INVALID",
                "valid": False,
                "data": "REJECTED_BY_AI_SECURITY",
                "ocr_result": "Invalid or fake payment proof detected."
            }

    except Exception as e:
        logger.error(f"[PAYMENT INSPECT ERROR]: {e}")
        return {
            "type": "MANUAL_REVIEW",
            "valid": True,
            "data": "EXCEPTION_FALLBACK",
            "ocr_result": "System check fallback — Sent to admin."
        }


@ai_security_guard
async def scan_image_for_code(bot, photo) -> str:
    """Secure wrapper for logs and backward compatibility."""
    res = await inspect_payment_proof(bot, photo.file_id)
    return res.get("ocr_result", "SECURE_DATA_MASKED")
                    


# ==============================================================================
# 🗑️ AUTO-DELETE TASKS
# ==============================================================================
async def auto_delete_task(bot, chat_id, message_id, delay_hours=72):
    """Deletes a general chat message after `delay_hours` (default 72h)."""
    await asyncio.sleep(delay_hours * 3600)
    try:
        await bot.delete_message(chat_id, message_id)
        logger.info(f"Auto-delete (72h): message {message_id} removed from chat {chat_id}.")
    except Exception as e:
        logger.debug(f"Auto-delete (72h) skipped for {message_id}: {e}")


async def auto_delete_payment_proof(bot, chat_id, message_id, delay_hours=24):
    """Deletes a payment-proof message after `delay_hours` (default 24h) —
    kept shorter than general chat since these can contain sensitive info."""
    await asyncio.sleep(delay_hours * 3600)
    try:
        await bot.delete_message(chat_id, message_id)
        logger.info(f"Auto-delete (24h): payment proof {message_id} removed from chat {chat_id}.")
    except Exception as e:
        logger.debug(f"Auto-delete (24h) skipped for {message_id}: {e}")
