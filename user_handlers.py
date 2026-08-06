import json
import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import select

from database import (
    async_session, User, Course, Order, UserCourse, Section, ContactMessage, log_step,
)
from config import BACKUP_CHANNEL, BOT_NAME, ADMIN_ID, PROFESSOR_CONTACT_LINK
from keyboards import (
    main_menu_kb, upsc_subsections_kb, state_psc_kb, section_webapp_kb,
    all_courses_webapp_kb, payment_method_kb, amazon_gift_intro_kb, gift_card_collect_kb,
    upi_contact_kb, admin_order_decision_kb, join_channel_kb,
    help_kb, SECTION_TITLES, get_line, get_welcome_message, BuyFlow,
    prelims_mains_kb, subject_specific_kb, empty_section_kb, optional_subjects_kb,
    ContactFlow, contact_cancel_kb,
)

logger = logging.getLogger(__name__)
router = Router()


def uid_tag(user_id: int) -> str:
    """User ID wrapped so a single tap copies it in Telegram."""
    return f"<code>{user_id}</code>"


# ================= START / CHANNEL GATE =================
async def _get_or_create_user(tg_user) -> tuple[User, bool]:
    """Returns (user, is_new)."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == tg_user.id))
        user = result.scalar_one_or_none()
        is_new = user is None
        if user is None:
            user = User(id=tg_user.id, username=tg_user.username, first_name=tg_user.first_name)
            session.add(user)
        else:
            user.username = tg_user.username
            user.first_name = tg_user.first_name
        await session.commit()
        await session.refresh(user)
        return user, is_new


async def _notify_admin_of_start(bot, tg_user, is_new: bool, user: User):
    """Sends the Professor a notification every time someone starts the bot,
    so admin always knows who's using it — including on repeat visits."""
    if tg_user.id == ADMIN_ID:
        return
    status_tag = "🆕 New user" if is_new else "🔁 Returning user"
    text = (
        f"👋 <b>{status_tag} started the bot</b>\n\n"
        f"👤 Name: {tg_user.full_name}\n"
        f"🔗 Username: @{tg_user.username or '—'}\n"
        f"🆔 User ID: {uid_tag(tg_user.id)}\n"
        f"📅 First seen: {user.joined_at.strftime('%d %b %Y, %H:%M UTC') if user.joined_at else '—'}\n"
        f"✅ Backup channel verified: {'Yes' if user.has_joined_backup_channel else 'No'}"
    )
    try:
        await bot.send_message(ADMIN_ID, text)
    except Exception:
        logger.exception("Failed to notify admin of /start")


async def _is_member_of_backup_channel(bot, user_id: int) -> bool:
    """Checks live membership via the Telegram API. Returns False (rather
    than raising) on any error — including the bot not being an admin in the
    channel, which is the most common misconfiguration and is logged loudly
    so it's easy to diagnose from the server logs."""
    try:
        member = await bot.get_chat_member(chat_id=BACKUP_CHANNEL, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except TelegramForbiddenError:
        logger.error(
            f"Backup-channel check failed for user {user_id}: bot is not an "
            f"admin of {BACKUP_CHANNEL}. Add the bot as an admin in that channel."
        )
        return False
    except TelegramBadRequest:
        logger.warning(f"Backup-channel check: user {user_id} not found in {BACKUP_CHANNEL} (likely hasn't joined).")
        return False
    except Exception:
        logger.exception(f"Unexpected error checking backup-channel membership for user {user_id}")
        return False


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext):
    user, is_new = await _get_or_create_user(message.from_user)
    await _notify_admin_of_start(message.bot, message.from_user, is_new, user)
    await log_step(user.id, "Started the bot (/start)")

    if user.is_banned:
        await message.answer("🚫 You don't have access to this bot. Contact Professor if you have a query.")
        return

    # Deep-link payload from the Mini App's "Buy Now" button, e.g. "buy_123"
    # (see webapp_template.py buyCourse()). Stash it — the channel gate below
    # may need to run first, and we resume the buy screen right after that.
    pending_course_id = None
    if command.args and command.args.startswith("buy_"):
        try:
            pending_course_id = int(command.args.split("_", 1)[1])
        except ValueError:
            pending_course_id = None

    # Once verified, the gate never shows again — even on repeat /start.
    if not user.has_joined_backup_channel:
        is_member = await _is_member_of_backup_channel(message.bot, message.from_user.id)
        if not is_member:
            if pending_course_id:
                await state.update_data(pending_course_id=pending_course_id)
            await message.answer(
                f"👋 Welcome to <b>{BOT_NAME}</b>!\n\n"
                "Joining our backup channel is required before you can access the bot — "
                "this is a one-time step.",
                reply_markup=join_channel_kb(BACKUP_CHANNEL),
            )
            return
        async with async_session() as session:
            u = await session.get(User, user.id)
            u.has_joined_backup_channel = True
            await session.commit()

    if pending_course_id:
        await _show_buy_screen(message, pending_course_id, tg_user=message.from_user)
        return

    welcome = get_welcome_message(message.from_user.first_name)
    await message.answer(
        f"👋 {welcome}\n\n{get_line()}\n\n"
        "Choose a section below — each one opens the full catalog with faculty, notes and pricing.",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data == "checkjoin")
async def cb_check_join(call: CallbackQuery, state: FSMContext):
    is_member = await _is_member_of_backup_channel(call.bot, call.from_user.id)
    if not is_member:
        await call.answer(
            "We still can't see you in the channel — join, then try again 🙏",
            show_alert=True,
        )
        return
    async with async_session() as session:
        u = await session.get(User, call.from_user.id)
        if u:
            u.has_joined_backup_channel = True
            await session.commit()

    data = await state.get_data()
    pending_course_id = data.get("pending_course_id")
    if pending_course_id:
        await state.update_data(pending_course_id=None)
        await _show_buy_screen(call.message, pending_course_id, tg_user=call.from_user, edit=True)
        await call.answer()
        return

    welcome = get_welcome_message(call.from_user.first_name)
    await call.message.edit_text(
        f"✅ Verified! {welcome}\n\n{get_line()}\n\nChoose a section below:",
        reply_markup=main_menu_kb(),
    )
    await call.answer()


@router.callback_query(F.data.in_(["menu:main", "menu:back"]))
async def cb_back_main(call: CallbackQuery):
    await call.message.edit_text(
        f"📚 <b>{BOT_NAME}</b>\n\n{get_line()}\n\nChoose a section:",
        reply_markup=main_menu_kb(),
    )
    await call.answer()


# ================= SECTIONS =================
@router.callback_query(F.data == "topsec:upsc")
async def cb_upsc(call: CallbackQuery):
    await log_step(call.from_user.id, "Opened UPSC menu")
    await call.message.edit_text(f"🏛 <b>UPSC</b>\n\n{get_line()}\n\nWhich stage do you need?", reply_markup=upsc_subsections_kb())
    await call.answer()


@router.callback_query(F.data == "topsec:state_psc")
async def cb_state_psc(call: CallbackQuery):
    await log_step(call.from_user.id, "Opened All State PSC menu")
    await call.message.edit_text(f"🏢 <b>All State PSC</b>\n\n{get_line()}\n\nChoose your state:", reply_markup=state_psc_kb())
    await call.answer()


@router.callback_query(F.data == "topsec:prelims_mains")
async def cb_prelims_mains(call: CallbackQuery):
    await log_step(call.from_user.id, "Opened Prelims & Mains Specific Batch menu")
    await call.message.edit_text(
        f"♛ <b>Prelims & Mains Specific Batch</b>\n\n{get_line()}\n\nWhich stage do you need?",
        reply_markup=prelims_mains_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "topsec:subject_specific")
async def cb_subject_specific(call: CallbackQuery):
    await log_step(call.from_user.id, "Opened Subject Specific Batch menu")
    await call.message.edit_text(
        f"🧑‍🏫 <b>Subject Specific Batch</b>\n\n{get_line()}\n\nChoose a subject:",
        reply_markup=subject_specific_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "upscopt:open")
async def cb_upsc_optional_picker(call: CallbackQuery):
    await log_step(call.from_user.id, "Opened UPSC Optional picker")
    await call.message.edit_text(
        f"📗 <b>UPSC Optional Subjects</b>\n\n{get_line()}\n\nChoose your optional:",
        reply_markup=optional_subjects_kb(),
    )
    await call.answer()


async def _section_course_count(key: str) -> int:
    async with async_session() as session:
        result = await session.execute(select(Section).where(Section.key == key))
        section = result.scalar_one_or_none()
        if not section:
            return 0
        return len([c for c in section.courses if c.is_active])


@router.callback_query(F.data.startswith("sec:"))
async def cb_leaf_section(call: CallbackQuery):
    key = call.data.split(":", 1)[1]
    title = SECTION_TITLES.get(key, key.title())
    await log_step(call.from_user.id, f"Opened section: {title}")

    count = await _section_course_count(key)
    if count == 0:
        await call.message.edit_text(
            f"📂 <b>{title}</b>\n\n"
            "Abhi is category me koi course listed nahi hai. Aapki specific demand ke liye "
            "Professor ko seedha message kar sakte ho 👇",
            reply_markup=empty_section_kb(),
        )
        await call.answer()
        return

    await call.message.edit_text(
        f"📂 <b>{title}</b>\n\n{get_line()}\n\nFull course catalog is in the Mini App 👇",
        reply_markup=section_webapp_kb(key, title),
    )
    await call.answer()


# ================= SEARCH ALL COURSES =================
@router.callback_query(F.data == "allcourses:open")
async def cb_all_courses(call: CallbackQuery):
    await log_step(call.from_user.id, "Opened Search All Courses")
    await call.message.edit_text(
        f"🔍 <b>Search All Courses</b>\n\n{get_line()}\n\n"
        "Browse and search across every section — foundation, mains, optionals, "
        "state PSCs, NET/JRF, and combo deals — in one place 👇",
        reply_markup=all_courses_webapp_kb(),
    )
    await call.answer()


# ================= TRENDING =================
async def _trending_kb() -> InlineKeyboardMarkup:
    async with async_session() as session:
        result = await session.execute(select(Course).where(Course.is_trending == True, Course.is_active == True))  # noqa: E712
        courses = result.scalars().all()
    rows = []
    for c in courses:
        price_tag = f"₹{int(c.price)}" if c.price is not None else "Price TBD"
        rows.append([InlineKeyboardButton(text=f"🔥 {c.name} — {price_tag}", callback_data=f"buy:{c.id}")])
    rows.append([InlineKeyboardButton(text="⬅ Back", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


TRENDING_TEXT = "🔥 <b>Trending Courses</b>\n\n{line}\n\nThe courses in highest demand right now — buy directly from here."


@router.message(Command("trending"))
async def cmd_trending(message: Message):
    await message.answer(TRENDING_TEXT.format(line=get_line()), reply_markup=await _trending_kb())


@router.callback_query(F.data == "trending:open")
async def cb_trending(call: CallbackQuery):
    await log_step(call.from_user.id, "Opened Trending Courses")
    await call.message.edit_text(TRENDING_TEXT.format(line=get_line()), reply_markup=await _trending_kb())
    await call.answer()


# ================= BUY FLOW =================
def _course_detail_text(course: Course) -> str:
    price_tag = f"₹{int(course.price)}" if course.price is not None else "Price on request — Professor will confirm with you"
    return (
        f"📘 <b>{course.name}</b>\n"
        f"🆔 Course ID: {course.id}\n"
        f"👨‍🏫 Faculty: {course.faculty or '—'}\n"
        f"🌐 Medium: {course.medium or '—'}\n"
        f"📝 Notes: {course.notes or '—'}\n"
        f"💰 {price_tag}\n♾️ Validity: Lifetime\n\n"
        "Choose a payment method below 👇"
    )


async def _notify_admin_buy_intent(bot, tg_user, course: Course):
    """Fires the moment a user taps Buy — Professor sees interest immediately,
    even before any payment proof is sent."""
    if tg_user.id == ADMIN_ID:
        return
    price_tag = f"₹{int(course.price)}" if course.price is not None else "TBD"
    text = (
        "👀 <b>Buy intent</b> — user opened the payment screen\n\n"
        f"👤 Name: {tg_user.full_name}\n"
        f"🔗 Username: @{tg_user.username or '—'}\n"
        f"🆔 User ID: {uid_tag(tg_user.id)}\n"
        f"📘 Course: {course.name}\n"
        f"🆔 Course ID: {course.id}\n"
        f"💰 Price: {price_tag}"
    )
    try:
        await bot.send_message(ADMIN_ID, text)
    except Exception:
        logger.exception("Failed to notify admin of buy intent")


async def _show_buy_screen(message: Message, course_id: int, tg_user=None, edit: bool = False):
    tg_user = tg_user or message.from_user
    async with async_session() as session:
        course = await session.get(Course, course_id)
    if not course or not course.is_active:
        target = message.edit_text if edit else message.answer
        await target("This course isn't available right now — please pick another from the menu.", reply_markup=main_menu_kb())
        return
    await log_step(tg_user.id, f"Viewed buy screen: {course.name}")
    await _notify_admin_buy_intent(message.bot, tg_user, course)
    text, kb = _course_detail_text(course), payment_method_kb(course.id)
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(call: CallbackQuery):
    course_id = int(call.data.split(":", 1)[1])
    await _show_buy_screen(call.message, course_id, tg_user=call.from_user, edit=True)
    await call.answer()


@router.callback_query(F.data.startswith("paym:upi:"))
async def cb_pay_upi(call: CallbackQuery):
    course_id = int(call.data.split(":", 2)[2])
    await log_step(call.from_user.id, f"Chose UPI payment for course_id={course_id}")
    await call.message.edit_text(
        "💳 <b>UPI Payment</b>\n\n"
        "UPI payments are handled directly by Professor (₹10 extra charge applies).\n"
        f"Tap below to message Professor and share which course (ID {course_id}) you want — "
        "they'll share UPI details and confirm the amount.",
        reply_markup=upi_contact_kb(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("paym:amazon:"))
async def cb_pay_amazon(call: CallbackQuery):
    course_id = int(call.data.split(":", 2)[2])
    async with async_session() as session:
        course = await session.get(Course, course_id)
    if not course:
        await call.answer("This course isn't available right now.", show_alert=True)
        return
    await log_step(call.from_user.id, f"Chose Amazon Pay Gift Card for course_id={course_id}")
    price_tag = f"₹{int(course.price)}" if course.price is not None else "to be confirmed by Professor"
    await call.message.edit_text(
        f"🎁 <b>Amazon Pay Gift Card</b>\n\n{course.name} (ID {course.id}) — {price_tag}\n\n"
        "Buy an Amazon Pay Gift Card of this amount from any UPI app (tap 'How to buy' below for step-by-step help), "
        "then send it here.",
        reply_markup=amazon_gift_intro_kb(course_id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("sendgc:"))
async def cb_send_gift_card(call: CallbackQuery, state: FSMContext):
    course_id = int(call.data.split(":", 1)[1])
    async with async_session() as session:
        course = await session.get(Course, course_id)
    if not course:
        await call.answer("This course isn't available right now.", show_alert=True)
        return
    await state.set_state(BuyFlow.waiting_for_gift_card)
    await state.update_data(course_id=course_id, order_id=None, msg_count=0)
    await log_step(call.from_user.id, f"Started gift card submission for course_id={course_id}")
    price_tag = f"₹{int(course.price)}" if course.price is not None else "to be confirmed by Professor"
    await call.message.edit_text(
        f"🎁 <b>Sending payment for:</b> {course.name} (ID {course.id}) — {price_tag}\n\n"
        "Send the Amazon Gift Card <b>photo</b>, the <b>14-digit alphanumeric code</b>, or any proof — "
        "text, photo or document. You can send up to <b>3 messages</b> here (e.g. screenshot + code + anything else).\n\n"
        "Everything goes straight to Professor for verification — the course unlocks in 'My Courses' the moment it's approved ✅",
        reply_markup=gift_card_collect_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "gcdone")
async def cb_gift_card_done(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("order_id"):
        await call.answer("Send at least one message (photo/code) first.", show_alert=True)
        return
    await state.clear()
    await call.message.edit_text(
        "✅ Got it — everything's been sent to Professor for verification.\n"
        "You'll get a notification once it's approved, and the course will appear under 'My Courses' 🎉",
        reply_markup=main_menu_kb(),
    )
    await call.answer()


MAX_GIFT_CARD_MESSAGES = 3


@router.message(BuyFlow.waiting_for_gift_card, F.photo | F.text | F.document)
async def receive_gift_card_proof(message: Message, state: FSMContext):
    data = await state.get_data()
    course_id = data["course_id"]
    order_id = data.get("order_id")
    msg_count = data.get("msg_count", 0)

    if message.photo:
        kind, content = "photo", message.photo[-1].file_id
    elif message.document:
        kind, content = "document", message.document.file_id
    else:
        kind, content = "text", message.text

    async with async_session() as session:
        course = await session.get(Course, course_id)
        if order_id is None:
            order = Order(user_id=message.from_user.id, course_id=course_id, submission_type=kind,
                           submission_content=str(content), status="pending")
            session.add(order)
            await session.commit()
            await session.refresh(order)
            order_id = order.id

    msg_count += 1
    await state.update_data(order_id=order_id, msg_count=msg_count)
    await log_step(message.from_user.id, f"Sent gift-card proof #{msg_count} for order #{order_id} ({course.name})")

    price_tag = f"₹{int(course.price)}" if course.price is not None else "TBD — confirm with buyer before approving"
    if msg_count == 1:
        admin_caption = (
            "🔔 <b>New Order — Verification Needed</b>\n\n"
            f"🧾 Order ID: #{order_id}\n"
            f"👤 Name: {message.from_user.full_name}\n"
            f"🔗 Username: @{message.from_user.username or '—'}\n"
            f"🆔 User ID: {uid_tag(message.from_user.id)}\n"
            f"📘 Course: {course.name}\n"
            f"🆔 Course ID: {course.id}\n"
            f"💰 Price: {price_tag}\n"
            f"📎 Message 1/{MAX_GIFT_CARD_MESSAGES}"
        )
        kb = admin_order_decision_kb(order_id)
    else:
        admin_caption = (
            f"📎 <b>Additional proof for Order #{order_id}</b> "
            f"(message {msg_count}/{MAX_GIFT_CARD_MESSAGES}) — {course.name} — {uid_tag(message.from_user.id)}"
        )
        kb = None

    try:
        if kind == "text":
            admin_caption += f"\n🎁 Content:\n<code>{content}</code>"
            await message.bot.send_message(ADMIN_ID, admin_caption, reply_markup=kb)
        elif kind == "photo":
            await message.bot.send_photo(ADMIN_ID, photo=content, caption=admin_caption, reply_markup=kb)
        else:
            await message.bot.send_document(ADMIN_ID, document=content, caption=admin_caption, reply_markup=kb)
    except Exception:
        logger.exception("Failed to forward gift card proof to admin")

    if msg_count >= MAX_GIFT_CARD_MESSAGES:
        await state.clear()
        await message.answer(
            "✅ Got all your messages — sent to Professor for verification.\n"
            "You'll get a notification once it's approved, and the course will appear under 'My Courses' 🎉",
            reply_markup=main_menu_kb(),
        )
    else:
        remaining = MAX_GIFT_CARD_MESSAGES - msg_count
        await message.answer(
            f"✅ Received (message {msg_count}/{MAX_GIFT_CARD_MESSAGES}). "
            f"You can send up to {remaining} more, or tap 'Done' below when finished.",
            reply_markup=gift_card_collect_kb(),
        )


# ================= MINI APP -> BUY BRIDGE (fallback if sendData ever fires) =================
@router.message(F.web_app_data)
async def handle_webapp_data(message: Message):
    try:
        data = json.loads(message.web_app_data.data)
    except (json.JSONDecodeError, AttributeError):
        return
    if data.get("action") != "buy":
        return
    await _show_buy_screen(message, data.get("course_id"))


# ================= MY COURSES =================
@router.callback_query(F.data == "mycourses:open")
async def cb_my_courses(call: CallbackQuery):
    await log_step(call.from_user.id, "Opened My Courses")
    async with async_session() as session:
        result = await session.execute(
            select(UserCourse, Course).join(Course, UserCourse.course_id == Course.id)
            .where(UserCourse.user_id == call.from_user.id)
        )
        rows = result.all()

    if not rows:
        await call.message.edit_text(
            "🧾 <b>My Courses</b>\n\nNo course has been assigned yet. Buy a course — it'll show here once approved!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅ Back", callback_data="menu:main")]]),
        )
        await call.answer()
        return

    kb_rows = []
    for _uc, course in rows:
        if course.group_link:
            kb_rows.append([InlineKeyboardButton(text=f"📂 {course.name}", url=course.group_link)])
        else:
            kb_rows.append([InlineKeyboardButton(text=f"⏳ {course.name} (link pending)", callback_data="noop")])
    kb_rows.append([InlineKeyboardButton(text="⬅ Back", callback_data="menu:main")])

    await call.message.edit_text("🧾 <b>My Courses</b>\n\nTap a course to join its group:",
                                  reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await call.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer("Professor will add the group link shortly.", show_alert=True)


# ================= HELP / FAQ =================
HELP_TEXT = (
    "🆘 <b>Help</b>\n\nFor any course, payment, or access issue, message Professor directly — "
    "tap the button below 👇"
)

FAQ_TEXT = (
    "❓ <b>Frequently Asked Questions</b>\n\n"
    "<b>How do I pay?</b>\nOnly Amazon Pay Gift Cards are accepted. Tap 'How to buy an Amazon Gift Card?' "
    "on any course's payment screen for instructions.\n\n"
    "<b>How long until my course is approved?</b>\nOrders are reviewed by Professor personally — "
    "you'll get a notification the moment it's approved or if something needs to be resent.\n\n"
    "<b>Is access lifetime?</b>\nYes — every course listed has lifetime validity and free updates when the source material updates.\n\n"
    "<b>A course shows 'Coming Soon' / no price — can I still get it?</b>\nMessage Professor via Help; "
    "pricing for that course hasn't been finalized yet.\n\n"
    "<b>I joined the backup channel but the bot still asks me to join.</b>\nTap 'I've Joined — Continue' again. "
    "If it persists, message Professor — occasionally Telegram takes a minute to reflect a new channel join."
)


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, reply_markup=help_kb())


@router.callback_query(F.data == "help:open")
async def cb_help(call: CallbackQuery):
    await log_step(call.from_user.id, "Opened Help")
    await call.message.edit_text(HELP_TEXT, reply_markup=help_kb())
    await call.answer()


@router.message(Command("faq"))
async def cmd_faq(message: Message):
    await message.answer(FAQ_TEXT, reply_markup=help_kb())


@router.callback_query(F.data == "faq:open")
async def cb_faq(call: CallbackQuery):
    await call.message.edit_text(FAQ_TEXT, reply_markup=help_kb())
    await call.answer()


# ================= CONTACT PROFESSOR (in-bot, with reply routing) =================
@router.callback_query(F.data == "contact:open")
async def cb_contact_open(call: CallbackQuery, state: FSMContext):
    if call.from_user.id == ADMIN_ID:
        await call.answer("Professor can't message themselves here 🙂", show_alert=True)
        return
    await state.set_state(ContactFlow.waiting_for_message)
    await log_step(call.from_user.id, "Started Contact Professor flow")
    await call.message.edit_text(
        "💬 <b>Contact Professor</b>\n\n"
        "Apna sawaal ya demand yahin type karke bhejo (text/photo/document) — "
        "seedha Professor ko pahunchega aur wahi is chat me reply karenge.\n\n"
        f"Ya seedha yahan message karo: {PROFESSOR_CONTACT_LINK}",
        reply_markup=contact_cancel_kb(),
    )
    await call.answer()


@router.message(Command("contact"))
async def cmd_contact(message: Message, state: FSMContext):
    if message.from_user.id == ADMIN_ID:
        return
    await state.set_state(ContactFlow.waiting_for_message)
    await message.answer(
        "💬 <b>Contact Professor</b>\n\nApna sawaal yahin likho — seedha Professor tak pahunchega.",
        reply_markup=contact_cancel_kb(),
    )


@router.message(ContactFlow.waiting_for_message)
async def receive_contact_message(message: Message, state: FSMContext):
    await state.clear()
    tg_user = message.from_user

    async with async_session() as session:
        session.add(ContactMessage(user_id=tg_user.id, direction="in", content=message.text or message.caption or "[media]"))
        await session.commit()
    await log_step(tg_user.id, "Sent a Contact Professor message")

    header = (
        "📩 <b>New message via Contact Professor</b>\n\n"
        f"👤 Name: {tg_user.full_name}\n"
        f"🔗 Username: @{tg_user.username or '—'}\n"
        f"🆔 User ID: {uid_tag(tg_user.id)}\n\n"
        "↩️ <i>Reply directly to this message in Telegram to answer — it'll be delivered to the user automatically.</i>"
    )
    try:
        if message.text:
            await message.bot.send_message(ADMIN_ID, header + f"\n\n💬 {message.text}")
        else:
            await message.copy_to(chat_id=ADMIN_ID, caption=header + (f"\n\n💬 {message.caption}" if message.caption else ""))
    except Exception:
        logger.exception("Failed to forward contact message to admin")

    await message.answer("✅ Aapka message Professor ko bhej diya gaya hai. Jaldi hi reply milega.")


# ================= ADMIN REPLY ROUTING (admin replies to a forwarded contact/order message) =================
@router.message(F.reply_to_message, F.from_user.id == ADMIN_ID)
async def admin_reply_to_user(message: Message):
    """When Professor replies (Telegram 'Reply') to any forwarded user
    message that contains a User ID, this routes the reply straight back to
    that user — no extra commands needed."""
    import re
    source_text = message.reply_to_message.text or message.reply_to_message.caption or ""
    match = re.search(r"User ID:\s*(?:<code>)?(\d+)", source_text)
    if not match:
        return  # not a message we tagged with a user id — let other handlers ignore it
    target_user_id = int(match.group(1))

    async with async_session() as session:
        session.add(ContactMessage(user_id=target_user_id, direction="out", content=message.text or message.caption or "[media]"))
        await session.commit()

    try:
        if message.text:
            await message.bot.send_message(target_user_id, f"💬 <b>Message from Professor:</b>\n\n{message.text}")
        else:
            await message.copy_to(chat_id=target_user_id)
        await message.reply("✅ Reply sent to user.")
    except TelegramForbiddenError:
        await message.reply("⚠️ Couldn't deliver — user has blocked the bot.")
    except Exception:
        logger.exception("Failed to deliver admin reply to user")
        await message.reply("⚠️ Couldn't deliver the reply — something went wrong.")


@router.message(Command("myid"))
async def cmd_my_id(message: Message):
    is_admin = message.from_user.id == ADMIN_ID
    await message.answer(
        f"🆔 Your Telegram ID: {uid_tag(message.from_user.id)}\n"
        f"{'✅ You are recognized as Professor (admin).' if is_admin else 'You are a regular user.'}"
    )


# ================= FALLBACK (must be registered last in main.py) =================
@router.message()
async def fallback(message: Message):
    await message.answer(f"{get_line()}\n\nUse the menu below to choose a section 👇", reply_markup=main_menu_kb())
