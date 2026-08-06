"""
Database: models + engine/session + initial section-tree seed + full course
catalog seed, all in one file.

Relationships use lazy="selectin" so that accessing course.sections /
section.courses inside an async session actually works. Without this,
SQLAlchemy's default lazy-loading tries to run a *sync* query under the hood,
which crashes with a MissingGreenlet error the moment the Mini App API
endpoint touches section.courses.

v2 NOTE: the home-screen structure was reorganised (UPSC / State PSC /
Subject Specific / Prelims & Mains Course / Test Series / Optional / NET-JRF).
`migrate_v2()` at the bottom performs this restructuring on top of an
*existing* deployed database safely and idempotently — it never deletes a
course or a section, it only creates new sections and re-parents/re-tags
existing ones. Safe to leave in main.py's startup on every deploy.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Boolean, ForeignKey,
    DateTime, Table, Numeric, select
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from config import DATABASE_URL
from course_seed_data import COURSE_SEED

Base = declarative_base()

course_sections = Table(
    "course_sections",
    Base.metadata,
    Column("course_id", Integer, ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True),
    Column("section_id", Integer, ForeignKey("sections.id", ondelete="CASCADE"), primary_key=True),
)


class Section(Base):
    __tablename__ = "sections"

    id = Column(Integer, primary_key=True)
    key = Column(String(80), nullable=False, unique=True)
    name = Column(String(120), nullable=False)
    emoji = Column(String(10), default="📘")
    parent_id = Column(Integer, ForeignKey("sections.id"), nullable=True)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)

    courses = relationship("Course", secondary=course_sections, back_populates="sections", lazy="selectin")


class Course(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    faculty = Column(String(150), default="")
    medium = Column(String(50), default="")
    notes = Column(Text, default="")
    price = Column(Numeric(10, 2), nullable=True)   # NULL = "Coming Soon"
    group_link = Column(String(300), nullable=True)
    is_trending = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    sections = relationship("Section", secondary=course_sections, back_populates="courses", lazy="selectin")


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)
    username = Column(String(100), nullable=True)
    first_name = Column(String(150), nullable=True)
    joined_at = Column(DateTime, default=datetime.utcnow)
    is_banned = Column(Boolean, default=False)
    has_joined_backup_channel = Column(Boolean, default=False)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    status = Column(String(20), default="pending")
    submission_type = Column(String(10), default="text")
    submission_content = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)


class UserCourse(Base):
    __tablename__ = "user_courses"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    granted_at = Column(DateTime, default=datetime.utcnow)


class UserActivity(Base):
    """Lightweight step-tracker so Professor can see what each user has been
    doing inside the bot (menu clicks, buy attempts, etc.) — see /activity."""
    __tablename__ = "user_activity"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    step = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ContactMessage(Base):
    """Every inbound 'Contact Professor' message + the admin's reply (if any),
    so Professor can see the full contact history for a user (see /contacthistory)."""
    __tablename__ = "contact_messages"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    direction = Column(String(10), nullable=False)  # "in" (user->admin) or "out" (admin->user)
    content = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------- engine / session ----------------
engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def log_step(user_id: int, step: str):
    """Fire-and-forget style step logger — call from any handler. Never raises
    (a logging failure should never break a user-facing flow)."""
    try:
        async with async_session() as session:
            session.add(UserActivity(user_id=user_id, step=step))
            await session.commit()
    except Exception:
        pass


# ---------------- initial section tree ----------------
def _slug(s: str) -> str:
    return s.lower().replace(" ", "_").replace("&", "and").replace("/", "_")


OPTIONAL_SUBJECTS = [
    "Anthropology", "PSIR", "Sociology", "History", "Geography", "Philosophy",
    "Public Administration", "Psychology", "Commerce & Accountancy",
    "Hindi Literature", "Mathematics", "Economics", "Law", "Forestry",
    "Geology", "Agriculture",
]

# ---- v2 home-screen structure ----
# Top level (home screen buttons, in this order):
#   UPSC | State PSC | Subject Specific | Prelims & Mains Course |
#   Test Series | UPSC Optional | NET/JRF | Combo Deals | Other Courses
SECTION_TREE = {
    ("upsc", "UPSC", "🏛"): [
        ("upsc_foundation", "Foundation", "⌂"),
        ("upsc_csat", "CSAT", "🧮"),
        ("upsc_pyq", "PYQ / Answer Practice", "🗂"),
        ("upsc_crash", "Crash Course", "⚡"),
        ("upsc_ca", "Current Affairs", "📰"),
    ],
    ("prelims_mains", "Prelims & Mains Course", "♛"): [
        ("upsc_prelims", "Prelims Specific", "◎"),
        ("upsc_mains", "Mains Specific", "♛"),
    ],
    ("test_series", "Test Series", "📝"): [
        ("upsc_ts_prelims", "Prelims Test Series", "📝"),
        ("upsc_ts_mains", "Mains Test Series", "📝"),
    ],
    ("subject_specific", "Subject Specific Course", "🧑‍🏫"): [
        ("subj_economy", "Economics (incl. Mrunal)", "💹"),
        ("subj_geography", "Geography (incl. Sudarshan Gujjar)", "🗺"),
        ("subj_polity", "Polity & Governance (incl. Jatin Gupta)", "🏛"),
        ("subj_environment_scitech", "Environment + Sci-Tech", "🌱"),
        ("subj_history", "History", "📜"),
        ("subj_ir", "International Relations", "🌐"),
        ("subj_public_admin", "Public Administration", "🏢"),
        ("upsc_ethics", "Ethics (GS-4)", "⚖️"),
        ("upsc_essay", "Essay", "✍️"),
        ("upsc_subject_specific", "Other Subject Courses", "📚"),
    ],
    ("upsc_optional", "UPSC Optional", "📗"): [
        (f"optional_{_slug(s)}", s, "📗") for s in OPTIONAL_SUBJECTS
    ],
    ("state_psc", "All State PSC", "🏢"): [
        ("uppsc", "UPPSC", "🏢"),
        ("bpsc", "BPSC", "🏢"),
        ("rpsc", "RPSC", "🏢"),
        ("jpsc", "JPSC", "🏢"),
        ("ukpsc", "UKPSC", "🏢"),
    ],
    ("net_jrf", "NET / JRF", "🎓"): [
        ("net_jrf_all", "All Subjects", "🎓"),
    ],
    ("combo", "Combo Deals & Bundles", "🎁"): [
        ("combo_deals", "Combo Deals", "🎁"),
    ],
    ("other", "Other Courses", "📦"): [
        ("other_misc", "Miscellaneous", "📦"),
    ],
}


async def seed_sections():
    """Creates the whole tree if the sections table is completely empty
    (fresh DB). On an existing DB this is a no-op — migrate_v2() handles
    bringing an older tree up to date instead."""
    async with async_session() as session:
        existing = (await session.execute(select(Section))).scalars().first()
        if existing:
            return
        for (top_key, top_name, top_emoji), children in SECTION_TREE.items():
            top = Section(key=top_key, name=top_name, emoji=top_emoji, parent_id=None)
            session.add(top)
            await session.flush()
            for key, name, emoji in children:
                session.add(Section(key=key, name=name, emoji=emoji, parent_id=top.id))
        await session.commit()


async def seed_courses():
    """One-time seed of the full course catalog (COURSE_SEED, defined in
    course_seed_data.py). Runs only if the courses table is empty, so it is
    safe to leave this call in main.py's startup every deploy."""
    async with async_session() as session:
        existing = (await session.execute(select(Course))).scalars().first()
        if existing:
            return
        result = await session.execute(select(Section))
        sections_by_key = {s.key: s for s in result.scalars().all()}

        for name, faculty, medium, notes, price, section_keys in COURSE_SEED:
            course = Course(name=name, faculty=faculty, medium=medium, notes=notes, price=price)
            for key in section_keys:
                sec = sections_by_key.get(key)
                if sec:
                    course.sections.append(sec)
            session.add(course)
        await session.commit()


# ---------------- v2 migration (safe on existing/deployed DBs) ----------------
NEW_TOP_SECTIONS = [
    ("prelims_mains", "Prelims & Mains Course", "♛"),
    ("test_series", "Test Series", "📝"),
    ("subject_specific", "Subject Specific Course", "🧑‍🏫"),
]

NEW_SUBJECT_CHILDREN = [
    ("subj_economy", "Economics (incl. Mrunal)", "💹"),
    ("subj_geography", "Geography (incl. Sudarshan Gujjar)", "🗺"),
    ("subj_polity", "Polity & Governance (incl. Jatin Gupta)", "🏛"),
    ("subj_environment_scitech", "Environment + Sci-Tech", "🌱"),
    ("subj_history", "History", "📜"),
    ("subj_ir", "International Relations", "🌐"),
    ("subj_public_admin", "Public Administration", "🏢"),
]

# (section_key_to_reparent, new_parent_key)
REPARENT = [
    ("upsc_prelims", "prelims_mains"),
    ("upsc_mains", "prelims_mains"),
    ("upsc_ts_prelims", "test_series"),
    ("upsc_ts_mains", "test_series"),
    ("upsc_ethics", "subject_specific"),
    ("upsc_essay", "subject_specific"),
    ("upsc_subject_specific", "subject_specific"),
]

# keyword -> extra section_key to *add* (additive tagging, never removes the
# course from wherever it already was) — used to sort the old catch-all
# "Subject Specific Course" pile into the new finer subject buckets.
KEYWORD_SECTION_MAP = [
    (["mrunal", "economy", "economics", "pcb", "shivin", "jayant", "aditya kaliya",
      "basava", "rishi jain", "bookstawa"], "subj_economy"),
    (["geography", "gujjar", "gurjar", "thapa", "himanshu"], "subj_geography"),
    (["polity", "governance", "jatin gupta", "sidharth arora", "laxmikanth"], "subj_polity"),
    (["environment", "sci-tech", "sci & tech", "science", "ecology", "pmf",
      "cp kaushik", "ravi agrahari"], "subj_environment_scitech"),
    (["history"], "subj_history"),
    (["international relations", "ir ", "chetan"], "subj_ir"),
    (["public administration", "pub ad"], "subj_public_admin"),
]

EXPLICIT_NEW_COURSES = [
    # (name, faculty, medium, notes, price, [section_keys])
    ("Polity & Governance — Jatin Gupta", "Jatin Gupta", "", "", None, ["subj_polity"]),
]


async def migrate_v2():
    """Idempotent — safe to call on every startup, on both a brand-new DB
    (seed_sections/seed_courses already built the v2 tree so this is a
    no-op) and an older deployed DB (brings it up to the v2 structure
    without deleting or losing anything)."""
    async with async_session() as session:
        result = await session.execute(select(Section))
        sections = {s.key: s for s in result.scalars().all()}
        if not sections:
            return  # DB not seeded yet — nothing to migrate

        changed = False

        # 1) ensure new top-level sections exist
        for key, name, emoji in NEW_TOP_SECTIONS:
            if key not in sections:
                sec = Section(key=key, name=name, emoji=emoji, parent_id=None)
                session.add(sec)
                await session.flush()
                sections[key] = sec
                changed = True

        # 2) ensure new subject-child sections exist
        for key, name, emoji in NEW_SUBJECT_CHILDREN:
            if key not in sections:
                parent = sections["subject_specific"]
                sec = Section(key=key, name=name, emoji=emoji, parent_id=parent.id)
                session.add(sec)
                await session.flush()
                sections[key] = sec
                changed = True

        # 3) reparent old sections onto the new top-level buckets
        for child_key, new_parent_key in REPARENT:
            child = sections.get(child_key)
            parent = sections.get(new_parent_key)
            if child and parent and child.parent_id != parent.id:
                child.parent_id = parent.id
                changed = True

        if changed:
            await session.commit()

        # 4) additive reclassification of the old subject-specific catch-all
        # pile into the finer subject buckets (keyword match on name+faculty)
        catchall = sections.get("upsc_subject_specific")
        if catchall:
            result = await session.execute(select(Course))
            all_courses = result.scalars().all()
            catchall_courses = [
                c for c in all_courses if any(s.key == "upsc_subject_specific" for s in c.sections)
            ]
            for course in catchall_courses:
                haystack = f"{course.name} {course.faculty}".lower()
                existing_keys = {s.key for s in course.sections}
                for keywords, target_key in KEYWORD_SECTION_MAP:
                    if target_key in existing_keys:
                        continue
                    if any(kw in haystack for kw in keywords):
                        target_sec = sections.get(target_key)
                        if target_sec:
                            course.sections.append(target_sec)
            await session.commit()

        # 5) add any explicit new named courses (e.g. Polity — Jatin Gupta)
        result = await session.execute(select(Course.name))
        existing_names = {n for (n,) in result.all()}
        for name, faculty, medium, notes, price, section_keys in EXPLICIT_NEW_COURSES:
            if name in existing_names:
                continue
            course = Course(name=name, faculty=faculty, medium=medium, notes=notes, price=price)
            for key in section_keys:
                sec = sections.get(key)
                if sec:
                    course.sections.append(sec)
            session.add(course)
        await session.commit()

        # 6) sync any COURSE_SEED entries that aren't in the DB yet by exact
        # name (keeps an existing deployed bot's catalog current if the seed
        # file is updated later — never touches an existing course's price).
        result = await session.execute(select(Course.name))
        existing_names = {n for (n,) in result.all()}
        for name, faculty, medium, notes, price, section_keys in COURSE_SEED:
            if name in existing_names:
                continue
            course = Course(name=name, faculty=faculty, medium=medium, notes=notes, price=price)
            for key in section_keys:
                sec = sections.get(key)
                if sec:
                    course.sections.append(sec)
            session.add(course)
        await session.commit()


# ---------------- v3 migration: simplified home screen ----------------
# Home screen now shows ONLY: UPSC | Prelims & Mains Specific Batch |
# Subject Specific Batch | State PSC | Search | Contact Professor (+ My Courses).
# UPSC Optional / Test Series move *inside* UPSC. NET-JRF, Combo Deals and
# Other Courses fold into Subject Specific so nothing is ever orphaned.
V3_REPARENT = [
    ("upsc_optional", "upsc"),
    ("upsc_ts_prelims", "upsc"),
    ("upsc_ts_mains", "upsc"),
    ("net_jrf_all", "subject_specific"),
    ("combo_deals", "subject_specific"),
    ("other_misc", "subject_specific"),
]

# additive tagging: fold CSAT / PYQ / Current Affairs into the new leaner
# UPSC menu (Foundation) and Prelims&Mains menu — courses keep their
# original section too, this only ADDS a second listing spot.
V3_ADDITIVE_TAGS = [
    ("upsc_csat", "upsc_prelims"),
    ("upsc_pyq", "upsc_prelims"),
    ("upsc_pyq", "upsc_mains"),
    ("upsc_ca", "upsc_foundation"),
]

V3_RENAME = {
    "upsc_ts_prelims": "Prelims Test Series 2027",
    "upsc_ts_mains": "Mains Test Series 2027",
}


async def migrate_v3():
    """Idempotent — collapses the home screen to just: UPSC, Prelims & Mains
    Specific Batch, Subject Specific Batch, State PSC (+ Search / Contact /
    My Courses handled purely in keyboards.py, no DB section needed for
    those). Never deletes a course — only re-parents/re-tags sections."""
    async with async_session() as session:
        result = await session.execute(select(Section))
        sections = {s.key: s for s in result.scalars().all()}
        if not sections:
            return

        changed = False
        for child_key, new_parent_key in V3_REPARENT:
            child = sections.get(child_key)
            parent = sections.get(new_parent_key)
            if child and parent and child.parent_id != parent.id:
                child.parent_id = parent.id
                changed = True

        for key, new_name in V3_RENAME.items():
            sec = sections.get(key)
            if sec and sec.name != new_name:
                sec.name = new_name
                changed = True

        if changed:
            await session.commit()

        result = await session.execute(select(Course))
        all_courses = result.scalars().all()
        for source_key, target_key in V3_ADDITIVE_TAGS:
            source_sec = sections.get(source_key)
            target_sec = sections.get(target_key)
            if not source_sec or not target_sec:
                continue
            tagged = [c for c in all_courses if any(s.key == source_key for s in c.sections)]
            for course in tagged:
                existing_keys = {s.key for s in course.sections}
                if target_key not in existing_keys:
                    course.sections.append(target_sec)
        await session.commit()
