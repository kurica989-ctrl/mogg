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

TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Comma-separated telegram user IDs of moderators/admins, e.g. "123456,789012"
ADMIN_IDS = [
    int(x) for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
]

MIN_AGE = 18

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

    conn.commit()
    cur.close()
    conn.close()


init_db()


# =========================================================
# RATING SCALE
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
    "MTN",
    "HMTN",
    "LHTN",
    "HTN",
    "HHTN",
    "CHAD LITE",
    "TRUE ADAM",

    "MTB",
    "HMTB",
    "LHTB",
    "HTB",
    "HHTB",
    "Stacy",
    "True Eve"
}


def get_scale(gender):
    return FEMALE_SCALE if gender == "female" else MALE_SCALE


def is_admin(user_id):
    return user_id in ADMIN_IDS


# =========================================================
# KEYBOARDS
# =========================================================

def main_menu():
    kb = ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2
    )

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

    kb.row(
        InlineKeyboardButton(
            "💌 Письмо",
            callback_data=f"msg_{target_id}"
        ),
        InlineKeyboardButton(
            "🤝 Познакомиться",
            callback_data=f"askuser_{target_id}"
        )
    )

    scale = get_scale(gender)

    for i in range(0, len(scale), 2):
        pair = scale[i:i + 2]

        kb.row(*[
            InlineKeyboardButton(
                f"{SCALE_EMOJIS.get(r, '⭐')} {r}",
                callback_data=f"rate_{target_id}_{r}"
            )
            for r in pair
        ])

    kb.row(
        InlineKeyboardButton(
            "⏭️ Пропустить",
            callback_data=f"skip_{target_id}"
        ),
        InlineKeyboardButton(
            "🚩 Жалоба",
            callback_data=f"report_{target_id}"
        )
    )

    return kb


def gender_kb():
    kb = InlineKeyboardMarkup(row_width=2)

    kb.add(
        InlineKeyboardButton(
            "💪 ПАРЕНЬ",
            callback_data="gender_male"
        )
    )

    kb.add(
        InlineKeyboardButton(
            "🌸 ДЕВУШКА",
            callback_data="gender_female"
        )
    )

    return kb


# Клавиатура уже открытой анкеты.
# Username здесь намеренно НЕ показываем.
def user_view_kb(user_id):
    kb = InlineKeyboardMarkup(row_width=1)

    kb.add(
        InlineKeyboardButton(
            "💌 Письмо",
            callback_data=f"msg_{user_id}"
        )
    )

    kb.add(
        InlineKeyboardButton(
            "🤝 Познакомиться",
            callback_data=f"askuser_{user_id}"
        )
    )

    kb.add(
        InlineKeyboardButton(
            "🚩 Пожаловаться",
            callback_data=f"report_{user_id}"
        )
    )

    return kb


def message_type_kb(target_id):
    kb = InlineKeyboardMarkup(row_width=3)

    kb.add(
        InlineKeyboardButton(
            "📝 Текст",
            callback_data=f"msgtype_text_{target_id}"
        ),
        InlineKeyboardButton(
            "🎤 Голос",
            callback_data=f"msgtype_voice_{target_id}"
        ),
        InlineKeyboardButton(
            "🎙️ Кружок",
            callback_data=f"msgtype_circle_{target_id}"
        )
    )

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
        kb.add(
            InlineKeyboardButton(
                reason,
                callback_data=f"reportreason_{target_id}_{reason}"
            )
        )

    return kb


# =========================================================
# USER STATE
# =========================================================

user_states = {}

# user_id -> set(profile_ids)
skipped_profiles = {}


def set_state(user_id, **state):
    user_states[user_id] = state


def get_state(user_id):
    return user_states.get(user_id, {})


def clear_state(user_id):
    user_states.pop(user_id, None)


# =========================================================
# DATABASE HELPERS
# =========================================================

def get_user(user_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(
        "SELECT * FROM users WHERE id=%s",
        (user_id,)
    )

    user = cur.fetchone()

    cur.close()
    conn.close()

    return user


def create_user(user_id, username, name):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO users (id, username, name)
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (user_id, username, name)
    )

    conn.commit()
    cur.close()
    conn.close()


def update_user(user_id, **kwargs):
    if not kwargs:
        return

    conn = get_db()
    cur = conn.cursor()

    set_clause = ", ".join(
        [f"{k}=%s" for k in kwargs.keys()]
    )

    values = list(kwargs.values()) + [user_id]

    cur.execute(
        f"UPDATE users SET {set_clause} WHERE id=%s",
        values
    )

    conn.commit()
    cur.close()
    conn.close()


def delete_user(user_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM users WHERE id=%s",
        (user_id,)
    )

    conn.commit()

    cur.close()
    conn.close()

    skipped_profiles.pop(user_id, None)
    user_states.pop(user_id, None)


def ban_user(user_id, reason=""):
    update_user(
        user_id,
        is_banned=True,
        ban_reason=reason
    )


def unban_user(user_id):
    update_user(
        user_id,
        is_banned=False,
        ban_reason=None
    )


# =========================================================
# RANDOM PROFILES
# =========================================================

def get_random_user(
    exclude_user_id,
    extra_exclude=None
):
    extra_exclude = extra_exclude or []

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(
        """
        SELECT *
        FROM users
        WHERE id != %s
          AND registered = TRUE
          AND is_banned = FALSE
          AND id NOT IN (
              SELECT to_user
              FROM ratings
              WHERE from_user = %s
          )
          AND NOT (id = ANY(%s))
        ORDER BY RANDOM()
        LIMIT 1
        """,
        (
            exclude_user_id,
            exclude_user_id,
            extra_exclude
        )
    )

    user = cur.fetchone()

    cur.close()
    conn.close()

    return user


def has_rated(from_user, to_user):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT 1
        FROM ratings
        WHERE from_user=%s
          AND to_user=%s
        """,
        (from_user, to_user)
    )

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

    cur.execute(
        """
        INSERT INTO ratings (
            from_user,
            to_user,
            rating
        )
        VALUES (%s, %s, %s)

        ON CONFLICT (from_user, to_user)
        DO UPDATE SET
            rating = EXCLUDED.rating,
            created_at = CURRENT_TIMESTAMP
        """,
        (
            from_user,
            to_user,
            rating
        )
    )

    conn.commit()

    cur.close()
    conn.close()

    check_match(
        from_user,
        to_user,
        rating
    )


def check_match(from_user, to_user, new_rating):
    if new_rating not in HIGH_RATINGS:
        return

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(
        """
        SELECT rating
        FROM ratings
        WHERE from_user=%s
          AND to_user=%s
        """,
        (
            to_user,
            from_user
        )
    )

    opposite = cur.fetchone()

    if opposite and opposite["rating"] in HIGH_RATINGS:
        cur.execute(
            """
            INSERT INTO matches (user1, user2)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                min(from_user, to_user),
                max(from_user, to_user)
            )
        )

        conn.commit()

        user1 = get_user(from_user)
        user2 = get_user(to_user)

        if user1 and user2:
            username1 = user1.get("username") or "пользователь"
            username2 = user2.get("username") or "пользователь"

            try:
                bot.send_message(
                    from_user,
                    f"❤️‍🔥 **ЛУКМЭТЧ!** ❤️‍🔥\n\n"
                    f"Ты и @{username2} лайкнули друг друга!",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

            try:
                bot.send_message(
                    to_user,
                    f"❤️‍🔥 **ЛУКМЭТЧ!** ❤️‍🔥\n\n"
                    f"Ты и @{username1} лайкнули друг друга!",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    cur.close()
    conn.close()


def get_user_ratings(user_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(
        """
        SELECT
            r.rating,
            u.username
        FROM ratings r
        JOIN users u
          ON r.from_user = u.id
        WHERE r.to_user=%s
        ORDER BY r.created_at DESC
        """,
        (user_id,)
    )

    ratings = cur.fetchall()

    cur.close()
    conn.close()

    return ratings


# =========================================================
# MESSAGES
# =========================================================

def save_message(
    from_user,
    to_user,
    content,
    msg_type,
    file_id=None
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO messages (
            from_user,
            to_user,
            content,
            message_type,
            file_id
        )
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            from_user,
            to_user,
            content,
            msg_type,
            file_id
        )
    )

    conn.commit()

    cur.close()
    conn.close()


def get_unread_messages(user_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Здесь намеренно берём name, а не username.
    cur.execute(
        """
        SELECT
            m.id,
            m.from_user,
            m.content,
            m.message_type,
            m.file_id,
            u.name AS sender_name
        FROM messages m
        JOIN users u
          ON m.from_user = u.id
        WHERE m.to_user=%s
          AND m.read=FALSE
        ORDER BY m.created_at DESC
        """,
        (user_id,)
    )

    messages = cur.fetchall()

    cur.close()
    conn.close()

    return messages


def mark_message_read(msg_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "UPDATE messages SET read=TRUE WHERE id=%s",
        (msg_id,)
    )

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
        """
        SELECT
            CASE
                WHEN user1=%s THEN user2
                ELSE user1
            END AS matched_user
        FROM matches
        WHERE user1=%s
           OR user2=%s
        """,
        (
            user_id,
            user_id,
            user_id
        )
    )

    matches = cur.fetchall()

    cur.close()
    conn.close()

    return [
        m["matched_user"]
        for m in matches
    ]


# =========================================================
# REPORTS
# =========================================================

def save_report(
    from_user,
    target_user,
    reason
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO reports (
            from_user,
            target_user,
            reason
        )
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (
            from_user,
            target_user,
            reason
        )
    )

    report_id = cur.fetchone()[0]

    conn.commit()

    cur.close()
    conn.close()

    return report_id


def get_open_reports():
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(
        """
        SELECT
            rp.id,
            rp.from_user,
            rp.target_user,
            rp.reason,
            rp.created_at,
            u.username AS target_username
        FROM reports rp
        JOIN users u
          ON rp.target_user = u.id
        WHERE rp.status = 'open'
        ORDER BY rp.created_at DESC
        LIMIT 20
        """
    )

    reports = cur.fetchall()

    cur.close()
    conn.close()

    return reports


def close_report(report_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "UPDATE reports SET status='closed' WHERE id=%s",
        (report_id,)
    )

    conn.commit()

    cur.close()
    conn.close()


def notify_admins(
    text,
    reply_markup=None
):
    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(
                admin_id,
                text,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        except Exception:
            pass


# =========================================================
# REGISTRATION
# =========================================================

@bot.message_handler(commands=["start"])
def start(m):
    uid = m.chat.id

    user = get_user(uid)

    if not user:
        create_user(
            uid,
            m.from_user.username or f"user_{uid}",
            m.from_user.first_name
        )

        bot.send_message(
            uid,
            f"💖 **ДОБРО ПОЖАЛОВАТЬ В MOGGVINCHIK!** 💖\n\n"
            f"Сервис доступен только совершеннолетним "
            f"пользователям ({MIN_AGE}+).\n\n"
            f"Сколько тебе лет?",
            parse_mode="Markdown"
        )

        return

    if user.get("is_banned"):
        bot.send_message(
            uid,
            "⛔ Твой аккаунт заблокирован модерацией."
            + (
                f"\nПричина: {user.get('ban_reason')}"
                if user.get("ban_reason")
                else ""
            )
        )
        return

    if user.get("registered"):
        bot.send_message(
            uid,
            f"✨ С возвращением, @{user['username']}!",
            reply_markup=main_menu()
        )
    else:
        bot.send_message(
            uid,
            "Продолжим регистрацию — просто ответь "
            "на следующий вопрос."
        )


# =========================================================
# ADMIN
# =========================================================

@bot.message_handler(commands=["admin"])
def admin_panel(m):
    uid = m.chat.id

    if not is_admin(uid):
        return

    reports = get_open_reports()

    if not reports:
        bot.send_message(
            uid,
            "✅ Открытых жалоб нет."
        )
        return

    for report in reports:
        kb = InlineKeyboardMarkup(row_width=2)

        kb.add(
            InlineKeyboardButton(
                "⛔ Забанить",
                callback_data=(
                    f"adminban_"
                    f"{report['target_user']}_"
                    f"{report['id']}"
                )
            ),
            InlineKeyboardButton(
                "✅ Отклонить",
                callback_data=(
                    f"admindismiss_{report['id']}"
                )
            )
        )

        bot.send_message(
            uid,
            f"🚩 Жалоба #{report['id']}\n"
            f"На: @{report['target_username']} "
            f"(id {report['target_user']})\n"
            f"Причина: {report['reason']}",
            reply_markup=kb
        )


@bot.message_handler(commands=["ban"])
def cmd_ban(m):
    uid = m.chat.id

    if not is_admin(uid):
        return

    parts = m.text.split(
        maxsplit=2
    )

    if len(parts) < 2 or not parts[1].isdigit():
        bot.send_message(
            uid,
            "Использование: /ban <user_id> [причина]"
        )
        return

    target_id = int(parts[1])
    reason = (
        parts[2]
        if len(parts) > 2
        else ""
    )

    ban_user(
        target_id,
        reason
    )

    bot.send_message(
        uid,
        f"⛔ Пользователь {target_id} забанен."
    )

    try:
        bot.send_message(
            target_id,
            "⛔ Твой аккаунт заблокирован модерацией."
            + (
                f"\nПричина: {reason}"
                if reason
                else ""
            )
        )
    except Exception:
        pass


@bot.message_handler(commands=["unban"])
def cmd_unban(m):
    uid = m.chat.id

    if not is_admin(uid):
        return

    parts = m.text.split(
        maxsplit=1
    )

    if len(parts) < 2 or not parts[1].isdigit():
        bot.send_message(
            uid,
            "Использование: /unban <user_id>"
        )
        return

    target_id = int(parts[1])

    unban_user(target_id)

    bot.send_message(
        uid,
        f"✅ Пользователь {target_id} разбанен."
    )


# =========================================================
# TEXT HANDLER
# =========================================================

@bot.message_handler(
    func=lambda m: True,
    content_types=["text"]
)
def handle_text(m):
    uid = m.chat.id

    user = get_user(uid)
    state = get_state(uid)

    if not user:
        return

    if user.get("is_banned"):
        bot.send_message(
            uid,
            "⛔ Твой аккаунт заблокирован модерацией."
        )
        return

    # -----------------------------------------------------
    # REGISTRATION
    # -----------------------------------------------------

    if not user.get("age") and m.text.isdigit():
        age = int(m.text)

        if age < MIN_AGE:
            bot.send_message(
                uid,
                f"❌ Сервис доступен только пользователям "
                f"{MIN_AGE}+. Регистрация невозможна."
            )
            return

        if age > 100:
            bot.send_message(
                uid,
                "❌ Введи корректный возраст."
            )
            return

        update_user(
            uid,
            age=age
        )

        bot.send_message(
            uid,
            "📏 Твой рост? (см, число от 100 до 250)"
        )

        return

    if user.get("age") and not user.get("height"):
        if (
            not m.text.isdigit()
            or not (100 <= int(m.text) <= 250)
        ):
            bot.send_message(
                uid,
                "❌ Введи рост числом от 100 до 250 см."
            )
            return

        update_user(
            uid,
            height=int(m.text)
        )

        bot.send_message(
            uid,
            "⚖️ Твой вес? (кг, число от 30 до 250)"
        )

        return

    if user.get("height") and not user.get("weight"):
        if (
            not m.text.isdigit()
            or not (30 <= int(m.text) <= 250)
        ):
            bot.send_message(
                uid,
                "❌ Введи вес числом от 30 до 250 кг."
            )
            return

        update_user(
            uid,
            weight=int(m.text)
        )

        bot.send_message(
            uid,
            "🏙️ Из какого ты города?"
        )

        return

    if user.get("weight") and not user.get("city"):
        update_user(
            uid,
            city=m.text[:50]
        )

        bot.send_message(
            uid,
            "📝 Напиши о себе (макс 200 символов)"
        )

        return

    if user.get("city") and not user.get("bio"):
        update_user(
            uid,
            bio=m.text[:200]
        )

        bot.send_message(
            uid,
            "📸 Отправь свою фотографию"
        )

        return

    # -----------------------------------------------------
    # OTHER REPORT
    # -----------------------------------------------------

    if state.get("action") == "reporting_other":
        target_id = state.get("target_id")

        save_report(
            uid,
            target_id,
            m.text[:300]
        )

        bot.send_message(
            uid,
            "✅ Жалоба отправлена модераторам.",
            reply_markup=main_menu()
        )

        notify_admins(
            f"🚩 Новая жалоба на пользователя "
            f"id {target_id}:\n"
            f"{m.text[:300]}"
        )

        clear_state(uid)

        return

    # -----------------------------------------------------
    # SEND TEXT MESSAGE
    # -----------------------------------------------------

    if (
        state.get("action") == "sending_message"
        and state.get("msg_type") == "text"
    ):
        target_id = state.get("target_id")

        save_message(
            uid,
            target_id,
            m.text,
            "text"
        )

        target = get_user(target_id)

        clear_state(uid)

        if target:
            bot.send_message(
                uid,
                "✅ Письмо отправлено! "
                "Теперь оцени анкету 👇"
            )

            show_rating_card(
                uid,
                target
            )
        else:
            bot.send_message(
                uid,
                "✅ Письмо отправлено!",
                reply_markup=main_menu()
            )

        return

    # -----------------------------------------------------
    # DELETE PROFILE
    # -----------------------------------------------------

    if state.get("action") == "confirm_delete":
        if m.text.lower() == "да":
            delete_user(uid)

            bot.send_message(
                uid,
                "❌ Твой профиль удален"
            )

            clear_state(uid)

        elif m.text.lower() == "нет":
            bot.send_message(
                uid,
                "✅ Отмена",
                reply_markup=main_menu()
            )

            clear_state(uid)

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
        bot.send_message(
            uid,
            "Главное меню",
            reply_markup=main_menu()
        )


# =========================================================
# PHOTO
# =========================================================

@bot.message_handler(content_types=["photo"])
def handle_photo(m):
    uid = m.chat.id

    user = get_user(uid)

    if (
        user
        and user.get("city")
        and not user.get("photo_id")
    ):
        update_user(
            uid,
            photo_id=m.photo[-1].file_id
        )

        bot.send_message(
            uid,
            "👤 Выбери свой пол:",
            reply_markup=gender_kb()
        )


# =========================================================
# VOICE
# =========================================================

@bot.message_handler(content_types=["voice"])
def handle_voice(m):
    uid = m.chat.id
    state = get_state(uid)

    if (
        state.get("action") == "sending_message"
        and state.get("msg_type") == "voice"
    ):
        target_id = state.get("target_id")

        save_message(
            uid,
            target_id,
            "🎤 Голосовое сообщение",
            "voice",
            m.voice.file_id
        )

        target = get_user(target_id)

        clear_state(uid)

        if target:
            bot.send_message(
                uid,
                "✅ Голосовое письмо отправлено! "
                "Теперь оцени анкету 👇"
            )

            show_rating_card(
                uid,
                target
            )

        else:
            bot.send_message(
                uid,
                "✅ Голосовое письмо отправлено!",
                reply_markup=main_menu()
            )


# =========================================================
# VIDEO NOTE / CIRCLE
# =========================================================

@bot.message_handler(content_types=["video_note"])
def handle_circle(m):
    uid = m.chat.id
    state = get_state(uid)

    if (
        state.get("action") == "sending_message"
        and state.get("msg_type") == "circle"
    ):
        target_id = state.get("target_id")

        save_message(
            uid,
            target_id,
            "🎙️ Кружок",
            "circle",
            m.video_note.file_id
        )

        target = get_user(target_id)

        clear_state(uid)

        if target:
            bot.send_message(
                uid,
                "✅ Кружок отправлен! "
                "Теперь оцени анкету 👇"
            )

            show_rating_card(
                uid,
                target
            )

        else:
            bot.send_message(
                uid,
                "✅ Кружок отправлен!",
                reply_markup=main_menu()
            )


# =========================================================
# GENDER
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data.startswith("gender_")
)
def set_gender(c):
    uid = c.from_user.id

    gender = (
        "male"
        if "male" in c.data
        else "female"
    )

    update_user(
        uid,
        gender=gender,
        registered=True
    )

    bot.edit_message_text(
        "✅ Профиль готов!",
        c.message.chat.id,
        c.message.message_id
    )

    bot.send_message(
        uid,
        "🎉 **ГОТОВО! Начни оценивать!** 🎉",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


# =========================================================
# RATING CARD
# =========================================================

def show_rating_card(uid, target):
    text = (
        f"👤 **@{target['username']}**  ·  "
        f"{target['age']} лет\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📏 {target['height']} см   "
        f"⚖️ {target['weight']} кг\n"
        f"🏙️ {target['city']}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📝 _{target['bio']}_\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💖 **Оцени внешность:**"
    )

    if target.get("photo_id"):
        bot.send_photo(
            uid,
            target["photo_id"],
            caption=text,
            reply_markup=rating_kb(
                target["gender"],
                target["id"]
            ),
            parse_mode="Markdown"
        )

    else:
        bot.send_message(
            uid,
            text,
            reply_markup=rating_kb(
                target["gender"],
                target["id"]
            ),
            parse_mode="Markdown"
        )


# =========================================================
# ANONYMOUS / PUBLIC PROFILE
# =========================================================

def show_public_profile(viewer_id, target):
    """
    Показываем анкету без username.
    Username пользователь сможет получить только
    через отдельное действие "Познакомиться".
    """

    text = (
        f"👤 **Анкета пользователя**  ·  "
        f"{target['age']} лет\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📏 {target['height']} см   "
        f"⚖️ {target['weight']} кг\n"
        f"🏙️ {target['city']}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📝 _{target['bio']}_\n"
        f"━━━━━━━━━━━━━━━"
    )

    if target.get("photo_id"):
        bot.send_photo(
            viewer_id,
            target["photo_id"],
            caption=text,
            reply_markup=user_view_kb(
                target["id"]
            ),
            parse_mode="Markdown"
        )

    else:
        bot.send_message(
            viewer_id,
            text,
            reply_markup=user_view_kb(
                target["id"]
            ),
            parse_mode="Markdown"
        )


# =========================================================
# RATE MENU
# =========================================================

def rate_menu(uid):
    user = get_user(uid)

    if not user or not user.get("registered"):
        bot.send_message(
            uid,
            "❌ Завершите регистрацию (/start)"
        )
        return

    skipped = skipped_profiles.get(
        uid,
        set()
    )

    target = get_random_user(
        uid,
        extra_exclude=list(skipped)
    )

    if not target:
        # Если все доступные анкеты были пропущены,
        # очищаем список пропущенных и пробуем снова.
        if skipped:
            skipped_profiles[uid] = set()

            target = get_random_user(uid)

        if not target:
            bot.send_message(
                uid,
                "😢 Больше некого оценивать "
                "прямо сейчас — загляни позже",
                reply_markup=main_menu()
            )
            return

    show_rating_card(
        uid,
        target
    )


# =========================================================
# RATING CALLBACK
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data.startswith("rate_")
)
def set_rating(c):
    parts = c.data.split(
        "_",
        2
    )

    target_id = int(parts[1])
    rating = parts[2]
    uid = c.from_user.id

    if has_rated(
        uid,
        target_id
    ):
        bot.answer_callback_query(
            c.id,
            "Ты уже оценивал(-а) этого пользователя"
        )
        return

    save_rating(
        uid,
        target_id,
        rating
    )

    emoji = SCALE_EMOJIS.get(
        rating,
        "⭐"
    )

    bot.answer_callback_query(
        c.id,
        f"✅ {emoji} {rating}"
    )

    # -----------------------------------------------------
    # УВЕДОМЛЕНИЕ О ЛЮБОЙ ОЦЕНКЕ
    #
    # Username здесь специально НЕ показывается.
    # -----------------------------------------------------

    target = get_user(target_id)
    rater = get_user(uid)

    if target and rater:
        notification_text = (
            f"{emoji} **Тебя оценили!**\n\n"
            f"Оценка: **{rating}**\n\n"
            f"👁️ Хочешь посмотреть анкету?"
        )

        keyboard = InlineKeyboardMarkup()

        keyboard.add(
            InlineKeyboardButton(
                "👁️ Показать анкету",
                callback_data=f"showuser_{uid}"
            )
        )

        # Если у оценившего есть фото,
        # оно показывается вместе с уведомлением.
        if rater.get("photo_id"):
            try:
                bot.send_photo(
                    target_id,
                    rater["photo_id"],
                    caption=notification_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            except Exception:
                # Если по какой-то причине фото не отправилось,
                # отправляем обычное текстовое уведомление.
                try:
                    bot.send_message(
                        target_id,
                        notification_text,
                        reply_markup=keyboard,
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

        else:
            try:
                bot.send_message(
                    target_id,
                    notification_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    # Автоматически показываем следующую анкету.
    rate_menu(uid)


# =========================================================
# SKIP
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data.startswith("skip_")
)
def handle_skip(c):
    uid = c.from_user.id

    target_id = int(
        c.data.split("_")[1]
    )

    skipped_profiles.setdefault(
        uid,
        set()
    ).add(target_id)

    bot.answer_callback_query(
        c.id,
        "⏭️ Пропущено"
    )

    rate_menu(uid)


# =========================================================
# SHOW PROFILE
# =========================================================

def show_profile(m):
    uid = m.chat.id

    user = get_user(uid)

    if not user or not user.get("registered"):
        bot.send_message(
            uid,
            "❌ Завершите регистрацию"
        )
        return

    emoji = (
        "👨"
        if user["gender"] == "male"
        else "👩"
    )

    text = (
        f"{emoji} **@{user['username']}**\n\n"
        f"📅 {user['age']} лет\n"
        f"📏 {user['height']} см\n"
        f"⚖️ {user['weight']} кг\n"
        f"🏙️ {user['city']}\n"
        f"📝 _{user['bio']}_"
    )

    if user.get("photo_id"):
        bot.send_photo(
            uid,
            user["photo_id"],
            caption=text,
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )

    else:
        bot.send_message(
            uid,
            text,
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )


# =========================================================
# MY RATINGS
# =========================================================

def show_ratings(m):
    uid = m.chat.id

    ratings = get_user_ratings(uid)

    if not ratings:
        bot.send_message(
            uid,
            "📊 Пока никто не оценил тебя 😞",
            reply_markup=main_menu()
        )
        return

    user = get_user(uid)

    if not user:
        return

    # Считаем количество каждой оценки.
    counts = {}

    for rating_data in ratings:
        rating = rating_data["rating"]

        counts[rating] = (
            counts.get(rating, 0) + 1
        )

    scale = get_scale(
        user["gender"]
    )

    text = "💕 **ТВОИ ОЦЕНКИ:**\n\n"

    # Показываем оценки в порядке шкалы.
    for rating in scale:
        if rating in counts:
            emoji = SCALE_EMOJIS.get(
                rating,
                "⭐"
            )

            count = counts[rating]

            text += (
                f"{emoji} **{rating}** — "
                f"{count}\n"
            )

    text += (
        f"\n📊 Всего оценок: "
        f"**{len(ratings)}**"
    )

    bot.send_message(
        uid,
        text,
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


# =========================================================
# MESSAGES LIST
# =========================================================

def show_messages(m):
    uid = m.chat.id

    messages = get_unread_messages(uid)

    if not messages:
        bot.send_message(
            uid,
            "📬 Нет новых писем",
            reply_markup=main_menu()
        )
        return

    text = (
        f"💌 **У тебя {len(messages)} "
        f"новых писем:**\n\n"
    )

    for msg in messages:
        sender_name = (
            msg["sender_name"]
            or "Пользователь"
        )

        text += (
            f"📨 От **{sender_name}**\n"
        )

    kb = ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    kb.add(
        KeyboardButton(
            "📬 Прочитать письма"
        ),
        KeyboardButton(
            "⬅️ Назад"
        )
    )

    bot.send_message(
        uid,
        text,
        parse_mode="Markdown",
        reply_markup=kb
    )


# =========================================================
# READ MESSAGES
# =========================================================

def read_messages(m):
    uid = m.chat.id

    messages = get_unread_messages(uid)

    if not messages:
        bot.send_message(
            uid,
            "📬 Нет новых писем",
            reply_markup=main_menu()
        )
        return

    for msg in messages:
        sender_name = (
            msg["sender_name"]
            or "Пользователь"
        )

        if msg["message_type"] == "text":
            bot.send_message(
                uid,
                f"💌 **От {sender_name}:**\n\n"
                f"{msg['content']}",
                parse_mode="Markdown"
            )

        elif msg["message_type"] == "voice":
            bot.send_voice(
                uid,
                msg["file_id"],
                caption=f"🎤 От {sender_name}"
            )

        elif msg["message_type"] == "circle":
            bot.send_video_note(
                uid,
                msg["file_id"]
            )

        mark_message_read(
            msg["id"]
        )

    bot.send_message(
        uid,
        "✅ Все письма прочитаны",
        reply_markup=main_menu()
    )


# =========================================================
# MATCHES
# =========================================================

def show_matches(m):
    uid = m.chat.id

    matches = get_matches(uid)

    if not matches:
        bot.send_message(
            uid,
            "❤️‍🔥 Мэтчей нет, но они появятся! 😊",
            reply_markup=main_menu()
        )
        return

    text = (
        "❤️‍🔥 **ТВОИ МЭТЧИ:**\n\n"
    )

    for match_id in matches:
        user = get_user(match_id)

        if user:
            name = (
                user.get("name")
                or "Пользователь"
            )

            username = (
                user.get("username")
                or "без username"
            )

            text += (
                f"👥 **{name}** "
                f"(@{username})\n"
            )

    bot.send_message(
        uid,
        text,
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


# =========================================================
# TOP
# =========================================================

def show_top(m):
    uid = m.chat.id

    conn = get_db()
    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    cur.execute(
        """
        SELECT
            u.username,
            u.gender,
            COUNT(r.id) AS count
        FROM users u
        LEFT JOIN ratings r
          ON r.to_user = u.id
        WHERE u.registered = TRUE
          AND u.is_banned = FALSE
        GROUP BY u.id
        ORDER BY count DESC
        LIMIT 20
        """
    )

    top_users = cur.fetchall()

    cur.close()
    conn.close()

    if not top_users:
        bot.send_message(
            uid,
            "🏆 Пока нет оценок",
            reply_markup=main_menu()
        )
        return

    text = (
        "🏆 **ТОП МОГГВИНЧИК:**\n\n"
    )

    for i, user in enumerate(
        top_users,
        1
    ):
        em = (
            "👨"
            if user["gender"] == "male"
            else "👩"
        )

        text += (
            f"{i}. {em} "
            f"@{user['username']} — "
            f"{user['count']} 🌟\n"
        )

    bot.send_message(
        uid,
        text,
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


# =========================================================
# DELETE PROFILE
# =========================================================

def confirm_delete(m):
    uid = m.chat.id

    set_state(
        uid,
        action="confirm_delete"
    )

    bot.send_message(
        uid,
        "⚠️ Ты уверен? Напиши 'да' или 'нет'"
    )


# =========================================================
# SHOW PROFILE FROM NOTIFICATION
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data.startswith("showuser_")
)
def handle_show_user(c):
    uid = c.from_user.id

    target_id = int(
        c.data.split("_")[1]
    )

    target = get_user(target_id)

    if (
        not target
        or not target.get("registered")
        or target.get("is_banned")
    ):
        bot.answer_callback_query(
            c.id,
            "Анкета больше недоступна"
        )
        return

    bot.answer_callback_query(
        c.id
    )

    show_public_profile(
        uid,
        target
    )


# =========================================================
# SEND MESSAGE
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data.startswith("msg_")
)
def handle_msg(c):
    uid = c.from_user.id

    target_id = int(
        c.data.split("_")[1]
    )

    if target_id == uid:
        bot.answer_callback_query(
            c.id,
            "Нельзя отправить письмо самому себе 😄"
        )
        return

    set_state(
        uid,
        action="choosing_message_type",
        target_id=target_id
    )

    bot.send_message(
        uid,
        "💌 Выбери тип письма:",
        reply_markup=message_type_kb(
            target_id
        )
    )


# =========================================================
# INTRO REQUEST
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data.startswith("askuser_")
)
def handle_askuser(c):
    uid = c.from_user.id

    target_id = int(
        c.data.split("_")[1]
    )

    if target_id == uid:
        bot.answer_callback_query(
            c.id,
            "Нельзя познакомиться с собой 😄"
        )
        return

    user = get_user(uid)
    target = get_user(target_id)

    if not user or not target:
        bot.answer_callback_query(
            c.id,
            "Пользователь недоступен"
        )
        return

    bot.answer_callback_query(
        c.id
    )

    username = (
        user.get("username")
        or "пользователь"
    )

    keyboard = InlineKeyboardMarkup()

    keyboard.add(
        InlineKeyboardButton(
            "✅ Дать юз",
            callback_data=f"giveuser_{uid}"
        )
    )

    bot.send_message(
        target_id,
        f"🤝 **@{username}** хочет с тобой "
        f"познакомиться и просит твой юзернейм!",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

    bot.send_message(
        uid,
        "🤝 Запрос на знакомство отправлен!"
    )


# =========================================================
# MESSAGE TYPE
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data.startswith("msgtype_")
)
def handle_msgtype(c):
    uid = c.from_user.id

    parts = c.data.split("_")

    msg_type = parts[1]
    target_id = int(parts[2])

    set_state(
        uid,
        action="sending_message",
        msg_type=msg_type,
        target_id=target_id
    )

    if msg_type == "text":
        bot.send_message(
            uid,
            "📝 Напиши своё письмо:"
        )

    elif msg_type == "voice":
        bot.send_message(
            uid,
            "🎤 Отправь голосовое сообщение:"
        )

    elif msg_type == "circle":
        bot.send_message(
            uid,
            "🎙️ Отправь кружок "
            "(видеосообщение):"
        )


# =========================================================
# GIVE USERNAME
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data.startswith("giveuser_")
)
def give_user_contact(c):
    user = get_user(
        c.from_user.id
    )

    requester_id = int(
        c.data.split("_")[1]
    )

    if not user:
        bot.answer_callback_query(
            c.id,
            "Пользователь недоступен"
        )
        return

    username = (
        user.get("username")
        or "username отсутствует"
    )

    try:
        bot.send_message(
            requester_id,
            f"✅ **Контакт:** @{username}",
            parse_mode="Markdown"
        )

        bot.answer_callback_query(
            c.id,
            "✅ Контакт отправлен!"
        )

    except Exception:
        bot.answer_callback_query(
            c.id,
            "❌ Не удалось отправить контакт"
        )


# =========================================================
# REPORT
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data.startswith("report_")
)
def handle_report(c):
    uid = c.from_user.id

    target_id = int(
        c.data.split("_")[1]
    )

    if target_id == uid:
        bot.answer_callback_query(
            c.id,
            "Нельзя пожаловаться на себя"
        )
        return

    bot.answer_callback_query(
        c.id
    )

    bot.send_message(
        uid,
        "🚩 Выбери причину жалобы:",
        reply_markup=report_reason_kb(
            target_id
        )
    )


# =========================================================
# REPORT REASON
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data.startswith(
        "reportreason_"
    )
)
def handle_report_reason(c):
    uid = c.from_user.id

    parts = c.data.split(
        "_",
        2
    )

    target_id = int(parts[1])
    reason = parts[2]

    if reason == "Другое":
        set_state(
            uid,
            action="reporting_other",
            target_id=target_id
        )

        bot.send_message(
            uid,
            "Опиши в чём проблема:"
        )

        return

    save_report(
        uid,
        target_id,
        reason
    )

    bot.send_message(
        uid,
        "✅ Жалоба отправлена модераторам.",
        reply_markup=main_menu()
    )

    notify_admins(
        f"🚩 Новая жалоба на пользователя "
        f"id {target_id}:\n"
        f"Причина: {reason}"
    )


# =========================================================
# ADMIN BAN FROM REPORT
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data.startswith(
        "adminban_"
    )
)
def handle_admin_ban(c):
    if not is_admin(
        c.from_user.id
    ):
        return

    parts = c.data.split("_")

    target_id = int(parts[1])
    report_id = int(parts[2])

    ban_user(
        target_id,
        "Забанен по жалобе модератором"
    )

    close_report(
        report_id
    )

    bot.answer_callback_query(
        c.id,
        "Пользователь забанен"
    )

    bot.edit_message_text(
        f"⛔ Пользователь id "
        f"{target_id} забанен. "
        f"Жалоба закрыта.",
        c.message.chat.id,
        c.message.message_id
    )

    try:
        bot.send_message(
            target_id,
            "⛔ Твой аккаунт заблокирован "
            "модерацией по жалобе."
        )
    except Exception:
        pass


# =========================================================
# ADMIN DISMISS REPORT
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data.startswith(
        "admindismiss_"
    )
)
def handle_admin_dismiss(c):
    if not is_admin(
        c.from_user.id
    ):
        return

    report_id = int(
        c.data.split("_")[1]
    )

    close_report(
        report_id
    )

    bot.answer_callback_query(
        c.id,
        "Жалоба отклонена"
    )

    bot.edit_message_text(
        "✅ Жалоба отклонена.",
        c.message.chat.id,
        c.message.message_id
    )


# =========================================================
# START BOT
# =========================================================

print("🚀 БОТ ЗАПУЩЕН!")

bot.infinity_polling()
