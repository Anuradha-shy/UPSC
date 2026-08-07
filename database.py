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
    batch_id = Column(String(20), nullable=True, unique=True)  # e.g. "CSE-014" — shown to admin on every order
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
    "Geology", "Agriculture", "Physics",
]

# NET/JRF subject-wise leaves (parented under the "net_jrf" top section
# alongside the existing "net_jrf_all"). Keys match exactly what
# COURSE_SEED uses to tag courses — every one of these MUST exist for those
# courses to be visible anywhere in the bot (kept as explicit (key, name)
# pairs rather than auto-slugged, since "Paper 1" -> "net_jrf_paper1" isn't
# what a generic slugger would produce).
NET_JRF_SUBJECTS = [
    ("net_jrf_commerce", "Commerce"),
    ("net_jrf_computer_science", "Computer Science"),
    ("net_jrf_education", "Education"),
    ("net_jrf_english", "English"),
    ("net_jrf_geography", "Geography"),
    ("net_jrf_history", "History"),
    ("net_jrf_home_science", "Home Science"),
    ("net_jrf_law", "Law"),
    ("net_jrf_management", "Management"),
    ("net_jrf_philosophy", "Philosophy"),
    ("net_jrf_polity", "Polity"),
    ("net_jrf_psychology", "Psychology"),
    ("net_jrf_public_administration", "Public Administration"),
    ("net_jrf_sociology", "Sociology"),
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
        ("upsc_ethics", "Ethics (GS-4)", "⚖️"),
        ("upsc_essay", "Essay", "✍️"),
        ("upsc_subject_specific", "Subject Specific Course", "📚"),
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
        *[(key, name, "🎓") for key, name in NET_JRF_SUBJECTS],
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

        for name, faculty, medium, notes, price, section_keys, batch_id in COURSE_SEED:
            course = Course(name=name, faculty=faculty, medium=medium, notes=notes, price=price, batch_id=batch_id)
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

# NEW_SUBJECT_CHILDREN is intentionally empty — the fine-grained subject
# split (subj_economy, subj_geography, subj_polity, subj_environment_scitech,
# subj_history, subj_ir, subj_public_admin) was reverted per request:
# clicking "Subject Specific" now shows one flat, minimalist course list
# again instead of per-subject sub-buttons. migrate_v5() below merges any
# courses an earlier deploy had already split into those sections back into
# upsc_subject_specific and retires the now-empty sections. Kept as an
# empty list (not deleted) so migrate_v2()'s loop below stays valid.
NEW_SUBJECT_CHILDREN = []

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

# KEYWORD_SECTION_MAP is intentionally empty for the same reason — it used
# to additively sort courses into the fine subj_* buckets by keyword; that
# splitting is reverted, so this loop is now a no-op (kept, not deleted, so
# migrate_v2()'s step 4 below stays valid code).
KEYWORD_SECTION_MAP = []

EXPLICIT_NEW_COURSES = [
    # (name, faculty, medium, notes, price, [section_keys])
    ("Polity & Governance — Jatin Gupta", "Jatin Gupta", "", "", None, ["upsc_subject_specific"]),
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
        for name, faculty, medium, notes, price, section_keys, batch_id in COURSE_SEED:
            if name in existing_names:
                continue
            course = Course(name=name, faculty=faculty, medium=medium, notes=notes, price=price, batch_id=batch_id)
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


# ---------------- v4 migration: NET/JRF subject sections + full catalog sync ----------------
# Fixes a real bug: COURSE_SEED tags ~30 courses with per-subject NET/JRF
# section keys (net_jrf_commerce, ...) and one course with "optional_physics"
# — none of which were ever created as actual Section rows on an
# already-deployed DB. Those courses were silently inserted with ZERO
# sections attached, so they existed in the database but were invisible
# everywhere in the bot. This migration:
#   1) creates any missing NET/JRF subject sections + "optional_physics"
#   1c) folds "Paper 1" into net_jrf_all (no dedicated section for it —
#       moves any courses off a stray net_jrf_paper1 if one was ever created
#       by an earlier deploy, and retires that section)
#   2) re-attaches sections to any already-existing course that's missing
#      one or more of the sections COURSE_SEED says it should have
#      (additive only — never removes a section a course already has),
#      and backfills batch_id for any pre-existing course that doesn't
#      have one yet (never overwrites a batch_id that's already set)
#   3) adds any COURSE_SEED course that doesn't exist in the DB at all yet
#   4) soft-deactivates (is_active=False) any legacy course with price
#      IS NULL — these are the old "no price mentioned" entries that were
#      superseded once COURSE_SEED became fully priced (233/233 courses,
#      all priced). Nothing is hard-deleted, so this can be reversed by
#      flipping is_active back to True if a deactivation was ever wrong.
# Idempotent — safe to run on every startup.
async def migrate_v4():
    async with async_session() as session:
        result = await session.execute(select(Section))
        sections = {s.key: s for s in result.scalars().all()}
        if not sections:
            return  # DB not seeded yet

        changed = False

        # 1a) optional_physics
        if "optional_physics" not in sections:
            parent = sections.get("upsc_optional")
            if parent:
                sec = Section(key="optional_physics", name="Physics", emoji="📗", parent_id=parent.id)
                session.add(sec)
                await session.flush()
                sections["optional_physics"] = sec
                changed = True

        # 1b) NET/JRF subject sections
        net_jrf_parent = sections.get("net_jrf")
        if net_jrf_parent:
            for key, name in NET_JRF_SUBJECTS:
                if key not in sections:
                    sec = Section(key=key, name=name, emoji="🎓", parent_id=net_jrf_parent.id)
                    session.add(sec)
                    await session.flush()
                    sections[key] = sec
                    changed = True

        if changed:
            await session.commit()

        # 1c) fold "Paper 1" into net_jrf_all instead of its own section —
        # if an earlier deploy already created net_jrf_paper1, move any
        # courses off it onto net_jrf_all and retire (deactivate) the
        # now-empty section rather than leaving a dangling duplicate.
        stray = sections.get("net_jrf_paper1")
        all_subjects_sec = sections.get("net_jrf_all")
        if stray and all_subjects_sec:
            result = await session.execute(select(Course))
            for course in result.scalars().all():
                keys = {s.key for s in course.sections}
                if "net_jrf_paper1" in keys:
                    course.sections = [s for s in course.sections if s.key != "net_jrf_paper1"]
                    if "net_jrf_all" not in keys:
                        course.sections.append(all_subjects_sec)
            stray.is_active = False
            await session.commit()

        # 2) + 3) re-attach missing sections to existing courses, backfill
        # batch_id for pre-existing courses, and add any COURSE_SEED course
        # that's completely missing from the DB.
        result = await session.execute(select(Course))
        courses_by_name = {c.name: c for c in result.scalars().all()}

        for name, faculty, medium, notes, price, section_keys, batch_id in COURSE_SEED:
            # Paper 1 courses now point at net_jrf_all only, never a dedicated section.
            section_keys = ["net_jrf_all" if k == "net_jrf_paper1" else k for k in section_keys]
            course = courses_by_name.get(name)
            if course is None:
                course = Course(name=name, faculty=faculty, medium=medium, notes=notes,
                                 price=price, batch_id=batch_id)
                for key in section_keys:
                    sec = sections.get(key)
                    if sec:
                        course.sections.append(sec)
                session.add(course)
            else:
                if not course.batch_id and batch_id:
                    course.batch_id = batch_id
                existing_keys = {s.key for s in course.sections}
                for key in section_keys:
                    if key not in existing_keys:
                        sec = sections.get(key)
                        if sec:
                            course.sections.append(sec)
        await session.commit()

        # 4) deactivate legacy no-price courses
        result = await session.execute(select(Course).where(Course.price.is_(None), Course.is_active == True))  # noqa: E712
        for course in result.scalars().all():
            course.is_active = False
        await session.commit()


# ---------------- v5 migration: un-split "Subject Specific" ----------------
# Reverts the earlier fine-grained subject split under "Subject Specific"
# (Economics/Geography/Polity/Environment+Sci-Tech/History/IR/Public Admin
# as separate sub-buttons) back to one flat, minimalist list — clicking
# "Subject Specific" now shows every subject-specific course together again,
# same as the original design. Idempotent and safe on every startup: if a
# deployed DB never had the split (fresh installs after this change), the
# "stray" sections below simply won't exist and the loop is a no-op.
STRAY_SUBJECT_SECTIONS = [
    "subj_economy", "subj_geography", "subj_polity", "subj_environment_scitech",
    "subj_history", "subj_ir", "subj_public_admin",
]


async def migrate_v5():
    async with async_session() as session:
        result = await session.execute(select(Section))
        sections = {s.key: s for s in result.scalars().all()}
        if not sections:
            return

        catchall = sections.get("upsc_subject_specific")
        if not catchall:
            return

        result = await session.execute(select(Course))
        all_courses = result.scalars().all()

        any_stray_found = False
        for stray_key in STRAY_SUBJECT_SECTIONS:
            stray = sections.get(stray_key)
            if not stray:
                continue
            any_stray_found = True
            for course in all_courses:
                keys = {s.key for s in course.sections}
                if stray_key in keys:
                    course.sections = [s for s in course.sections if s.key != stray_key]
                    if "upsc_subject_specific" not in {s.key for s in course.sections}:
                        course.sections.append(catchall)
            stray.is_active = False

        if any_stray_found:
            await session.commit()
