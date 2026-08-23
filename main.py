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
import json
from datetime import datetime, timedelta

TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

ADMIN_IDS = [
    int(x)
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
]

MIN_AGE = 14

bot = telebot.TeleBot(TOKEN)


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
            rating FLOAT DEFAULT 0,
            daily_bonus_count INT DEFAULT 0,
            daily_bonus_date DATE,
            weekly_top INT DEFAULT 0,
            rank VARCHAR(50) DEFAULT 'Новичок',
            views_count INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            id SERIAL PRIMARY KEY,
            from_user BIGINT,
            to_user BIGINT,
            rating VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(from_user, to_user),
            FOREIGN KEY(from_user)
                REFERENCES users(id)
                ON DELETE CASCADE,
            FOREIGN KEY(to_user)
                REFERENCES users(id)
                ON DELETE CASCADE
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
            FOREIGN KEY(from_user)
                REFERENCES users(id)
                ON DELETE CASCADE,
            FOREIGN KEY(to_user)
                REFERENCES users(id)
                ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id SERIAL PRIMARY KEY,
            user1 BIGINT,
            user2 BIGINT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user1, user2),
            FOREIGN KEY(user1)
                REFERENCES users(id)
                ON DELETE CASCADE,
            FOREIGN KEY(user2)
                REFERENCES users(id)
                ON DELETE CASCADE
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
            FOREIGN KEY(from_user)
                REFERENCES users(id)
                ON DELETE CASCADE,
            FOREIGN KEY(target_user)
                REFERENCES users(id)
                ON DELETE CASCADE
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
    "Sub3",
    "Sub5",
    "LLTN",
    "LTN",
    "HLTN",
    "LMTN",
    "MTN",
    "HMTN",
    "LHTN",
    "HTN",
    "HHTN",
    "CHAD LITE",
    "TRUE ADAM"
]

FEMALE_SCALE = [
    "Sub3",
    "Sub5",
    "LLTB",
    "LTB",
    "HLTB",
    "LMTB",
    "MTB",
    "HMTB",
    "LHTB",
    "HTB",
    "HHTB",
    "Stacy",
    "True Eve"
]

SCALE_EMOJIS = {
    "Sub3": "😢",
    "Sub5": "😐",
    "LLTN": "😕",
    "LTN": "🙂",
    "HLTN": "😊",
    "LMTN": "😄",
    "MTN": "😍",
    "HMTN": "🔥",
    "LHTN": "💎",
    "HTN": "✨",
    "HHTN": "🌟",
    "CHAD LITE": "👑",
    "TRUE ADAM": "👨‍🦱",
    "LLTB": "😕",
    "LTB": "🙂",
    "HLTB": "😊",
    "LMTB": "😄",
    "MTB": "😍",
    "HMTB": "🔥",
    "LHTB": "💎",
    "HTB": "✨",
    "HHTB": "🌟",
    "Stacy": "👑",
    "True Eve": "👸"
}

HIGH_RATINGS = {
    "MTN", "HMTN", "LHTN", "HTN", "HHTN", "CHAD LITE", "TRUE ADAM",
    "MTB", "HMTB", "LHTB", "HTB", "HHTB", "Stacy", "True Eve"
}

RATING_MEANINGS = {
    "Sub3": "😢 **Очень низкая оценка** — есть много работы над собой. Начни с малого: спорт, уход, стиль.",
    "Sub5": "😐 **Ниже среднего** — потенциал есть, но нужно развивать.",
    "LLTN": "😕 **Low Low Tier Normie** — ты на старте. Первые шаги: измени причёску и добавь спорта.",
    "LTN": "🙂 **Low Tier Normie** — неплохо, но есть куда расти.",
    "HLTN": "😊 **High Low Tier Normie** — выше среднего. Добавь немного стиля в одежде.",
    "LMTN": "😄 **Low Mid Tier Normie** — ты уже в хорошей форме. Работай над осанкой.",
    "MTN": "😍 **Mid Tier Normie** — база хорошая. Теперь работай над деталями.",
    "HMTN": "🔥 **High Mid Tier Normie** — ты выше среднего. Отличная симметрия лица.",
    "LHTN": "💎 **Low High Tier Normie** — почти топ. Добавь уверенности.",
    "HTN": "✨ **High Tier Normie** — ты в топ-15%.",
    "HHTN": "🌟 **High High Tier Normie** — ты среди лучших.",
    "CHAD LITE": "👑 **Почти Чад** — у тебя мощный потенциал.",
    "TRUE ADAM": "👨‍🦱 **Идеал** — ты лучшее, что есть.",
    "LLTB": "😕 **Low Low Tier Beauty** — начни с малого.",
    "LTB": "🙂 **Low Tier Beauty** — ты красива, но не раскрыта.",
    "HLTB": "😊 **High Low Tier Beauty** — ты на подъёме.",
    "LMTB": "😄 **Low Mid Tier Beauty** — отличная база.",
    "MTB": "😍 **Mid Tier Beauty** — ты уже хороша.",
    "HMTB": "🔥 **High Mid Tier Beauty** — ты шикарна.",
    "LHTB": "💎 **Low High Tier Beauty** — почти идеал.",
    "HTB": "✨ **High Tier Beauty** — ты в топе.",
    "HHTB": "🌟 **High High Tier Beauty** — ты среди лучших.",
    "Stacy": "👑 **Stacy** — ты идеал женской красоты.",
    "True Eve": "👸 **True Eve** — абсолютная женственность."
}

RANK_EMOJIS = {
    "Новичок": "🧑‍🎓",
    "Любопытный": "👀",
    "Оценщик": "🔥",
    "Луксмаксер": "🏆",
    "Король": "👑",
    "Легенда": "💎"
}


def get_rank(user_data):
    user_id = user_data["id"]
    ratings_given = get_ratings_given(user_id)
    ratings_received = len(get_user_ratings(user_id))
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
    else:
        return "Новичок"


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


def get_scale(gender):
    if gender == "female":
        return FEMALE_SCALE
    return MALE_SCALE


def is_admin(user_id):
    return user_id in ADMIN_IDS


# =========================================================
# KEYBOARDS
# =========================================================

def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        KeyboardButton("🎲 Оценить"),
        KeyboardButton("💌 Письма")
    )
    kb.add(
        KeyboardButton("👤 Профиль"),
        KeyboardButton("💕 Мои оценки")
    )
    kb.add(
        KeyboardButton("❤️‍🔥 Мэтчи"),
        KeyboardButton("🏆 Топ")
    )
    kb.add(
        KeyboardButton("🗑️ Удалить профиль")
    )
    return kb


def rating_kb(gender, target_id):
    kb = InlineKeyboardMarkup(row_width=2)

    # Кнопки "Письмо" и "Познакомиться"
    kb.row(
        InlineKeyboardButton("💌 Письмо", callback_data=f"msg_{target_id}"),
        InlineKeyboardButton("🤝 Познакомиться", callback_data=f"askuser_{target_id}")
    )

    scale = get_scale(gender)

    # Оценки по 2 в ряд
    for i in range(0, len(scale), 2):
        pair = scale[i:i+2]
        kb.row(*[
            InlineKeyboardButton(
                f"{SCALE_EMOJIS.get(r, '⭐')} {r}",
                callback_data=f"rate_{target_id}_{r}"
            )
            for r in pair
        ])

    # Кнопки "Пропустить" и "Жалоба"
    kb.row(
        InlineKeyboardButton("⏭️ Пропустить", callback_data=f"skip_{target_id}"),
        InlineKeyboardButton("🚩 Жалоба", callback_data=f"report_{target_id}")
    )

    return kb


def gender_kb():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("💪 Я парень", callback_data="gender_male"),
        InlineKeyboardButton("🌸 Я девушка", callback_data="gender_female")
    )
    return kb


def rated_profile_kb(target_id):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(
        InlineKeyboardButton("⭐ Оценить в ответ", callback_data=f"replyrate_{target_id}"),
        InlineKeyboardButton("⏭️ Пропустить", callback_data=f"replyskip_{target_id}")
    )
    kb.row(
        InlineKeyboardButton("💌 Письмо", callback_data=f"msg_{target_id}"),
        InlineKeyboardButton("🤝 Познакомиться", callback_data=f"askuser_{target_id}")
    )
    kb.add(InlineKeyboardButton("🚩 Пожаловаться", callback_data=f"report_{target_id}"))
    return kb


def reply_rating_kb(gender, target_id):
    kb = InlineKeyboardMarkup(row_width=2)
    scale = get_scale(gender)
    for i in range(0, len(scale), 2):
        pair = scale[i:i+2]
        kb.row(*[
            InlineKeyboardButton(
                f"{SCALE_EMOJIS.get(r, '⭐')} {r}",
                callback_data=f"rate_{target_id}_{r}"
            )
            for r in pair
        ])
    kb.add(InlineKeyboardButton("⏭️ Пропустить", callback_data=f"replyskip_{target_id}"))
    return kb


def message_type_kb(target_id):
    kb = InlineKeyboardMarkup(row_width=3)
    kb.add(
        InlineKeyboardButton("📝 Текст", callback_data=f"msgtype_text_{target_id}"),
        InlineKeyboardButton("🎤 Голос", callback_data=f"msgtype_voice_{target_id}"),
        InlineKeyboardButton("🎙️ Кружок", callback_data=f"msgtype_circle_{target_id}")
    )
    return kb


def user_view_kb(user_id):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("👀 Показать анкету", callback_data=f"showrated_{user_id}"))
    return kb


def report_reason_kb(target_id):
    kb = InlineKeyboardMarkup(row_width=1)
    reasons = [
        "Неприемлемое фото",
        "Оскорбления / харассмент",
        "Фейковый профиль",
        "Спам / реклама",
        "Другое"
    ]
    for reason in reasons:
        kb.add(InlineKeyboardButton(reason, callback_data=f"reportreason_{target_id}_{reason}"))
    return kb


# =========================================================
# STATES
# =========================================================

user_states = {}
skipped_profiles = {}

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

def create_user(user_id, username, name):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO users (id, username, name)
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
    """, (user_id, username, name))
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

def get_random_user(exclude_user_id, extra_exclude=None):
    extra_exclude = extra_exclude or []
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT *
        FROM users
        WHERE id != %s
          AND registered = TRUE
          AND is_banned = FALSE
          AND id NOT IN (SELECT to_user FROM ratings WHERE from_user = %s)
          AND NOT (id = ANY(%s))
        ORDER BY RANDOM()
        LIMIT 1
    """, (exclude_user_id, exclude_user_id, extra_exclude))
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
# RATINGS
# =========================================================

def save_rating(from_user, to_user, rating):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO ratings (from_user, to_user, rating)
        VALUES (%s, %s, %s)
        ON CONFLICT (from_user, to_user)
        DO UPDATE SET rating = EXCLUDED.rating, created_at = CURRENT_TIMESTAMP
    """, (from_user, to_user, rating))
    conn.commit()
    cur.close()
    conn.close()
    check_match(from_user, to_user, rating)
    notify_about_rating(from_user, to_user, rating)
    update_daily_bonus(from_user)

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
    cur.execute("""
        INSERT INTO matches (user1, user2)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
    """, (min(from_user, to_user), max(from_user, to_user)))
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
        bot.send_message(from_user, f"❤️‍🔥 *Лукмэтч!* ❤️‍🔥\n\nВы понравились друг другу!\nВторой пользователь: @{username2}", parse_mode="Markdown")
    except Exception:
        pass
    try:
        bot.send_message(to_user, f"❤️‍🔥 *Лукмэтч!* ❤️‍🔥\n\nВы понравились друг другу!\nВторой пользователь: @{username1}", parse_mode="Markdown")
    except Exception:
        pass

def notify_about_rating(from_user, to_user, rating):
    if from_user == to_user:
        return
    emoji = SCALE_EMOJIS.get(rating, "⭐")
    text = f"{emoji} *Тебя оценили!*\n\nОценка: *{rating}*\n\n👀 Показать анкету этого человека?"
    try:
        bot.send_message(to_user, text, reply_markup=user_view_kb(from_user), parse_mode="Markdown")
    except Exception:
        pass

def update_daily_bonus(user_id):
    conn = get_db()
    cur = conn.cursor()
    today = datetime.now().date()
    cur.execute("SELECT daily_bonus_date, daily_bonus_count, rating FROM users WHERE id=%s", (user_id,))
    row = cur.fetchone()
    if row and row[0] == today:
        count = row[1] + 1
        update_user(user_id, daily_bonus_date=today, daily_bonus_count=count)
        if count == 5:
            current_rating = float(row[2] or 0)
            update_user(user_id, rating=round(current_rating + 0.5, 2), weekly_top=1)
            try:
                bot.send_message(user_id, "🏆 *Ежедневный бонус активирован!*\n\nТы поставил уже 5 оценок сегодня 🔥\nРейтинг +0.5 и ты в топе недели!", parse_mode="Markdown")
            except Exception:
                pass
    else:
        update_user(user_id, daily_bonus_date=today, daily_bonus_count=1)
    cur.close()
    conn.close()

def get_latest_rating(from_user, to_user):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT rating FROM ratings WHERE from_user=%s AND to_user=%s LIMIT 1", (from_user, to_user))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result

def get_user_ratings(user_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT r.rating, r.created_at FROM ratings r WHERE r.to_user=%s ORDER BY r.created_at DESC", (user_id,))
    ratings = cur.fetchall()
    cur.close()
    conn.close()
    return ratings


# =========================================================
# MESSAGES
# =========================================================

def save_message(from_user, to_user, content, msg_type, file_id=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO messages (from_user, to_user, content, message_type, file_id)
        VALUES (%s, %s, %s, %s, %s)
    """, (from_user, to_user, content, msg_type, file_id))
    conn.commit()
    cur.close()
    conn.close()

def get_unread_messages(user_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT m.id, m.from_user, m.content, m.message_type, m.file_id, u.username
        FROM messages m
        JOIN users u ON m.from_user = u.id
        WHERE m.to_user=%s AND m.read=FALSE
        ORDER BY m.created_at DESC
    """, (user_id,))
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
    cur.execute("""
        SELECT CASE WHEN user1=%s THEN user2 ELSE user1 END AS matched_user
        FROM matches
        WHERE user1=%s OR user2=%s
    """, (user_id, user_id, user_id))
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
    cur.execute("""
        INSERT INTO reports (from_user, target_user, reason)
        VALUES (%s, %s, %s)
        RETURNING id
    """, (from_user, target_user, reason))
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
        FROM reports rp
        JOIN users u ON rp.target_user = u.id
        WHERE rp.status='open'
        ORDER BY rp.created_at DESC
        LIMIT 20
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
    rank = user.get("rank", "Новичок")
    rank_emoji = RANK_EMOJIS.get(rank, "🧑‍🎓")
    bio = (user.get("bio") or "").strip()
    bio_line = f"📝 _{bio}_" if bio else "📝 _без описания_"
    text = (
        f"{rank_emoji} *{rank}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 *Анкета* · {user['age']} лет\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📏 {user['height']} см   "
        f"⚖️ {user['weight']} кг\n"
        f"🏙️ {user['city']}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{bio_line}\n"
        f"━━━━━━━━━━━━━━━"
    )
    if rating:
        emoji = SCALE_EMOJIS.get(rating, "⭐")
        text += f"\n\n{emoji} *Оценка: {rating}*"
    return text

def show_rating_card(uid, target):
    rank = target.get("rank", "Новичок")
    rank_emoji = RANK_EMOJIS.get(rank, "🧑‍🎓")
    bio = (target.get("bio") or "").strip()
    bio_line = f"📝 _{bio}_" if bio else "📝 _без описания_"
    text = (
        f"{rank_emoji} *{rank}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 *Анкета* · {target['age']} лет\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📏 {target['height']} см   "
        f"⚖️ {target['weight']} кг\n"
        f"🏙️ {target['city']}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{bio_line}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💖 *Оцени внешность:*"
    )
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
        create_user(uid, m.from_user.username or f"user_{uid}", m.from_user.first_name)
        bot.send_message(
            uid,
            "💖 *Добро пожаловать в Моггвинчик!* 💖\n\n"
            "Здесь тебя честно оценят по внешности — "
            "без фильтров и лишней воды.\n\n"
            "📸 Заполни короткую анкету и начинай получать оценки "
            "и мэтчи.\n\n"
            "🚀 Сервис доступен с 14 лет.\n\n"
            "Для начала напиши свой *возраст* числом 👇",
            parse_mode="Markdown"
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
            InlineKeyboardButton("✅ Отклонить", callback_data=f"admindismiss_{report['id']}")
        )
        bot.send_message(uid, f"🚩 Жалоба #{report['id']}\nНа: @{report['target_username']} (id {report['target_user']})\nПричина: {report['reason']}", reply_markup=kb)

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
    bot.send_message(uid, "📊 **Рассылка завершена**\n\n👥 Всего: {total}\n✅ Доставлено: {sent}\n❌ Ошибок: {failed}", parse_mode="Markdown")


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

    # -----------------------------------------------------
    # REGISTRATION
    # -----------------------------------------------------
    if not user.get("age") and m.text.isdigit():
        age = int(m.text)
        if age < MIN_AGE:
            bot.send_message(uid, f"❌ Сервис доступен только пользователям {MIN_AGE}+.")
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
        if text_lower in ("пропустить", "skip", "-", "нет", "не хочу"):
            bio_value = ""
        else:
            bio_value = (m.text or "")[:200]
        update_user(uid, bio=bio_value)
        bot.send_message(uid, "📸 Отлично! Теперь отправь свою фотографию\n(лучше селфи или портрет в хорошем качестве)", parse_mode="Markdown")
        return

    # -----------------------------------------------------
    # REPORT OTHER
    # -----------------------------------------------------
    if state.get("action") == "reporting_other":
        target_id = state.get("target_id")
        save_report(uid, target_id, m.text[:300])
        bot.send_message(uid, "✅ Жалоба отправлена модераторам.", reply_markup=main_menu())
        notify_admins(f"🚩 Новая жалоба\n\nНа пользователя id: {target_id}\nПричина: {m.text[:300]}")
        clear_state(uid)
        return

    # -----------------------------------------------------
    # SENDING TEXT MESSAGE
    # -----------------------------------------------------
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

    # -----------------------------------------------------
    # DELETE CONFIRMATION
    # -----------------------------------------------------
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

    # -----------------------------------------------------
    # MAIN MENU
    # -----------------------------------------------------
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
    elif m.text == "🗑️ Удалить профиль":
        confirm_delete(m)
    elif m.text == "📬 Прочитать письма":
        read_messages(m)
    elif m.text == "⬅️ Назад":
        bot.send_message(uid, "Главное меню", reply_markup=main_menu())


# =========================================================
# PHOTO
# =========================================================

@bot.message_handler(content_types=["photo"])
def handle_photo(m):
    uid = m.chat.id
    user = get_user(uid)
    if user and user.get("city") and user.get("bio") is not None and not user.get("photo_id"):
        update_user(uid, photo_id=m.photo[-1].file_id)
        bot.send_message(uid, "👤 Последний шаг — выбери свой пол 👇", reply_markup=gender_kb())


# =========================================================
# VOICE
# =========================================================

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


# =========================================================
# VIDEO NOTE
# =========================================================

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
        update_user(uid, gender=gender, registered=True)

        try:
            bot.delete_message(c.message.chat.id, c.message.message_id)
        except Exception:
            try:
                bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
            except Exception:
                pass

        bot.send_message(
            uid,
            "🎉 *ГОТОВО!*\n\n"
            "Твой профиль создан и уже доступен для оценок ✨\n\n"
            "Жми «🎲 Оценить» и начинай 👇",
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )

    except Exception as e:
        print(f"[set_gender error] uid={uid}: {e}")
        try:
            bot.send_message(
                uid,
                "⚠️ Произошла ошибка при сохранении профиля.\n"
                "Попробуй ещё раз нажать кнопку или напиши /start"
            )
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

    # Обновляем счётчик просмотров
    update_user(uid, views_count=user.get("views_count", 0) + 1)

    # Обновляем звание
    rank = get_rank(user)
    if rank != user.get("rank"):
        update_user(uid, rank=rank)

    # Пропущенные анкеты
    skipped = skipped_profiles.get(uid, set())
    target = get_random_user(uid, extra_exclude=list(skipped))

    if not target:
        if skipped:
            skipped_profiles[uid] = set()
            target = get_random_user(uid)

        if not target:
            bot.send_message(
                uid,
                "😢 Пока некого оценивать — загляни чуть позже.\n\n"
                "👥 А пока можешь позвать друзей в бота!\n"
                "Чем больше людей — тем интереснее 💫",
                reply_markup=main_menu()
            )
            return

    show_rating_card(uid, target)


# =========================================================
# RATING CALLBACK
# =========================================================

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


# =========================================================
# SHOW RATED PROFILE
# =========================================================

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

    rating = rating_data["rating"]
    bot.answer_callback_query(c.id)

    try:
        bot.delete_message(c.message.chat.id, c.message.message_id)
    except Exception:
        pass

    show_rated_profile(uid, target, rating)


# =========================================================
# DON'T SHOW RATED PROFILE
# =========================================================

@bot.callback_query_handler(func=lambda c: c.data.startswith("replyskip_"))
def handle_reply_skip(c):
    bot.answer_callback_query(c.id, "⏭️ Пропущено")
    try:
        bot.delete_message(c.message.chat.id, c.message.message_id)
    except Exception:
        pass


# =========================================================
# REPLY RATE
# =========================================================

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


# =========================================================
# SKIP NORMAL PROFILE
# =========================================================

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

    text = (
        f"{emoji} *Моя анкета*\n"
        f"{rank_emoji} *Звание:* {rank}\n\n"
        f"📅 {user['age']} лет\n"
        f"📏 {user['height']} см\n"
        f"⚖️ {user['weight']} кг\n"
        f"🏙️ {user['city']}\n"
        f"{bio_line}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"⭐ Рейтинг: {user['rating']}\n"
    )
    if place:
        text += f"🏆 Место в топе: {place} из {total}\n"
    daily_bonus = user.get("daily_bonus_count", 0)
    if daily_bonus > 0:
        text += f"🔥 Сегодня оценок: {daily_bonus}/5 (бонус)\n"

    if user.get("photo_id"):
        bot.send_photo(uid, user["photo_id"], caption=text, reply_markup=main_menu(), parse_mode="Markdown")
    else:
        bot.send_message(uid, text, reply_markup=main_menu(), parse_mode="Markdown")


# =========================================================
# MY RATINGS
# =========================================================

def show_ratings(m):
    uid = m.chat.id
    ratings = get_user_ratings(uid)
    if not ratings:
        bot.send_message(uid, "📊 Пока никто тебя не оценил 🥺\nОценивай других — и оценки скоро появятся!", reply_markup=main_menu())
        return

    text = "💕 *Твои оценки:*\n\n"
    for rating_data in ratings:
        rating = rating_data["rating"]
        emoji = SCALE_EMOJIS.get(rating, "⭐")
        text += f"{emoji} **{rating}**\n"

    bot.send_message(uid, text, parse_mode="Markdown", reply_markup=main_menu())


# =========================================================
# MESSAGES
# =========================================================

def show_messages(m):
    uid = m.chat.id
    messages = get_unread_messages(uid)
    if not messages:
        bot.send_message(uid, "📬 Пока новых писем нет\nКогда кто-то напишет — сразу увидишь 💌", reply_markup=main_menu())
        return

    text = f"💌 *У тебя {len(messages)} новых писем:*\n\n"
    for msg in messages:
        text += f"📨 Новое сообщение\n"

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
        if msg["message_type"] == "text":
            bot.send_message(uid, f"💌 *Новое письмо:*\n\n{msg['content']}", parse_mode="Markdown")
        elif msg["message_type"] == "voice":
            bot.send_voice(uid, msg["file_id"], caption="🎤 Новое голосовое сообщение")
        elif msg["message_type"] == "circle":
            bot.send_video_note(uid, msg["file_id"])
        mark_message_read(msg["id"])

    bot.send_message(uid, "✅ Все письма прочитаны", reply_markup=main_menu())


# =========================================================
# MATCHES
# =========================================================

def show_matches(m):
    uid = m.chat.id
    matches = get_matches(uid)
    if not matches:
        bot.send_message(uid, "❤️‍🔥 Пока мэтчей нет\nОценивай людей высоко — и взаимность обязательно появится 💫", reply_markup=main_menu())
        return

    text = "❤️‍🔥 *Твои мэтчи:*\n\n"
    for match_id in matches:
        user = get_user(match_id)
        if user:
            username = user.get("username", "пользователь")
            text += f"👥 @{username}\n"

    bot.send_message(uid, text, parse_mode="Markdown", reply_markup=main_menu())


# =========================================================
# TOP
# =========================================================

def show_top(m):
    uid = m.chat.id
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT u.username, u.gender, COUNT(r.id) AS count, u.rank
        FROM users u
        LEFT JOIN ratings r ON r.to_user = u.id
        WHERE u.registered=TRUE AND u.is_banned=FALSE
        GROUP BY u.id
        ORDER BY count DESC
        LIMIT 20
    """)
    top_users = cur.fetchall()
    cur.close()
    conn.close()

    if not top_users:
        bot.send_message(uid, "🏆 Пока топ пуст — будь первым, кто начнёт оценивать!", reply_markup=main_menu())
        return

    text = "🏆 *Топ Моггвинчик:*\n\n"
    for i, user in enumerate(top_users, 1):
        emoji = "👨" if user["gender"] == "male" else "👩"
        rank_emoji = RANK_EMOJIS.get(user["rank"], "🧑‍🎓")
        text += f"{i}. {emoji} @{user['username']} {rank_emoji} — {user['count']} 🌟\n"

    bot.send_message(uid, text, parse_mode="Markdown", reply_markup=main_menu())


# =========================================================
# DELETE PROFILE
# =========================================================

def confirm_delete(m):
    uid = m.chat.id
    set_state(uid, action="confirm_delete")
    bot.send_message(uid, "⚠️ Ты уверен?\n\nНапиши «да» или «нет».")


# =========================================================
# MESSAGE CALLBACKS
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

    user = get_user(uid)
    bot.answer_callback_query(c.id)
    requester_username = user.get("username") or f"user_{uid}"
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Дать юз", callback_data=f"giveuser_{uid}"))

    try:
        bot.send_message(target_id, "🤝 **Кто-то хочет с тобой познакомиться!**\n\nПоказать свой Telegram username?", reply_markup=kb, parse_mode="Markdown")
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
        bot.send_message(requester_id, f"✅ **Контакт:** @{username}", parse_mode="Markdown")
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
    notify_admins(f"🚩 **Новая жалоба**\n\nНа пользователя id: {target_id}\nПричина: {reason}")


# =========================================================
# ADMIN REPORT CALLBACKS
# =========================================================

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
# START
# =========================================================

print("🚀 БОТ ЗАПУЩЕН!")

bot.infinity_polling(skip_pending=True)
