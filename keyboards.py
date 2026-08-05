import random

from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

from config import WEBAPP_BASE_URL, PAYMENT_HELP_LINK, HELP_BOT_USERNAME

# ---------------- header tagline ----------------
TAGLINE = "Verified courses. Trusted faculty. Lifetime access."


def get_line() -> str:
    return TAGLINE


# ---------------- welcome messages ----------------
# A different short welcome message for (almost) every user — picked
# randomly per /start so the bot doesn't feel copy-pasted. Kept short &
# Hinglish-friendly to match Professor's own tone.
WELCOME_MESSAGES = [
    "Swagat hai, {name}! Aapki UPSC/State PSC journey ke liye sahi jagah pe aa gaye ho.",
    "Namaste {name} 🙏 — Professor ke curated courses ab ek click door hain.",
    "Hello {name}! Tayyari ko next level pe le jaane ka time aa gaya hai.",
    "Welcome {name} — verified faculty, sahi price, lifetime access. Let's begin.",
    "{name}, aapka istaqbaal hai! Neeche se apna section choose karo.",
    "Good to see you, {name}! Course dhoondhna ab bohot easy ho gaya hai.",
    "Namaskar {name} — Professor ki taraf se best courses ka collection yahin hai.",
    "Hey {name}! Ek qadam aur apni manzil ke kareeb — chuno apna course.",
    "{name}, tayyari shuru karte hain — sahi resource, sahi guidance.",
    "Welcome aboard, {name}! Foundation se Test Series tak, sab kuch yahin milega.",
]


def get_welcome_message(name: str) -> str:
    safe_name = (name or "Aspirant").strip() or "Aspirant"
    return random.choice(WELCOME_MESSAGES).format(name=safe_name)


# ---------------- section titles (for leaf sections that route to Mini App) ----------------
SECTION_TITLES = {
    "upsc_foundation": "UPSC Foundation",
    "upsc_csat": "CSAT",
    "upsc_pyq": "PYQ / Answer Practice",
    "upsc_crash": "UPSC Crash Course",
    "upsc_ca": "Current Affairs",
    "upsc_prelims": "Prelims Specific",
    "upsc_mains": "Mains Specific",
    "upsc_ts_prelims": "Prelims Test Series",
    "upsc_ts_mains": "Mains Test Series",
    "subj_economy": "Economics (incl. Mrunal)",
    "subj_geography": "Geography (incl. Sudarshan Gujjar)",
    "subj_polity": "Polity & Governance (incl. Jatin Gupta)",
    "subj_environment_scitech": "Environment + Sci-Tech",
    "subj_history": "History",
    "subj_ir": "International Relations",
    "subj_public_admin": "Public Administration",
    "upsc_ethics": "Ethics (GS-4)",
    "upsc_essay": "Essay",
    "upsc_subject_specific": "Other Subject Courses",
    "uppsc": "UPPSC",
    "bpsc": "BPSC",
    "rpsc": "RPSC",
    "jpsc": "JPSC",
    "ukpsc": "UKPSC",
    "net_jrf": "NET / JRF",
    "net_jrf_all": "NET / JRF — All Subjects",
    "combo_deals": "Combo Deals & Bundles",
    "other": "Other Courses",
    "other_misc": "Other Courses",
}


# ---------------- FSM states ----------------
class BuyFlow(StatesGroup):
    waiting_for_gift_card = State()


class AdminAddCourse(StatesGroup):
    name = State()
    faculty = State()
    medium = State()
    notes = State()
    price = State()
    section = State()


class AdminBroadcast(StatesGroup):
    waiting_message = State()


class ContactFlow(StatesGroup):
    waiting_for_message = State()


class AdminReplyFlow(StatesGroup):
    waiting_for_reply = State()


# ---------------- keyboards ----------------
def main_menu_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🏛 UPSC", callback_data="topsec:upsc")],
        [InlineKeyboardButton(text="🏢 All State PSC", callback_data="topsec:state_psc")],
        [InlineKeyboardButton(text="🧑‍🏫 Subject Specific Course", callback_data="topsec:subject_specific")],
        [InlineKeyboardButton(text="♛ Prelims & Mains Course", callback_data="topsec:prelims_mains")],
        [InlineKeyboardButton(text="📝 Test Series", callback_data="topsec:test_series")],
        [InlineKeyboardButton(text="📗 UPSC Optional", callback_data="topsec:upsc_optional")],
        [InlineKeyboardButton(text="🎓 NET / JRF", callback_data="topsec:net_jrf")],
        [InlineKeyboardButton(text="🎁 Combo Deals & Bundles", callback_data="sec:combo_deals")],
        [InlineKeyboardButton(text="📦 Other Courses", callback_data="topsec:other")],
        [InlineKeyboardButton(text="🔍 Search All Courses", callback_data="allcourses:open")],
        [InlineKeyboardButton(text="🔥 Trending Courses", callback_data="trending:open")],
        [InlineKeyboardButton(text="🧾 My Courses", callback_data="mycourses:open")],
        [InlineKeyboardButton(text="🆘 Help", callback_data="help:open")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def state_psc_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="UPPSC", callback_data="sec:uppsc")],
        [InlineKeyboardButton(text="BPSC", callback_data="sec:bpsc")],
        [InlineKeyboardButton(text="RPSC", callback_data="sec:rpsc")],
        [InlineKeyboardButton(text="JPSC", callback_data="sec:jpsc")],
        [InlineKeyboardButton(text="UKPSC", callback_data="sec:ukpsc")],
        [InlineKeyboardButton(text="⬅ Back", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def upsc_subsections_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="⌂ Foundation", callback_data="sec:upsc_foundation")],
        [InlineKeyboardButton(text="🧮 CSAT", callback_data="sec:upsc_csat")],
        [InlineKeyboardButton(text="🗂 PYQ / Answer Practice", callback_data="sec:upsc_pyq")],
        [InlineKeyboardButton(text="⚡ Crash Course", callback_data="sec:upsc_crash")],
        [InlineKeyboardButton(text="📰 Current Affairs", callback_data="sec:upsc_ca")],
        [InlineKeyboardButton(text="⬅ Back", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def prelims_mains_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="◎ Prelims Specific", callback_data="sec:upsc_prelims")],
        [InlineKeyboardButton(text="♛ Mains Specific", callback_data="sec:upsc_mains")],
        [InlineKeyboardButton(text="⬅ Back", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def test_series_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📝 Prelims Test Series", callback_data="sec:upsc_ts_prelims")],
        [InlineKeyboardButton(text="📝 Mains Test Series", callback_data="sec:upsc_ts_mains")],
        [InlineKeyboardButton(text="⬅ Back", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subject_specific_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="💹 Economics (Mrunal & others)", callback_data="sec:subj_economy")],
        [InlineKeyboardButton(text="🗺 Geography (Sudarshan Gujjar & others)", callback_data="sec:subj_geography")],
        [InlineKeyboardButton(text="🏛 Polity & Governance (Jatin Gupta & others)", callback_data="sec:subj_polity")],
        [InlineKeyboardButton(text="🌱 Environment + Sci-Tech", callback_data="sec:subj_environment_scitech")],
        [InlineKeyboardButton(text="📜 History", callback_data="sec:subj_history")],
        [InlineKeyboardButton(text="🌐 International Relations", callback_data="sec:subj_ir")],
        [InlineKeyboardButton(text="🏢 Public Administration", callback_data="sec:subj_public_admin")],
        [InlineKeyboardButton(text="⚖️ Ethics (GS-4)", callback_data="sec:upsc_ethics")],
        [InlineKeyboardButton(text="✍️ Essay", callback_data="sec:upsc_essay")],
        [InlineKeyboardButton(text="📚 Other Subject Courses", callback_data="sec:upsc_subject_specific")],
        [InlineKeyboardButton(text="⬅ Back", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def section_webapp_kb(section_key: str, section_title: str) -> InlineKeyboardMarkup:
    url = f"{WEBAPP_BASE_URL}/webapp/section/{section_key}"
    rows = [
        [InlineKeyboardButton(text=f"📂 Open {section_title} Courses", web_app=WebAppInfo(url=url))],
        [InlineKeyboardButton(text="⬅ Back", callback_data="menu:back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def all_courses_webapp_kb() -> InlineKeyboardMarkup:
    url = f"{WEBAPP_BASE_URL}/webapp/section/all"
    rows = [
        [InlineKeyboardButton(text="🔍 Open Full Course Catalog", web_app=WebAppInfo(url=url))],
        [InlineKeyboardButton(text="⬅ Back", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def empty_section_kb() -> InlineKeyboardMarkup:
    """Shown instead of the Mini-App button when a section currently has
    zero listed courses — routes straight into the in-bot Contact Professor
    flow instead of opening an empty catalog."""
    rows = [
        [InlineKeyboardButton(text="💬 Contact Professor for this", callback_data="contact:open")],
        [InlineKeyboardButton(text="⬅ Back", callback_data="menu:back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_kb(course_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🎁 How to buy an Amazon Gift Card?", url=PAYMENT_HELP_LINK)],
        [InlineKeyboardButton(text="📤 Send Gift Card Here", callback_data=f"sendgc:{course_id}")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_order_decision_kb(order_id: int) -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton(text="✅ Approve", callback_data=f"adm_ok:{order_id}"),
        InlineKeyboardButton(text="❌ Reject", callback_data=f"adm_no:{order_id}"),
    ]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def join_channel_kb(channel_username: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📢 Join Backup Channel", url=f"https://t.me/{channel_username.lstrip('@')}")],
        [InlineKeyboardButton(text="✅ I've Joined — Continue", callback_data="checkjoin")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def help_kb() -> InlineKeyboardMarkup:
    uname = HELP_BOT_USERNAME.lstrip("@")
    rows = [
        [InlineKeyboardButton(text="💬 Contact Professor (in this bot)", callback_data="contact:open")],
        [InlineKeyboardButton(text="🔗 Message Professor directly", url=f"https://t.me/{uname}")],
        [InlineKeyboardButton(text="❓ FAQ", callback_data="faq:open")],
        [InlineKeyboardButton(text="⬅ Back", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def contact_cancel_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="❌ Cancel", callback_data="menu:main")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)
