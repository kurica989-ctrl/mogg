import telebot
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from datetime import datetime, timedelta

TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

ADMIN_IDS = [
    int(x)
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
]

# Kept at 18+ — this is a photo/rating/contact-exchange service, so the
# age gate matters. Change explicitly if you really mean to, not by accident.
MIN_AGE = 18

# Free-tier daily cap on ratings given (premium users bypass this).
FREE_DAILY_RATING_CAP = 50

bot = telebot.TeleBot(TOKEN)
BOT_USERNAME = None  # filled in at startup via bot.get_me()


# =========================================================
# DATABASE
# =========================================================

def get_db():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            username VARCHAR(255),
            name VARCHAR(255),
            age INT,
            height INT,
            weight INT,
            city VARCHAR(255),
            bio TEXT,
            gender VARCHAR(10),
            photo_id VARCHAR(255),
            registered BOOLEAN DEFAULT FALSE,
            is_banned BOOLEAN DEFAULT FALSE,
            ban_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Migration: CREATE TABLE IF NOT EXISTS does not alter an existing
    # table, so any new column has to be added explicitly here.
    new_columns = [
        ("rating", "FLOAT DEFAULT 0"),
        ("daily_bonus_count", "INT DEFAULT 0"),
        ("daily_bonus_date", "DATE"),
        ("weekly_top", "INT DEFAULT 0"),
        ("rank", "VARCHAR(50) DEFAULT 'Новичок'"),
        ("views_count", "INT DEFAULT 0"),
        ("is_premium", "BOOLEAN DEFAULT FALSE"),
        ("premium_until", "DATE"),
        ("referred_by", "BIGINT"),
        ("referral_count", "INT DEFAULT 0"),
        ("streak_count", "INT DEFAULT 0"),
        ("last_active_date", "DATE"),
        ("filter_same_city", "BOOLEAN DEFAULT FALSE"),
    ]
    for col_name, col_def in new_columns:
        cur.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col_name} {col_def}")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            id SERIAL PRIMARY KEY,
            from_user BIGINT,
            to_user BIGINT,
            rating VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(from_user, to_user),
            FOREIGN KEY(from_user) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(to_user) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            from_user BIGINT,
            to_user BIGINT,
            content TEXT,
            message_type VARCHAR(20),
            file_id VARCHAR(255),
            read BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(from_user) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(to_user) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id SERIAL PRIMARY KEY,
            user1 BIGINT,
            user2 BIGINT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user1, user2),
            FOREIGN KEY(user1) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(user2) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id SERIAL PRIMARY KEY,
            from_user BIGINT,
            target_user BIGINT,
            reason TEXT,
            status VARCHAR(20) DEFAULT 'open',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(from_user) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(target_user) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS profile_views (
            id SERIAL PRIMARY KEY,
            viewer_id BIGINT,
            viewed_id BIGINT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(viewer_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(viewed_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    cur.close()
    conn.close()


init_db()


# =========================================================
# RATING SYSTEM
# =========================================================

MALE_SCALE = [
    "Sub3", "Sub5", "LLTN", "LTN", "HLTN", "LMTN", "MTN",
    "HMTN", "LHTN", "HTN", "HHTN", "CHAD LITE", "TRUE ADAM"
]

FEMALE_SCALE = [
    "Sub3", "Sub5", "LLTB", "LTB", "HLTB", "LMTB", "MTB",
    "HMTB", "LHTB", "HTB", "HHTB", "Stacy", "True Eve"
]

SCALE_EMOJIS = {
    "Sub3": "😢", "Sub5": "😐", "LLTN": "😕", "LTN": "🙂", "HLTN": "😊",
    "LMTN": "😄", "MTN": "😍", "HMTN": "🔥", "LHTN": "💎", "HTN": "✨",
    "HHTN": "🌟", "CHAD LITE": "👑", "TRUE ADAM": "👨‍🦱",
    "LLTB": "😕", "LTB": "🙂", "HLTB": "😊", "LMTB": "😄", "MTB": "😍",
    "HMTB": "🔥", "LHTB": "💎", "HTB": "✨", "HHTB": "🌟",
    "Stacy": "👑", "True Eve": "👸",
}

HIGH_RATINGS = {
    "MTN", "HMTN", "LHTN", "HTN", "HHTN", "CHAD LITE", "TRUE ADAM",
    "MTB", "HMTB", "LHTB", "HTB", "HHTB", "Stacy", "True Eve",
}

RATING_MEANINGS = {
    "Sub3": "😢 Очень низкая оценка — есть много работы над собой. Начни с малого: спорт, уход, стиль.",
    "Sub5": "😐 Ниже среднего — потенциал есть, но нужно развивать.",
    "LLTN": "😕 Low Low Tier Normie — ты на старте. Первые шаги: причёска и спорт.",
    "LTN": "🙂 Low Tier Normie — неплохо, но есть куда расти.",
    "HLTN": "😊 High Low Tier Normie — выше среднего. Добавь стиля в одежде.",
    "LMTN": "😄 Low Mid Tier Normie — уже в хорошей форме. Работай над осанкой.",
    "MTN": "😍 Mid Tier Normie — база хорошая. Теперь работай над деталями.",
    "HMTN": "🔥 High Mid Tier Normie — выше среднего. Отличная симметрия лица.",
    "LHTN": "💎 Low High Tier Normie — почти топ. Добавь уверенности.",
    "HTN": "✨ High Tier Normie — ты в топ-15%.",
    "HHTN": "🌟 High High Tier Normie — ты среди лучших.",
    "CHAD LITE": "👑 Почти Чад — мощный потенциал.",
    "TRUE ADAM": "👨‍🦱 Идеал — ты лучшее, что есть.",
    "LLTB": "😕 Low Low Tier Beauty — начни с малого.",
    "LTB": "🙂 Low Tier Beauty — красива, но не раскрыта.",
    "HLTB": "😊 High Low Tier Beauty — на подъёме.",
    "LMTB": "😄 Low Mid Tier Beauty — отличная база.",
    "MTB": "😍 Mid Tier Beauty — уже хороша.",
    "HMTB": "🔥 High Mid Tier Beauty — шикарна.",
    "LHTB": "💎 Low High Tier Beauty — почти идеал.",
    "HTB": "✨ High Tier Beauty — ты в топе.",
    "HHTB": "🌟 High High Tier Beauty — среди лучших.",
    "Stacy": "👑 Stacy — идеал женской красоты.",
    "True Eve": "👸 True Eve — абсолютная женственность.",
}

RANK_EMOJIS = {
    "Новичок": "🧑‍🎓",
    "Любопытный": "👀",
    "Оценщик": "🔥",
    "Луксмаксер": "🏆",
    "Король": "👑",
    "Легенда": "💎",
}

STREAK_MILESTONES = {3: 0.2, 7: 0.5, 14: 1.0, 30: 2.5}


def get_scale(gender):
    return FEMALE_SCALE if gender == "female" else MALE_SCALE


def is_admin(user_id):
    return user_id in ADMIN_IDS


def is_premium_active(user):
    if not user or not user.get("is_premium"):
        return False
    until = user.get("premium_until")
    if until is None:
        return True  # permanent grant, no expiry set
    return until >= datetime.now().date()


def get_ratings_given(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM ratings WHERE from_user=%s", (user_id,))
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count


def get_user_place(user_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT u.id, COUNT(r.id) as count
        FROM users u
        LEFT JOIN ratings r ON r.to_user = u.id
        WHERE u.registered=TRUE AND u.is_banned=FALSE
        GROUP BY u.id
        ORDER BY count DESC
    """)
    users = cur.fetchall()
    cur.close()
    conn.close()
    for i, u in enumerate(users, 1):
        if u["id"] == user_id:
            return i, len(users)
    return None, None


def get_rank(user_data):
    user_id = user_data["id"]
    ratings_given = get_ratings_given(user_id)
    ratings_received = get_rating_total(user_id)
    place, _ = get_user_place(user_id)

    if place == 1 and ratings_received >= 100:
        return "Легенда"
    elif place == 1:
        return "Король"
    elif ratings_received >= 10:
        return "Луксмаксер"
    elif ratings_given >= 10:
        return "Оценщик"
    elif user_data.get("views_count", 0) >= 5:
        return "Любопытный"
    return "Новичок"


# =========================================================
# KEYBOARDS
# =========================================================

def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(KeyboardButton("🎲 Оценить"), KeyboardButton("💌 Письма"))
    kb.add(KeyboardButton("👤 Профиль"), KeyboardButton("💕 Мои оценки"))
    kb.add(KeyboardButton("❤️‍🔥 Мэтчи"), KeyboardButton("🏆 Топ"))
    kb.add(KeyboardButton("👥 Пригласить друзей"), KeyboardButton("📍 Фильтр города"))
    kb.add(KeyboardButton("🗑️ Удалить профиль"))
    return kb


def rating_kb(gender, target_id):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(
        InlineKeyboardButton("💌 Письмо", callback_data=f"msg_{target_id}"),
        InlineKeyboardButton("🤝 Познакомиться", callback_data=f"askuser_{target_id}"),
    )
    scale = get_scale(gender)
    for i in range(0, len(scale), 2):
        pair = scale[i:i + 2]
        kb.row(*[
            InlineKeyboardButton(f"{SCALE_EMOJIS.get(r, '⭐')} {r}", callback_data=f"rate_{target_id}_{r}")
            for r in pair
        ])
    kb.row(
        InlineKeyboardButton("⏭️ Пропустить", callback_data=f"skip_{target_id}"),
        InlineKeyboardButton("🚩 Жалоба", callback_data=f"report_{target_id}"),
    )
    return kb


def gender_kb():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("💪 Я парень", callback_data="gender_male"),
        InlineKeyboardButton("🌸 Я девушка", callback_data="gender_female"),
    )
    return kb


def rated_profile_kb(target_id):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(
        InlineKeyboardButton("⭐ Оценить в ответ", callback_data=f"replyrate_{target_id}"),
        InlineKeyboardButton("⏭️ Пропустить", callback_data=f"replyskip_{target_id}"),
    )
    kb.row(
        InlineKeyboardButton("💌 Письмо", callback_data=f"msg_{target_id}"),
        InlineKeyboardButton("🤝 Познакомиться", callback_data=f"askuser_{target_id}"),
    )
    kb.add(InlineKeyboardButton("🚩 Пожаловаться", callback_data=f"report_{target_id}"))
    return kb


def reply_rating_kb(gender, target_id):
    kb = InlineKeyboardMarkup(row_width=2)
    scale = get_scale(gender)
    for i in range(0, len(scale), 2):
        pair = scale[i:i + 2]
        kb.row(*[
            InlineKeyboardButton(f"{SCALE_EMOJIS.get(r, '⭐')} {r}", callback_data=f"rate_{target_id}_{r}")
            for r in pair
        ])
    kb.add(InlineKeyboardButton("⏭️ Пропустить", callback_data=f"replyskip_{target_id}"))
    return kb


def message_type_kb(target_id):
    kb = InlineKeyboardMarkup(row_width=3)
    kb.add(
        InlineKeyboardButton("📝 Текст", callback_data=f"msgtype_text_{target_id}"),
        InlineKeyboardButton("🎤 Голос", callback_data=f"msgtype_voice_{target_id}"),
        InlineKeyboardButton("🎙️ Кружок", callback_data=f"msgtype_circle_{target_id}"),
    )
    return kb


def rated_notify_kb(rater_id):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("👀 Показать анкету", callback_data=f"showrated_{rater_id}"))
    return kb


def letter_reply_kb(sender_id):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(
        InlineKeyboardButton("👀 Анкета", callback_data=f"viewsender_{sender_id}"),
        InlineKeyboardButton("🤝 Познакомиться", callback_data=f"askuser_{sender_id}"),
    )
    return kb


def report_reason_kb(target_id):
    kb = InlineKeyboardMarkup(row_width=1)
    reasons = [
        "Неприемлемое фото",
        "Оскорбления / харассмент",
        "Фейковый профиль",
        "Спам / реклама",
        "Другое",
    ]
    for reason in reasons:
        kb.add(InlineKeyboardButton(reason, callback_data=f"reportreason_{target_id}_{reason}"))
    return kb


def profile_kb():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("📤 Поделиться / пригласить", callback_data="share_profile"))
    return kb


def city_filter_kb(current_state):
    kb = InlineKeyboardMarkup(row_width=1)
    label = "✅ Только мой город (вкл)" if current_state else "⬜ Только мой город (выкл)"
    kb.add(InlineKeyboardButton(label, callback_data="togglecityfilter"))
    return kb


# =========================================================
# STATE
# =========================================================

user_states = {}
skipped_profiles = {}  # user_id -> set of profile ids skipped this session


def set_state(user_id, **state):
    user_states[user_id] = state


def get_state(user_id):
    return user_states.get(user_id, {})


def clear_state(user_id):
    user_states.pop(user_id, None)


# =========================================================
# DB HELPERS
# =========================================================

def get_user(user_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM users WHERE id=%s", (user_id,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user


def create_user(user_id, username, name, referred_by=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (id, username, name, referred_by) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
        (user_id, username, name, referred_by),
    )
    conn.commit()
    cur.close()
    conn.close()


def update_user(user_id, **kwargs):
    if not kwargs:
        return
    conn = get_db()
    cur = conn.cursor()
    set_clause = ", ".join(f"{key}=%s" for key in kwargs.keys())
    values = list(kwargs.values()) + [user_id]
    cur.execute(f"UPDATE users SET {set_clause} WHERE id=%s", values)
    conn.commit()
    cur.close()
    conn.close()


def delete_user(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()
    skipped_profiles.pop(user_id, None)
    user_states.pop(user_id, None)


def ban_user(user_id, reason=""):
    update_user(user_id, is_banned=True, ban_reason=reason)


def unban_user(user_id):
    update_user(user_id, is_banned=False, ban_reason=None)


def grant_premium(user_id, days=None):
    if days:
        until = (datetime.now().date() + timedelta(days=days))
        update_user(user_id, is_premium=True, premium_until=until)
    else:
        update_user(user_id, is_premium=True, premium_until=None)


def revoke_premium(user_id):
    update_user(user_id, is_premium=False, premium_until=None)


def get_random_user(exclude_user_id, extra_exclude=None, same_city=None):
    extra_exclude = extra_exclude or []
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    query = """
        SELECT * FROM users
        WHERE id != %s AND registered = TRUE AND is_banned = FALSE
        AND id NOT IN (SELECT to_user FROM ratings WHERE from_user = %s)
        AND NOT (id = ANY(%s))
    """
    params = [exclude_user_id, exclude_user_id, extra_exclude]
    if same_city:
        query += " AND city ILIKE %s"
        params.append(same_city)
    # premium profiles get a small boost in how often they're shown
    query += " ORDER BY is_premium DESC, RANDOM() LIMIT 1"
    cur.execute(query, params)
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user


def has_rated(from_user, to_user):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM ratings WHERE from_user=%s AND to_user=%s", (from_user, to_user))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row is not None


# =========================================================
# PROFILE VIEWS
# =========================================================

def record_profile_view(viewer_id, viewed_id):
    if viewer_id == viewed_id:
        return
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO profile_views (viewer_id, viewed_id) VALUES (%s, %s)",
        (viewer_id, viewed_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_unique_viewer_count(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(DISTINCT viewer_id) FROM profile_views WHERE viewed_id=%s", (user_id,))
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count


# =========================================================
# RATINGS
# =========================================================

def save_rating(from_user, to_user, rating):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO ratings (from_user, to_user, rating) VALUES (%s, %s, %s)
        ON CONFLICT (from_user, to_user)
        DO UPDATE SET rating = EXCLUDED.rating, created_at = CURRENT_TIMESTAMP
    """, (from_user, to_user, rating))
    conn.commit()
    cur.close()
    conn.close()
    check_match(from_user, to_user, rating)
    notify_about_rating(from_user, to_user, rating)
    update_daily_activity(from_user)


def check_match(from_user, to_user, new_rating):
    if new_rating not in HIGH_RATINGS:
        return
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT rating FROM ratings WHERE from_user=%s AND to_user=%s", (to_user, from_user))
    opposite = cur.fetchone()
    cur.close()
    if not opposite or opposite["rating"] not in HIGH_RATINGS:
        conn.close()
        return
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO matches (user1, user2) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (min(from_user, to_user), max(from_user, to_user)),
    )
    conn.commit()
    cur.close()
    conn.close()

    user1 = get_user(from_user)
    user2 = get_user(to_user)
    if not user1 or not user2:
        return
    username1 = user1.get("username") or "пользователь"
    username2 = user2.get("username") or "пользователь"
    try:
        bot.send_message(from_user, f"❤️‍🔥 *Лукмэтч!* ❤️‍🔥\n\nВы понравились друг другу!\n👤 @{username2}", parse_mode="Markdown")
    except Exception:
        pass
    try:
        bot.send_message(to_user, f"❤️‍🔥 *Лукмэтч!* ❤️‍🔥\n\nВы понравились друг другу!\n👤 @{username1}", parse_mode="Markdown")
    except Exception:
        pass


def notify_about_rating(from_user, to_user, rating):
    """Notify on every rating, high or low — with the rater's photo attached,
    but never their username (that stays hidden until an explicit contact
    exchange via 'Дать юз')."""
    if from_user == to_user:
        return
    rater = get_user(from_user)
    if not rater:
        return
    emoji = SCALE_EMOJIS.get(rating, "⭐")
    caption = f"{emoji} *Тебя только что оценили!*\n\nОценка: *{rating}*"
    kb = rated_notify_kb(from_user)
    try:
        if rater.get("photo_id"):
            bot.send_photo(to_user, rater["photo_id"], caption=caption, reply_markup=kb, parse_mode="Markdown")
        else:
            bot.send_message(to_user, caption, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        pass


def update_daily_activity(user_id):
    """Runs on every rating given. Handles three things in one pass:
    1) the 5-ratings-a-day bonus, 2) the day-streak counter, 3) resets
    the per-day rating counter used for the free-tier cap."""
    conn = get_db()
    cur = conn.cursor()
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    cur.execute(
        "SELECT daily_bonus_date, daily_bonus_count, rating, last_active_date, streak_count FROM users WHERE id=%s",
        (user_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return
    bonus_date, bonus_count, current_rating, last_active, streak = row
    current_rating = float(current_rating or 0)
    streak = streak or 0

    # --- daily ratings-given counter + 5-rating bonus ---
    if bonus_date == today:
        count = (bonus_count or 0) + 1
        update_user(user_id, daily_bonus_date=today, daily_bonus_count=count)
        if count == 5:
            update_user(user_id, rating=round(current_rating + 0.5, 2), weekly_top=1)
            try:
                bot.send_message(user_id, "🏆 *Ежедневный бонус!*\n\nТы поставил уже 5 оценок сегодня 🔥\nРейтинг +0.5!", parse_mode="Markdown")
            except Exception:
                pass
    else:
        update_user(user_id, daily_bonus_date=today, daily_bonus_count=1)

    # --- streak ---
    if last_active == today:
        pass  # already counted today
    elif last_active == yesterday:
        streak += 1
        update_user(user_id, last_active_date=today, streak_count=streak)
        if streak in STREAK_MILESTONES:
            bonus = STREAK_MILESTONES[streak]
            new_rating = round(current_rating + bonus, 2)
            update_user(user_id, rating=new_rating)
            try:
                bot.send_message(
                    user_id,
                    f"🔥 *Стрик {streak} дней подряд!*\n\nРейтинг +{bonus}. Не останавливайся!",
                    parse_mode="Markdown",
                )
            except Exception:
                pass
    else:
        update_user(user_id, last_active_date=today, streak_count=1)


def get_daily_rating_count(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT daily_bonus_date, daily_bonus_count FROM users WHERE id=%s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row or row[0] != datetime.now().date():
        return 0
    return row[1] or 0


def get_latest_rating(from_user, to_user):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT rating FROM ratings WHERE from_user=%s AND to_user=%s LIMIT 1", (from_user, to_user))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result


def get_rating_counts(user_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT rating, COUNT(*) as count FROM ratings WHERE to_user=%s GROUP BY rating", (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {r["rating"]: r["count"] for r in rows}


def get_rating_total(user_id):
    return sum(get_rating_counts(user_id).values())


# =========================================================
# REFERRALS
# =========================================================

def handle_referral_bonus(referrer_id, new_user_id):
    referrer = get_user(referrer_id)
    if not referrer or referrer_id == new_user_id:
        return
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT rating, referral_count FROM users WHERE id=%s", (referrer_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return
    current_rating = float(row[0] or 0)
    referral_count = (row[1] or 0) + 1
    update_user(referrer_id, rating=round(current_rating + 0.3, 2), referral_count=referral_count)
    try:
        bot.send_message(
            referrer_id,
            "🎉 *По твоей ссылке зарегистрировался новый человек!*\n\nРейтинг +0.3. Спасибо, что приводишь друзей 💫",
            parse_mode="Markdown",
        )
    except Exception:
        pass


def referral_link(user_id):
    if BOT_USERNAME:
        return f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    return f"(ссылка появится после первого /start у бота) start=ref_{user_id}"


# =========================================================
# MESSAGES
# =========================================================

def save_message(from_user, to_user, content, msg_type, file_id=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (from_user, to_user, content, message_type, file_id) VALUES (%s, %s, %s, %s, %s)",
        (from_user, to_user, content, msg_type, file_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_unread_messages(user_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT id, from_user, content, message_type, file_id FROM messages "
        "WHERE to_user=%s AND read=FALSE ORDER BY created_at DESC",
        (user_id,),
    )
    messages = cur.fetchall()
    cur.close()
    conn.close()
    return messages


def mark_message_read(msg_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE messages SET read=TRUE WHERE id=%s", (msg_id,))
    conn.commit()
    cur.close()
    conn.close()


# =========================================================
# MATCHES
# =========================================================

def get_matches(user_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT CASE WHEN user1=%s THEN user2 ELSE user1 END AS matched_user "
        "FROM matches WHERE user1=%s OR user2=%s",
        (user_id, user_id, user_id),
    )
    matches = cur.fetchall()
    cur.close()
    conn.close()
    return [m["matched_user"] for m in matches]


# =========================================================
# REPORTS
# =========================================================

def save_report(from_user, target_user, reason):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO reports (from_user, target_user, reason) VALUES (%s, %s, %s) RETURNING id",
        (from_user, target_user, reason),
    )
    report_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return report_id


def get_open_reports():
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT rp.id, rp.from_user, rp.target_user, rp.reason, rp.created_at, u.username AS target_username
        FROM reports rp JOIN users u ON rp.target_user = u.id
        WHERE rp.status='open' ORDER BY rp.created_at DESC LIMIT 20
    """)
    reports = cur.fetchall()
    cur.close()
    conn.close()
    return reports


def close_report(report_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE reports SET status='closed' WHERE id=%s", (report_id,))
    conn.commit()
    cur.close()
    conn.close()


# =========================================================
# ADMIN
# =========================================================

def notify_admins(text, reply_markup=None):
    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, text, parse_mode="Markdown", reply_markup=reply_markup)
        except Exception:
            pass


def get_registered_users_for_broadcast():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE registered=TRUE AND is_banned=FALSE")
    users = cur.fetchall()
    cur.close()
    conn.close()
    return [row[0] for row in users]


# =========================================================
# PROFILE DISPLAY
# =========================================================

def build_profile_text(user, rating=None):
    """Shared card renderer — shows name, age, height, weight, city, bio.
    Never includes the Telegram username (that stays private by default)."""
    rank = user.get("rank", "Новичок")
    rank_emoji = RANK_EMOJIS.get(rank, "🧑‍🎓")
    bio = (user.get("bio") or "").strip()
    bio_line = f"📝 _{bio}_" if bio else "📝 _без описания_"
    premium_line = "💎 *Premium*\n" if is_premium_active(user) else ""
    text = (
        f"{premium_line}"
        f"{rank_emoji} *{rank}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 *{user.get('name') or 'Анкета'}*  ·  {user['age']} лет\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📏 {user['height']} см   ⚖️ {user['weight']} кг\n"
        f"🏙️ {user['city']}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{bio_line}\n"
        f"━━━━━━━━━━━━━━━"
    )
    if rating:
        emoji = SCALE_EMOJIS.get(rating, "⭐")
        meaning = RATING_MEANINGS.get(rating, "")
        text += f"\n\n{emoji} *Оценка: {rating}*"
        if meaning:
            text += f"\n_{meaning}_"
    return text


def show_rating_card(uid, target):
    record_profile_view(uid, target["id"])
    text = build_profile_text(target) + "\n\n💖 *Оцени внешность:*"
    kb = rating_kb(target["gender"], target["id"])
    if target.get("photo_id"):
        bot.send_photo(uid, target["photo_id"], caption=text, reply_markup=kb, parse_mode="Markdown")
    else:
        bot.send_message(uid, text, reply_markup=kb, parse_mode="Markdown")


def show_rated_profile(uid, target, rating):
    text = build_profile_text(target, rating=rating)
    markup = rated_profile_kb(target["id"])
    if target.get("photo_id"):
        bot.send_photo(uid, target["photo_id"], caption=text, reply_markup=markup, parse_mode="Markdown")
    else:
        bot.send_message(uid, text, reply_markup=markup, parse_mode="Markdown")


# =========================================================
# REGISTRATION
# =========================================================

@bot.message_handler(commands=["start"])
def start(m):
    uid = m.chat.id
    user = get_user(uid)

    if not user:
        referred_by = None
        parts = m.text.split(maxsplit=1)
        if len(parts) > 1 and parts[1].startswith("ref_"):
            ref_part = parts[1][4:]
            if ref_part.isdigit():
                candidate = int(ref_part)
                if candidate != uid and get_user(candidate):
                    referred_by = candidate

        create_user(uid, m.from_user.username or f"user_{uid}", m.from_user.first_name, referred_by=referred_by)
        bot.send_message(
            uid,
            "💖 *Добро пожаловать в Моггвинчик!* 💖\n\n"
            "Здесь тебя честно оценят по внешности — без фильтров и лишней воды.\n\n"
            "📸 Заполни короткую анкету и начинай получать оценки и мэтчи.\n\n"
            f"🚀 Сервис доступен только пользователям {MIN_AGE}+.\n\n"
            "Для начала напиши свой *возраст* числом 👇",
            parse_mode="Markdown",
        )
        return

    if user.get("is_banned"):
        bot.send_message(uid, "⛔ Твой аккаунт заблокирован модерацией." + (f"\nПричина: {user.get('ban_reason')}" if user.get("ban_reason") else ""))
        return
    if user.get("registered"):
        bot.send_message(uid, "✨ С возвращением!\n\nРад снова тебя видеть 💫\nЧто делаем дальше?", reply_markup=main_menu())
    else:
        bot.send_message(uid, "Продолжим регистрацию ✨\nПросто ответь на следующий вопрос 👇")


# =========================================================
# ADMIN PANEL
# =========================================================

@bot.message_handler(commands=["admin"])
def admin_panel(m):
    uid = m.chat.id
    if not is_admin(uid):
        return
    reports = get_open_reports()
    if not reports:
        bot.send_message(uid, "✅ Открытых жалоб нет.")
        return
    for report in reports:
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("⛔ Забанить", callback_data=f"adminban_{report['target_user']}_{report['id']}"),
            InlineKeyboardButton("✅ Отклонить", callback_data=f"admindismiss_{report['id']}"),
        )
        bot.send_message(
            uid,
            f"🚩 Жалоба #{report['id']}\nНа: @{report['target_username']} (id {report['target_user']})\nПричина: {report['reason']}",
            reply_markup=kb,
        )


@bot.message_handler(commands=["ban"])
def cmd_ban(m):
    uid = m.chat.id
    if not is_admin(uid):
        return
    parts = m.text.split(maxsplit=2)
    if len(parts) < 2 or not parts[1].isdigit():
        bot.send_message(uid, "Использование: /ban <user_id> [причина]")
        return
    target_id = int(parts[1])
    reason = parts[2] if len(parts) > 2 else ""
    ban_user(target_id, reason)
    bot.send_message(uid, f"⛔ Пользователь {target_id} забанен.")
    try:
        bot.send_message(target_id, "⛔ Твой аккаунт заблокирован модерацией." + (f"\nПричина: {reason}" if reason else ""))
    except Exception:
        pass


@bot.message_handler(commands=["unban"])
def cmd_unban(m):
    uid = m.chat.id
    if not is_admin(uid):
        return
    parts = m.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].isdigit():
        bot.send_message(uid, "Использование: /unban <user_id>")
        return
    target_id = int(parts[1])
    unban_user(target_id)
    bot.send_message(uid, f"✅ Пользователь {target_id} разбанен.")


@bot.message_handler(commands=["grantpremium"])
def cmd_grant_premium(m):
    uid = m.chat.id
    if not is_admin(uid):
        return
    parts = m.text.split(maxsplit=2)
    if len(parts) < 2 or not parts[1].isdigit():
        bot.send_message(uid, "Использование: /grantpremium <user_id> [дней, необязательно]")
        return
    target_id = int(parts[1])
    days = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    grant_premium(target_id, days)
    bot.send_message(uid, f"💎 Premium выдан пользователю {target_id}" + (f" на {days} дней" if days else " бессрочно"))
    try:
        bot.send_message(target_id, "💎 *Тебе выдан Premium!*\n\n— Безлимит оценок в день\n— Профиль показывается чаще\n— Приоритет в топе", parse_mode="Markdown")
    except Exception:
        pass


@bot.message_handler(commands=["revokepremium"])
def cmd_revoke_premium(m):
    uid = m.chat.id
    if not is_admin(uid):
        return
    parts = m.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].isdigit():
        bot.send_message(uid, "Использование: /revokepremium <user_id>")
        return
    target_id = int(parts[1])
    revoke_premium(target_id)
    bot.send_message(uid, f"✅ Premium снят с пользователя {target_id}")


# =========================================================
# BROADCAST
# =========================================================

@bot.message_handler(commands=["broadcast"])
def broadcast(m):
    uid = m.chat.id
    if not is_admin(uid):
        return
    parts = m.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(uid, "📢 Использование:\n\n/broadcast Текст сообщения")
        return
    message_text = parts[1].strip()
    if not message_text:
        bot.send_message(uid, "❌ Сообщение не может быть пустым.")
        return
    users = get_registered_users_for_broadcast()
    total = len(users)
    sent = 0
    failed = 0
    bot.send_message(uid, f"📢 Начинаю рассылку.\nПолучателей: {total}")
    for target_id in users:
        try:
            bot.send_message(target_id, message_text)
            sent += 1
        except Exception:
            failed += 1
    bot.send_message(
        uid,
        f"📊 **Рассылка завершена**\n\n👥 Всего: {total}\n✅ Доставлено: {sent}\n❌ Ошибок: {failed}",
        parse_mode="Markdown",
    )


# =========================================================
# TEXT HANDLER
# =========================================================

@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_text(m):
    uid = m.chat.id
    user = get_user(uid)
    state = get_state(uid)
    if not user:
        return
    if user.get("is_banned"):
        bot.send_message(uid, "⛔ Твой аккаунт заблокирован модерацией.")
        return

    # --- registration ---
    if not user.get("age") and m.text.isdigit():
        age = int(m.text)
        if age < MIN_AGE:
            bot.send_message(uid, f"❌ Сервис доступен только пользователям {MIN_AGE}+. Регистрация невозможна.")
            return
        if age > 100:
            bot.send_message(uid, "❌ Введи корректный возраст.")
            return
        update_user(uid, age=age)
        bot.send_message(uid, "📏 Какой у тебя рост?\n(в сантиметрах, число от 100 до 250)")
        return

    if user.get("age") and not user.get("height"):
        if not m.text.isdigit() or not (100 <= int(m.text) <= 250):
            bot.send_message(uid, "❌ Рост нужно указать числом от 100 до 250 см.")
            return
        update_user(uid, height=int(m.text))
        bot.send_message(uid, "⚖️ А вес?\n(в килограммах, число от 30 до 250)")
        return

    if user.get("height") and not user.get("weight"):
        if not m.text.isdigit() or not (30 <= int(m.text) <= 250):
            bot.send_message(uid, "❌ Вес нужно указать числом от 30 до 250 кг.")
            return
        update_user(uid, weight=int(m.text))
        bot.send_message(uid, "🏙️ Из какого ты города?")
        return

    if user.get("weight") and not user.get("city"):
        update_user(uid, city=m.text[:50])
        bot.send_message(uid, "📝 Расскажи немного о себе\n(максимум 200 символов)\n\nМожно пропустить — просто напиши *пропустить*", parse_mode="Markdown")
        return

    if user.get("city") and user.get("bio") is None:
        text_lower = (m.text or "").strip().lower()
        bio_value = "" if text_lower in ("пропустить", "skip", "-", "нет", "не хочу") else (m.text or "")[:200]
        update_user(uid, bio=bio_value)
        bot.send_message(uid, "📸 Отлично! Теперь отправь свою фотографию\n(лучше селфи или портрет в хорошем качестве)", parse_mode="Markdown")
        return

    # --- report free text ---
    if state.get("action") == "reporting_other":
        target_id = state.get("target_id")
        save_report(uid, target_id, m.text[:300])
        bot.send_message(uid, "✅ Жалоба отправлена модераторам.", reply_markup=main_menu())
        notify_admins(f"🚩 Новая жалоба\n\nНа пользователя id: {target_id}\nПричина: {m.text[:300]}")
        clear_state(uid)
        return

    # --- sending a text letter ---
    if state.get("action") == "sending_message" and state.get("msg_type") == "text":
        target_id = state.get("target_id")
        save_message(uid, target_id, m.text, "text")
        target = get_user(target_id)
        clear_state(uid)
        if target:
            bot.send_message(uid, "✅ Письмо отправлено!\n\nТеперь оцени анкету 👇")
            show_rating_card(uid, target)
        else:
            bot.send_message(uid, "✅ Письмо отправлено!", reply_markup=main_menu())
        return

    # --- delete confirmation ---
    if state.get("action") == "confirm_delete":
        if m.text.lower() == "да":
            delete_user(uid)
            bot.send_message(uid, "❌ Твой профиль удален.")
            clear_state(uid)
            return
        if m.text.lower() == "нет":
            clear_state(uid)
            bot.send_message(uid, "✅ Отмена.", reply_markup=main_menu())
            return

    # --- main menu ---
    if m.text == "🎲 Оценить":
        rate_menu(uid)
    elif m.text == "👤 Профиль":
        show_profile(m)
    elif m.text == "💕 Мои оценки":
        show_ratings(m)
    elif m.text == "💌 Письма":
        show_messages(m)
    elif m.text == "❤️‍🔥 Мэтчи":
        show_matches(m)
    elif m.text == "🏆 Топ":
        show_top(m)
    elif m.text == "👥 Пригласить друзей":
        show_referral(m)
    elif m.text == "📍 Фильтр города":
        show_city_filter(m)
    elif m.text == "🗑️ Удалить профиль":
        confirm_delete(m)
    elif m.text == "📬 Прочитать письма":
        read_messages(m)
    elif m.text == "⬅️ Назад":
        bot.send_message(uid, "Главное меню", reply_markup=main_menu())


# =========================================================
# PHOTO / VOICE / VIDEO NOTE
# =========================================================

@bot.message_handler(content_types=["photo"])
def handle_photo(m):
    uid = m.chat.id
    user = get_user(uid)
    if user and user.get("city") and user.get("bio") is not None and not user.get("photo_id"):
        update_user(uid, photo_id=m.photo[-1].file_id)
        bot.send_message(uid, "👤 Последний шаг — выбери свой пол 👇", reply_markup=gender_kb())


@bot.message_handler(content_types=["voice"])
def handle_voice(m):
    uid = m.chat.id
    state = get_state(uid)
    if state.get("action") == "sending_message" and state.get("msg_type") == "voice":
        target_id = state.get("target_id")
        save_message(uid, target_id, "🎤 Голосовое сообщение", "voice", m.voice.file_id)
        target = get_user(target_id)
        clear_state(uid)
        if target:
            bot.send_message(uid, "✅ Голосовое письмо отправлено!\n\nТеперь оцени анкету 👇")
            show_rating_card(uid, target)
        else:
            bot.send_message(uid, "✅ Голосовое письмо отправлено!", reply_markup=main_menu())


@bot.message_handler(content_types=["video_note"])
def handle_circle(m):
    uid = m.chat.id
    state = get_state(uid)
    if state.get("action") == "sending_message" and state.get("msg_type") == "circle":
        target_id = state.get("target_id")
        save_message(uid, target_id, "🎙️ Кружок", "circle", m.video_note.file_id)
        target = get_user(target_id)
        clear_state(uid)
        if target:
            bot.send_message(uid, "✅ Кружок отправлен!\n\nТеперь оцени анкету 👇")
            show_rating_card(uid, target)
        else:
            bot.send_message(uid, "✅ Кружок отправлен!", reply_markup=main_menu())


# =========================================================
# GENDER
# =========================================================

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("gender_"))
def set_gender(c):
    uid = c.from_user.id
    try:
        bot.answer_callback_query(c.id, text="✅")
    except Exception:
        pass
    try:
        gender = "male" if c.data == "gender_male" else "female"
        was_registered_before = False
        existing = get_user(uid)
        if existing:
            was_registered_before = bool(existing.get("registered"))
        update_user(uid, gender=gender, registered=True)

        # first time this user becomes registered -> pay out referral bonus
        if not was_registered_before and existing and existing.get("referred_by"):
            handle_referral_bonus(existing["referred_by"], uid)

        try:
            bot.delete_message(c.message.chat.id, c.message.message_id)
        except Exception:
            try:
                bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
            except Exception:
                pass
        bot.send_message(
            uid,
            "🎉 *ГОТОВО!*\n\nТвой профиль создан и уже доступен для оценок ✨\n\nЖми «🎲 Оценить» и начинай 👇",
            reply_markup=main_menu(),
            parse_mode="Markdown",
        )
    except Exception as e:
        print(f"[set_gender error] uid={uid}: {e}")
        try:
            bot.send_message(uid, "⚠️ Произошла ошибка при сохранении профиля.\nПопробуй ещё раз или напиши /start")
        except Exception:
            pass


# =========================================================
# RATING MENU
# =========================================================

def rate_menu(uid):
    user = get_user(uid)
    if not user or not user.get("registered"):
        bot.send_message(uid, "❌ Сначала заверши регистрацию через /start")
        return

    if not is_premium_active(user) and get_daily_rating_count(uid) >= FREE_DAILY_RATING_CAP:
        bot.send_message(
            uid,
            f"⏳ Ты уже поставил {FREE_DAILY_RATING_CAP} оценок сегодня — это дневной лимit для бесплатного аккаунта.\n\n"
            "💎 Premium снимает лимит полностью. Загляни завтра или напиши администратору за Premium.",
            reply_markup=main_menu(),
        )
        return

    update_user(uid, views_count=user.get("views_count", 0) + 1)
    rank = get_rank(user)
    if rank != user.get("rank"):
        update_user(uid, rank=rank)

    same_city = user["city"] if user.get("filter_same_city") and user.get("city") else None
    skipped = skipped_profiles.get(uid, set())
    target = get_random_user(uid, extra_exclude=list(skipped), same_city=same_city)
    if not target:
        if skipped:
            skipped_profiles[uid] = set()
            target = get_random_user(uid, same_city=same_city)
        if not target and same_city:
            # nobody left in the same city — fall back to everyone rather than a dead end
            target = get_random_user(uid)
            if target:
                bot.send_message(uid, "📍 В твоём городе больше некого оценивать — показываю анкеты отовсюду.")
        if not target:
            bot.send_message(
                uid,
                "😢 Пока некого оценивать — загляни чуть позже.\n\n👥 А пока можешь позвать друзей в бота!",
                reply_markup=main_menu(),
            )
            return

    show_rating_card(uid, target)


@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_"))
def set_rating(c):
    parts = c.data.split("_", 2)
    target_id = int(parts[1])
    rating = parts[2]
    uid = c.from_user.id

    if target_id == uid:
        bot.answer_callback_query(c.id, "Нельзя оценить себя 😄")
        return
    if has_rated(uid, target_id):
        bot.answer_callback_query(c.id, "Ты уже оценивал(-а) этого пользователя")
        return

    user = get_user(uid)
    if not is_premium_active(user) and get_daily_rating_count(uid) >= FREE_DAILY_RATING_CAP:
        bot.answer_callback_query(c.id, "Дневной лимит оценок исчерпан. Premium снимает лимит.", show_alert=True)
        return

    target = get_user(target_id)
    if not target or not target.get("registered") or target.get("is_banned"):
        bot.answer_callback_query(c.id, "Анкета больше недоступна")
        return

    save_rating(uid, target_id, rating)
    emoji = SCALE_EMOJIS.get(rating, "⭐")
    bot.answer_callback_query(c.id, f"✅ {emoji} {rating}")

    try:
        bot.delete_message(c.message.chat.id, c.message.message_id)
    except Exception:
        pass

    rate_menu(uid)


@bot.callback_query_handler(func=lambda c: c.data.startswith("showrated_"))
def show_rated(c):
    uid = c.from_user.id
    target_id = int(c.data.split("_")[1])
    target = get_user(target_id)
    if not target or not target.get("registered") or target.get("is_banned"):
        bot.answer_callback_query(c.id, "Эта анкета больше недоступна")
        return

    rating_data = get_latest_rating(target_id, uid)
    if not rating_data:
        bot.answer_callback_query(c.id, "Оценка не найдена")
        return

    bot.answer_callback_query(c.id)
    try:
        bot.delete_message(c.message.chat.id, c.message.message_id)
    except Exception:
        pass
    show_rated_profile(uid, target, rating_data["rating"])


@bot.callback_query_handler(func=lambda c: c.data.startswith("viewsender_"))
def show_letter_sender(c):
    """Same idea as 'Показать анкету' but triggered from a letter instead
    of a rating notification — lets the recipient view (and optionally
    rate) whoever wrote to them, without exposing a username."""
    uid = c.from_user.id
    sender_id = int(c.data.split("_")[1])
    sender = get_user(sender_id)
    bot.answer_callback_query(c.id)
    if not sender or not sender.get("registered") or sender.get("is_banned"):
        bot.send_message(uid, "😕 Анкета больше недоступна")
        return
    if has_rated(uid, sender_id):
        text = build_profile_text(sender)
        if sender.get("photo_id"):
            bot.send_photo(uid, sender["photo_id"], caption=text, parse_mode="Markdown")
        else:
            bot.send_message(uid, text, parse_mode="Markdown")
    else:
        show_rating_card(uid, sender)


@bot.callback_query_handler(func=lambda c: c.data.startswith("replyskip_"))
def handle_reply_skip(c):
    bot.answer_callback_query(c.id, "⏭️ Пропущено")
    try:
        bot.delete_message(c.message.chat.id, c.message.message_id)
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.data.startswith("replyrate_"))
def handle_reply_rate(c):
    uid = c.from_user.id
    target_id = int(c.data.split("_")[1])
    target = get_user(target_id)
    if not target or not target.get("registered") or target.get("is_banned"):
        bot.answer_callback_query(c.id, "Эта анкета больше недоступна")
        return
    if target_id == uid:
        bot.answer_callback_query(c.id, "Нельзя оценить себя 😄")
        return
    bot.answer_callback_query(c.id)
    try:
        bot.edit_message_reply_markup(uid, c.message.message_id, reply_markup=None)
    except Exception:
        pass
    bot.send_message(uid, "⭐ **Оцени его/её в ответ:**", reply_markup=reply_rating_kb(target["gender"], target_id), parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data.startswith("skip_"))
def handle_skip(c):
    uid = c.from_user.id
    target_id = int(c.data.split("_")[1])
    skipped_profiles.setdefault(uid, set()).add(target_id)
    bot.answer_callback_query(c.id, "⏭️ Пропущено")
    try:
        bot.delete_message(c.message.chat.id, c.message.message_id)
    except Exception:
        pass
    rate_menu(uid)


# =========================================================
# CITY FILTER
# =========================================================

def show_city_filter(m):
    uid = m.chat.id
    user = get_user(uid)
    if not user or not user.get("registered"):
        bot.send_message(uid, "❌ Сначала заверши регистрацию через /start")
        return
    state = bool(user.get("filter_same_city"))
    bot.send_message(
        uid,
        f"📍 Сейчас фильтр по городу: {'включён' if state else 'выключен'}.\n\n"
        f"Твой город: {user.get('city') or 'не указан'}\n\n"
        "Если включить — при оценивании будут показываться только анкеты из твоего города.",
        reply_markup=city_filter_kb(state),
    )


@bot.callback_query_handler(func=lambda c: c.data == "togglecityfilter")
def toggle_city_filter(c):
    uid = c.from_user.id
    user = get_user(uid)
    if not user:
        bot.answer_callback_query(c.id, "Профиль не найден")
        return
    new_state = not bool(user.get("filter_same_city"))
    update_user(uid, filter_same_city=new_state)
    bot.answer_callback_query(c.id, "✅ Обновлено")
    try:
        bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=city_filter_kb(new_state))
    except Exception:
        pass


# =========================================================
# PROFILE
# =========================================================

def show_profile(m):
    uid = m.chat.id
    user = get_user(uid)
    if not user or not user.get("registered"):
        bot.send_message(uid, "❌ Сначала заверши регистрацию через /start")
        return

    rank = user.get("rank", "Новичок")
    rank_emoji = RANK_EMOJIS.get(rank, "🧑‍🎓")
    emoji = "👨" if user["gender"] == "male" else "👩"
    place, total = get_user_place(uid)
    bio = (user.get("bio") or "").strip()
    bio_line = f"📝 _{bio}_" if bio else "📝 _без описания_"
    viewer_count = get_unique_viewer_count(uid)
    premium_line = "💎 *Premium активен*\n" if is_premium_active(user) else ""

    text = (
        f"{emoji} *Моя анкета*\n"
        f"{premium_line}"
        f"{rank_emoji} *Звание:* {rank}\n\n"
        f"📅 {user['age']} лет\n"
        f"📏 {user['height']} см\n"
        f"⚖️ {user['weight']} кг\n"
        f"🏙️ {user['city']}\n"
        f"{bio_line}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"⭐ Рейтинг: {user['rating']}\n"
        f"👁 Анкету посмотрели: {viewer_count} чел.\n"
        f"🔥 Стрик: {user.get('streak_count', 0)} дн.\n"
        f"👥 Приглашено друзей: {user.get('referral_count', 0)}\n"
    )
    if place:
        text += f"🏆 Место в топе: {place} из {total}\n"
    daily_bonus = user.get("daily_bonus_count", 0)
    if daily_bonus > 0:
        text += f"📊 Сегодня оценок: {daily_bonus}/{FREE_DAILY_RATING_CAP if not is_premium_active(user) else '∞'}\n"

    if user.get("photo_id"):
        bot.send_photo(uid, user["photo_id"], caption=text, reply_markup=main_menu(), parse_mode="Markdown")
    else:
        bot.send_message(uid, text, reply_markup=main_menu(), parse_mode="Markdown")
    bot.send_message(uid, "👇 Поделиться профилем / пригласить друзей:", reply_markup=profile_kb())


# =========================================================
# MY RATINGS — grouped & counted, not one line per rating
# =========================================================

def show_ratings(m):
    uid = m.chat.id
    user = get_user(uid)
    counts = get_rating_counts(uid)
    total = sum(counts.values())
    if not total:
        bot.send_message(uid, "📊 Пока никто тебя не оценил 🥺\nОценивай других — и оценки скоро появятся!", reply_markup=main_menu())
        return

    scale = get_scale(user["gender"])
    lines = []
    for r in reversed(scale):
        c = counts.get(r)
        if c:
            emoji = SCALE_EMOJIS.get(r, "⭐")
            lines.append(f"{emoji}  {r:<10} ×{c}")
    text = f"💕 *Тебя оценили {total} раз(а):*\n━━━━━━━━━━━━━━━\n" + "\n".join(lines)
    bot.send_message(uid, text, parse_mode="Markdown", reply_markup=main_menu())


# =========================================================
# REFERRALS
# =========================================================

def show_referral(m):
    uid = m.chat.id
    user = get_user(uid)
    if not user or not user.get("registered"):
        bot.send_message(uid, "❌ Сначала заверши регистрацию через /start")
        return
    link = referral_link(uid)
    text = (
        "👥 *Пригласи друзей!*\n\n"
        "За каждого друга, который зарегистрируется по твоей ссылке — +0.3 к рейтингу 🎉\n\n"
        f"Твоя ссылка:\n`{link}`\n\n"
        f"Уже приглашено: {user.get('referral_count', 0)} чел."
    )
    bot.send_message(uid, text, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data == "share_profile")
def share_profile(c):
    uid = c.from_user.id
    user = get_user(uid)
    bot.answer_callback_query(c.id)
    if not user:
        return
    link = referral_link(uid)
    share_text = (
        "🔥 Я только что оценил(-а) себя в MoggVinchik!\n\n"
        "Честная оценка внешности, без прикрас 👀\n"
        f"Попробуй тоже: {link}"
    )
    bot.send_message(uid, f"📤 Вот текст, который можно переслать друзьям или в сторис:\n\n{share_text}")


# =========================================================
# MESSAGES
# =========================================================

def show_messages(m):
    uid = m.chat.id
    messages = get_unread_messages(uid)
    if not messages:
        bot.send_message(uid, "📬 Пока новых писем нет\nКогда кто-то напишет — сразу увидишь 💌", reply_markup=main_menu())
        return
    text = f"💌 *У тебя {len(messages)} новых писем*\n━━━━━━━━━━━━━━━\nНажми ниже, чтобы прочитать все"
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("📬 Прочитать письма"), KeyboardButton("⬅️ Назад"))
    bot.send_message(uid, text, parse_mode="Markdown", reply_markup=kb)


def read_messages(m):
    uid = m.chat.id
    messages = get_unread_messages(uid)
    if not messages:
        bot.send_message(uid, "📬 Новых писем больше нет", reply_markup=main_menu())
        return

    for msg in messages:
        kb = letter_reply_kb(msg["from_user"])
        if msg["message_type"] == "text":
            bot.send_message(uid, f"💌 *Тебе написали:*\n\n{msg['content']}", reply_markup=kb, parse_mode="Markdown")
        elif msg["message_type"] == "voice":
            bot.send_voice(uid, msg["file_id"], caption="🎤 Тебе прислали голосовое письмо", reply_markup=kb)
        elif msg["message_type"] == "circle":
            bot.send_video_note(uid, msg["file_id"])
            bot.send_message(uid, "🎙️ Тебе прислали кружок ⬆️", reply_markup=kb)
        mark_message_read(msg["id"])

    bot.send_message(uid, "✅ Все письма прочитаны", reply_markup=main_menu())


# =========================================================
# MATCHES — usernames shown here only, because a match = mutual consent
# =========================================================

def show_matches(m):
    uid = m.chat.id
    matches = get_matches(uid)
    if not matches:
        bot.send_message(uid, "❤️‍🔥 Пока мэтчей нет\nОценивай людей высоко — и взаимность обязательно появится 💫", reply_markup=main_menu())
        return
    text = "❤️‍🔥 *Твои мэтчи:*\n━━━━━━━━━━━━━━━\n"
    for match_id in matches:
        user = get_user(match_id)
        if user:
            username = user.get("username") or "пользователь"
            text += f"👥 @{username}\n"
    bot.send_message(uid, text, parse_mode="Markdown", reply_markup=main_menu())


# =========================================================
# TOP — anonymized: name + rank, no username. Premium gets a small boost.
# =========================================================

def show_top(m):
    uid = m.chat.id
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT u.name, u.gender, u.rank, u.is_premium, COUNT(r.id) AS count
        FROM users u
        LEFT JOIN ratings r ON r.to_user = u.id
        WHERE u.registered=TRUE AND u.is_banned=FALSE
        GROUP BY u.id
        ORDER BY u.is_premium DESC, count DESC
        LIMIT 20
    """)
    top_users = cur.fetchall()
    cur.close()
    conn.close()

    if not top_users:
        bot.send_message(uid, "🏆 Пока топ пуст — будь первым, кто начнёт оценивать!", reply_markup=main_menu())
        return

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    text = "🏆 *Топ Моггвинчик*\n━━━━━━━━━━━━━━━\n"
    for i, u in enumerate(top_users, 1):
        emoji = "👨" if u["gender"] == "male" else "👩"
        rank_emoji = RANK_EMOJIS.get(u["rank"], "🧑‍🎓")
        premium_mark = "💎" if u["is_premium"] else ""
        place = medals.get(i, f"{i}.")
        text += f"{place} {emoji} {u['name']} {rank_emoji}{premium_mark} — {u['count']} 🌟\n"
    bot.send_message(uid, text, parse_mode="Markdown", reply_markup=main_menu())


# =========================================================
# DELETE PROFILE
# =========================================================

def confirm_delete(m):
    uid = m.chat.id
    set_state(uid, action="confirm_delete")
    bot.send_message(uid, "⚠️ Ты уверен?\n\nНапиши «да» или «нет».")


# =========================================================
# MESSAGE / CONTACT-EXCHANGE CALLBACKS
# =========================================================

@bot.callback_query_handler(func=lambda c: c.data.startswith("msg_"))
def handle_msg(c):
    uid = c.from_user.id
    target_id = int(c.data.split("_")[1])
    target = get_user(target_id)
    if not target or not target.get("registered") or target.get("is_banned"):
        bot.answer_callback_query(c.id, "Пользователь недоступен")
        return
    set_state(uid, action="choosing_message_type", target_id=target_id)
    bot.answer_callback_query(c.id)
    bot.send_message(uid, "💌 Выбери тип письма:", reply_markup=message_type_kb(target_id))


@bot.callback_query_handler(func=lambda c: c.data.startswith("askuser_"))
def handle_askuser(c):
    uid = c.from_user.id
    target_id = int(c.data.split("_")[1])
    if target_id == uid:
        bot.answer_callback_query(c.id, "Нельзя познакомиться с собой 😄")
        return
    target = get_user(target_id)
    if not target or not target.get("registered") or target.get("is_banned"):
        bot.answer_callback_query(c.id, "Пользователь недоступен")
        return

    bot.answer_callback_query(c.id)
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Дать юз", callback_data=f"giveuser_{uid}"))
    try:
        bot.send_message(
            target_id,
            "🤝 *Кто-то хочет с тобой познакомиться!*\n\nПоказать свой Telegram username?",
            reply_markup=kb, parse_mode="Markdown",
        )
        bot.send_message(uid, "🤝 Запрос на знакомство отправлен!")
    except Exception:
        bot.send_message(uid, "❌ Не удалось отправить запрос.")


@bot.callback_query_handler(func=lambda c: c.data.startswith("msgtype_"))
def handle_msgtype(c):
    uid = c.from_user.id
    parts = c.data.split("_")
    msg_type = parts[1]
    target_id = int(parts[2])
    set_state(uid, action="sending_message", msg_type=msg_type, target_id=target_id)
    bot.answer_callback_query(c.id)
    if msg_type == "text":
        bot.send_message(uid, "📝 Напиши своё письмо:")
    elif msg_type == "voice":
        bot.send_message(uid, "🎤 Отправь голосовое сообщение:")
    elif msg_type == "circle":
        bot.send_message(uid, "🎙️ Отправь кружок:")


@bot.callback_query_handler(func=lambda c: c.data.startswith("giveuser_"))
def give_user_contact(c):
    user = get_user(c.from_user.id)
    requester_id = int(c.data.split("_")[1])
    if not user:
        bot.answer_callback_query(c.id, "Пользователь не найден")
        return
    username = user.get("username") or f"user_{user['id']}"
    try:
        bot.send_message(requester_id, f"✅ *Контакт:* @{username}", parse_mode="Markdown")
        bot.answer_callback_query(c.id, "✅ Контакт отправлен!")
    except Exception:
        bot.answer_callback_query(c.id, "❌ Не удалось отправить контакт")


# =========================================================
# REPORTING
# =========================================================

@bot.callback_query_handler(func=lambda c: c.data.startswith("report_"))
def handle_report(c):
    uid = c.from_user.id
    target_id = int(c.data.split("_")[1])
    if target_id == uid:
        bot.answer_callback_query(c.id, "Нельзя пожаловаться на себя")
        return
    bot.answer_callback_query(c.id)
    bot.send_message(uid, "🚩 Выбери причину жалобы:", reply_markup=report_reason_kb(target_id))


@bot.callback_query_handler(func=lambda c: c.data.startswith("reportreason_"))
def handle_report_reason(c):
    uid = c.from_user.id
    parts = c.data.split("_", 2)
    target_id = int(parts[1])
    reason = parts[2]
    if reason == "Другое":
        set_state(uid, action="reporting_other", target_id=target_id)
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "Опиши, в чём проблема:")
        return
    save_report(uid, target_id, reason)
    bot.answer_callback_query(c.id, "✅ Жалоба отправлена")
    bot.send_message(uid, "✅ Жалоба отправлена модераторам.", reply_markup=main_menu())
    notify_admins(f"🚩 *Новая жалоба*\n\nНа пользователя id: {target_id}\nПричина: {reason}")


@bot.callback_query_handler(func=lambda c: c.data.startswith("adminban_"))
def handle_admin_ban(c):
    if not is_admin(c.from_user.id):
        return
    parts = c.data.split("_")
    target_id = int(parts[1])
    report_id = int(parts[2])
    ban_user(target_id, "Забанен по жалобе модератором")
    close_report(report_id)
    bot.answer_callback_query(c.id, "Пользователь забанен")
    try:
        bot.edit_message_text(f"⛔ Пользователь id {target_id} забанен.\n\nЖалоба закрыта.", c.message.chat.id, c.message.message_id)
    except Exception:
        pass
    try:
        bot.send_message(target_id, "⛔ Твой аккаунт заблокирован модерацией по жалобе.")
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.data.startswith("admindismiss_"))
def handle_admin_dismiss(c):
    if not is_admin(c.from_user.id):
        return
    report_id = int(c.data.split("_")[1])
    close_report(report_id)
    bot.answer_callback_query(c.id, "Жалоба отклонена")
    try:
        bot.edit_message_text("✅ Жалоба отклонена.", c.message.chat.id, c.message.message_id)
    except Exception:
        pass


# =========================================================
# START POLLING
# =========================================================

try:
    BOT_USERNAME = bot.get_me().username
except Exception:
    BOT_USERNAME = None

print("🚀 БОТ ЗАПУЩЕН!")
bot.infinity_polling(skip_pending=True)
