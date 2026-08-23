from flask import Flask, request, redirect, session, render_template_string, jsonify
import sqlite3
import os
import time
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "sou9-jilma-secret-2026")

DB = "sou9_jilma.db"
UPLOAD_FOLDER = "static/uploads"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_phone(phone):
    return "".join(
        char for char in phone
        if char.isdigit()
    )


def init_db():

    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            phone TEXT,
            email TEXT UNIQUE,
            is_admin INTEGER DEFAULT 0
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS ads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            price TEXT NOT NULL,
            category TEXT NOT NULL,
            location TEXT NOT NULL,
            image TEXT,
            user_id INTEGER,
            views INTEGER DEFAULT 0,
            status TEXT DEFAULT 'available',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad_id INTEGER NOT NULL,
            reporter_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            details TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ad_id, reporter_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            ad_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, ad_id)
        )
    """)

    # -----------------------------------------------------
    # ميزات الإدارة المتقدمة
    # -----------------------------------------------------
    try:
        conn.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute("ALTER TABLE users ADD COLUMN ban_reason TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute("ALTER TABLE users ADD COLUMN created_at TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute("ALTER TABLE users ADD COLUMN last_login TIMESTAMP")
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute("ALTER TABLE ads ADD COLUMN featured INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            action TEXT NOT NULL,
            target_type TEXT,
            target_id INTEGER,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # -----------------------------------------------------
    # إصلاح قواعد البيانات القديمة
    # -----------------------------------------------------

    try:
        conn.execute(
            "ALTER TABLE users ADD COLUMN email TEXT"
        )
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute(
            "ALTER TABLE ads ADD COLUMN views INTEGER DEFAULT 0"
        )
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute(
            "ALTER TABLE ads ADD COLUMN status TEXT DEFAULT 'available'"
        )
    except sqlite3.OperationalError:
        pass

    # -----------------------------------------------------
    # حساب الأدمن الأساسي
    # -----------------------------------------------------

    admin = conn.execute(
        """
        SELECT *
        FROM users
        WHERE username = ?
        """,
        ("so9na.com",)
    ).fetchone()

    if not admin:

        conn.execute("""
            INSERT INTO users
            (
                username,
                password,
                phone,
                email,
                is_admin
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            "so9na.com",
            generate_password_hash("yakoub50"),
            "",
            "admin@so9na.com",
            1
        ))

    else:

        conn.execute("""
            UPDATE users
            SET password = ?,
                is_admin = 1
            WHERE username = ?
        """, (
            generate_password_hash("yakoub50"),
            "so9na.com"
        ))

    conn.commit()
    conn.close()


# =========================================================
# CATEGORIES
# =========================================================

CATEGORIES = [
    ("📱", "هواتف"),
    ("💻", "إلكترونيات"),
    ("🚗", "سيارات"),
    ("🏠", "عقارات"),
    ("👕", "ملابس"),
    ("🌾", "فلاحة"),
    ("🐄", "حيوانات"),
    ("🔧", "خدمات"),
    ("🛋️", "أثاث"),
    ("📦", "أخرى")
]


REPORT_REASONS = [
    "إعلان مخالف",
    "احتيال أو نصب",
    "معلومات كاذبة",
    "منتج ممنوع",
    "محتوى غير مناسب",
    "سبب آخر"
]


# =========================================================
# HELPERS
# =========================================================

def is_logged():
    return bool(session.get("user_id"))


def is_admin():
    """تحقق من صلاحية الأدمن من قاعدة البيانات، وليس من الجلسة فقط."""
    user_id = session.get("user_id")
    if not user_id:
        return False

    try:
        conn = get_db()
        user = conn.execute(
            "SELECT is_admin, is_banned FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        conn.close()
        return bool(user and user["is_admin"] and not user["is_banned"])
    except sqlite3.Error:
        return False


def admin_required():
    if not is_logged():
        return False
    return is_admin()


def log_admin_action(action, target_type="", target_id=None, details=""):
    """يسجل عمليات الإدارة لمراجعتها لاحقاً."""
    try:
        conn = get_db()
        conn.execute(
            """
            INSERT INTO admin_logs
            (admin_id, action, target_type, target_id, details)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session.get("user_id"),
                action,
                target_type,
                target_id,
                details
            )
        )
        conn.commit()
        conn.close()
    except sqlite3.Error:
        pass


# =========================================================
# STYLE
# =========================================================

STYLE = """
<meta name="viewport"
content="width=device-width, initial-scale=1.0,
maximum-scale=1.0, user-scalable=no">

<style>

* {
    box-sizing: border-box;
}

html,
body {
    width: 100%;
    min-height: 100%;
    margin: 0;
    padding: 0;
}

body {
    font-family: Arial, sans-serif;
    background: #f5f3ff;
    color: #222;
    overflow-x: hidden;
}

nav {
    width: 100%;
    background: linear-gradient(
        135deg,
        #5b21b6,
        #7c3aed
    );
    color: white;
    padding: 12px 10px;
    box-shadow: 0 3px 12px #0002;
}

.nav-container {
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
}

.logo {
    width: 100%;
    text-align: center;
    font-size: 22px;
    font-weight: bold;
}

.nav-buttons {
    width: 100%;
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 7px;
    flex-wrap: wrap;
}

.nav-buttons a {
    flex: 1;
    min-width: 65px;
    max-width: 130px;
    text-align: center;
    background: #ffffff20;
    color: white;
    padding: 9px 6px;
    border-radius: 10px;
    text-decoration: none;
    font-size: 13px;
}

.nav-buttons a:hover {
    background: #ffffff38;
}

.container {
    width: 100%;
    min-height: calc(100vh - 100px);
    padding: 10px;
}

.hero {
    width: 100%;
    background: white;
    padding: 18px;
    border-radius: 15px;
    margin-bottom: 12px;
    box-shadow: 0 2px 10px #0001;
}

.hero h1 {
    color: #5b21b6;
    margin-top: 0;
}

.welcome {
    width: 100%;
    background: linear-gradient(
        135deg,
        #ede9fe,
        #ddd6fe
    );
    color: #4c1d95;
    padding: 15px;
    border-radius: 13px;
    margin-bottom: 12px;
    box-shadow: 0 2px 8px #0001;
}

.search {
    width: 100%;
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}

input,
textarea,
select {
    width: 100%;
    padding: 14px;
    border: 1px solid #ddd6fe;
    border-radius: 10px;
    margin-bottom: 10px;
    font-size: 16px;
    background: white;
    outline: none;
}

input:focus,
textarea:focus,
select:focus {
    border-color: #7c3aed;
    box-shadow: 0 0 0 2px #7c3aed22;
}

button,
.btn {
    background: linear-gradient(
        135deg,
        #5b21b6,
        #7c3aed
    );
    color: white;
    border: none;
    padding: 13px 18px;
    border-radius: 10px;
    cursor: pointer;
    text-decoration: none;
    display: inline-block;
    font-size: 16px;
}

button {
    width: auto;
}

.btn-danger {
    background: #dc2626;
}

.btn-blue {
    background: #2563eb;
}

.btn-green {
    background: #16a34a;
}

.btn-orange {
    background: #ea580c;
}

.btn-gray {
    background: #6b7280;
}

.grid {
    width: 100%;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 9px;
}

.card {
    width: 100%;
    background: white;
    border-radius: 13px;
    overflow: hidden;
    box-shadow: 0 2px 8px #0002;
    position: relative;
}

.card img {
    width: 100%;
    height: 145px;
    object-fit: cover;
    display: block;
}

.card-body {
    width: 100%;
    padding: 10px;
}

.card-body h3 {
    font-size: 15px;
    margin: 4px 0 8px;
}

.price {
    color: #6d28d9;
    font-size: 17px;
    font-weight: bold;
}

.category {
    color: #777;
    font-size: 13px;
}

.form-box {
    width: 100%;
    max-width: 600px;
    margin: 10px auto;
    background: white;
    padding: 18px;
    border-radius: 15px;
    box-shadow: 0 2px 10px #0001;
}

.alert {
    background: #fee2e2;
    color: #991b1b;
    padding: 12px;
    border-radius: 10px;
    margin-bottom: 12px;
}

.success {
    background: #dcfce7;
    color: #166534;
    padding: 12px;
    border-radius: 10px;
    margin-bottom: 12px;
}

.detail {
    width: 100%;
    background: white;
    padding: 15px;
    border-radius: 15px;
    box-shadow: 0 2px 10px #0001;
}

.detail img {
    width: 100%;
    max-height: 450px;
    object-fit: contain;
    border-radius: 12px;
}

.admin-header {
    width: 100%;
    background: linear-gradient(
        135deg,
        #5b21b6,
        #7c3aed
    );
    color: white;
    padding: 18px;
    border-radius: 15px;
    margin-bottom: 15px;
}

.admin-stats {
    width: 100%;
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
}

.stat {
    background: white;
    border-radius: 13px;
    padding: 15px;
    text-align: center;
    box-shadow: 0 2px 8px #0001;
}

.stat-number {
    font-size: 25px;
    font-weight: bold;
    color: #6d28d9;
}

.admin-card,
.user-admin-card {
    background: white;
    border-radius: 13px;
    padding: 15px;
    margin: 8px 0;
    box-shadow: 0 2px 8px #0001;
}

.admin-actions {
    display: flex;
    gap: 7px;
    flex-wrap: wrap;
}

.chat-box {
    width: 100%;
    max-width: 650px;
    margin: 10px auto;
    background: white;
    border-radius: 15px;
    overflow: hidden;
    box-shadow: 0 2px 10px #0002;
}

.chat-header {
    background: linear-gradient(
        135deg,
        #5b21b6,
        #7c3aed
    );
    color: white;
    padding: 13px;
    text-align: center;
}

.messages {
    height: 55vh;
    min-height: 350px;
    overflow-y: auto;
    padding: 12px;
    background: #f8f7ff;
}

.message-row {
    display: flex;
    margin: 7px 0;
}

.message-row.mine {
    justify-content: flex-end;
}

.message-row.theirs {
    justify-content: flex-start;
}

.message-bubble {
    max-width: 78%;
    padding: 9px 12px;
    border-radius: 14px;
    word-wrap: break-word;
    overflow-wrap: anywhere;
    box-shadow: 0 1px 4px #0001;
}

.mine .message-bubble {
    background: #7c3aed;
    color: white;
    border-bottom-right-radius: 4px;
}

.theirs .message-bubble {
    background: white;
    color: #222;
    border-bottom-left-radius: 4px;
}

.message-time {
    display: block;
    font-size: 10px;
    margin-top: 4px;
    opacity: .7;
}

.message-form {
    display: flex;
    gap: 7px;
    padding: 9px;
    background: white;
    border-top: 1px solid #eee;
}

.message-input {
    flex: 1;
    width: auto !important;
    margin: 0 !important;
    padding: 10px 12px !important;
    min-height: 42px;
    max-height: 90px;
    resize: none;
}

.message-form button {
    width: auto;
    padding: 10px 15px;
}

.chat-user {
    display: block;
    background: white;
    padding: 13px;
    border-radius: 12px;
    margin: 7px 0;
    text-decoration: none;
    color: #222;
    box-shadow: 0 2px 7px #0001;
}

.report-box {
    background: #fff7ed;
    border: 1px solid #fed7aa;
    padding: 15px;
    border-radius: 13px;
    margin-top: 20px;
}

.report-card {
    background: #fff;
    border-left: 5px solid #ea580c;
    border-radius: 13px;
    padding: 15px;
    margin: 10px 0;
    box-shadow: 0 2px 8px #0001;
}

.report-done {
    border-left-color: #16a34a;
}

.status-available {
    color: #16a34a;
    font-weight: bold;
}

.status-sold {
    color: #dc2626;
    font-weight: bold;
}

.favorite-btn {
    display: inline-block;
    padding: 8px 12px;
    border-radius: 9px;
    text-decoration: none;
    background: #f3e8ff;
    color: #6d28d9;
}

.views {
    color: #777;
    font-size: 13px;
}

footer {
    width: 100%;
    text-align: center;
    padding: 25px 10px;
    color: #777;
}

@media (max-width: 600px) {

    html,
    body {
        width: 100vw;
        min-width: 100vw;
        max-width: 100vw;
    }

    nav {
        padding: 10px 7px;
    }

    .container {
        width: 100vw;
        padding: 8px;
    }

    .logo {
        font-size: 20px;
    }

    .nav-buttons {
        gap: 5px;
    }

    .nav-buttons a {
        min-width: 60px;
        max-width: none;
        padding: 9px 5px;
        font-size: 12px;
    }

    .grid {
        width: 100%;
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .card img {
        height: 135px;
    }

    .card-body {
        padding: 8px;
    }

    .card-body h3 {
        font-size: 14px;
    }

    .price {
        font-size: 16px;
    }

    .messages {
        height: 58vh;
        min-height: 300px;
    }

    .message-bubble {
        max-width: 85%;
    }
}

@media (max-width: 360px) {

    .nav-buttons a {
        min-width: 55px;
        font-size: 11px;
        padding: 8px 4px;
    }

    .logo {
        font-size: 18px;
    }
}

</style>
"""


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    if not is_logged():
        return redirect("/login")

    category = request.args.get(
        "category",
        ""
    ).strip()

    sort = request.args.get(
        "sort",
        "newest"
    ).strip()

    search = request.args.get(
        "search",
        ""
    ).strip()

    conn = get_db()

    query = """
        SELECT
            ads.*,
            users.username
        FROM ads
        LEFT JOIN users
        ON ads.user_id = users.id
        WHERE 1=1
    """

    params = []

    if category:

        query += """
            AND ads.category = ?
        """

        params.append(category)

    if search:

        query += """
            AND (
                ads.title LIKE ?
                OR ads.description LIKE ?
                OR ads.location LIKE ?
            )
        """

        search_value = "%" + search + "%"

        params.extend([
            search_value,
            search_value,
            search_value
        ])

    if sort == "cheap":

        query += """
            ORDER BY
                CASE WHEN COALESCE(ads.featured, 0)=1 THEN 0 ELSE 1 END,
                CASE
                    WHEN ads.status = 'sold' THEN 1
                    ELSE 0
                END,
                CAST(ads.price AS REAL) ASC
        """

    elif sort == "expensive":

        query += """
            ORDER BY
                CASE WHEN COALESCE(ads.featured, 0)=1 THEN 0 ELSE 1 END,
                CASE
                    WHEN ads.status = 'sold' THEN 1
                    ELSE 0
                END,
                CAST(ads.price AS REAL) DESC
        """

    elif sort == "views":

        query += """
            ORDER BY
                CASE WHEN COALESCE(ads.featured, 0)=1 THEN 0 ELSE 1 END,
                CASE
                    WHEN ads.status = 'sold' THEN 1
                    ELSE 0
                END,
                ads.views DESC
        """

    else:

        query += """
            ORDER BY
                CASE
                    WHEN ads.status = 'sold' THEN 1
                    ELSE 0
                END,
                ads.id DESC
        """

    ads = conn.execute(
        query,
        params
    ).fetchall()

    conn.close()

    return render_template_string(
        STYLE + """

        <nav>

            <div class="nav-container">

                <div class="logo">
                    🛒 Sou9na 🇹🇳
                </div>

                <div class="nav-buttons">

                    <a href="/">
                        🏠 الرئيسية
                    </a>

                    <a href="/messages">
                        💬 الرسائل
                    </a>

                    <a href="/favorites">
                        ❤️ المفضلة
                    </a>

                    <a href="/profile">
                        👤 حسابي
                    </a>

                    <a href="/add">
                        📢 نشر
                    </a>

                    {% if session.get("is_admin") %}

                        <a href="/admin">
                            🛡️ Admin
                        </a>

                    {% endif %}

                    <a href="/logout">
                        🚪 خروج
                    </a>

                </div>

            </div>

        </nav>

        <div class="container">

            <div class="welcome">

                👋 مرحباً
                <b>{{ session.get("username") }}</b>

                <br>

                أهلاً بيك في Sou9na 🇹🇳

            </div>

            <div class="hero">

                <h1>
                    سوقنا 🛒
                </h1>

                <p>
                    بيع وشراء بسهولة 🇹🇳
                </p>

                <form
                    class="search"
                    method="GET"
                >

                    <input
                        type="search"
                        name="search"
                        value="{{ search }}"
                        placeholder="🔎 ابحث عن منتج أو مكان..."
                    >

                    <select name="category">

                        <option value="">
                            📂 كل التصنيفات
                        </option>

                        {% for icon, c in categories %}

                            <option
                                value="{{ c }}"
                                {% if category == c %}
                                selected
                                {% endif %}
                            >
                                {{ icon }} {{ c }}
                            </option>

                        {% endfor %}

                    </select>

                    <select name="sort">

                        <option
                            value="newest"
                            {% if sort == "newest" %}
                            selected
                            {% endif %}
                        >
                            🆕 الأحدث
                        </option>

                        <option
                            value="cheap"
                            {% if sort == "cheap" %}
                            selected
                            {% endif %}
                        >
                            💰 الأرخص أولاً
                        </option>

                        <option
                            value="expensive"
                            {% if sort == "expensive" %}
                            selected
                            {% endif %}
                        >
                            💎 الأغلى أولاً
                        </option>

                        <option
                            value="views"
                            {% if sort == "views" %}
                            selected
                            {% endif %}
                        >
                            👁️ الأكثر مشاهدة
                        </option>

                    </select>

                    <button type="submit">
                        🔎 بحث
                    </button>

                </form>

            </div>

            <div class="grid">

                {% for ad in ads %}

                    <a
                        href="/ad/{{ ad['id'] }}"
                        style="
                            text-decoration:none;
                            color:inherit;
                        "
                    >

                        <div class="card">

                            {% if ad['image'] %}

                                <img
                                    src="/static/uploads/{{ ad['image'].split('|')[0] }}"
                                >

                            {% else %}

                                <div style="
                                    height:145px;
                                    display:flex;
                                    align-items:center;
                                    justify-content:center;
                                    background:#ddd;
                                    font-size:35px;
                                ">
                                    📷
                                </div>

                            {% endif %}

                            <div class="card-body">

                                <h3>
                                    {{ ad['title'] }}
                                    {% if ad['featured'] %}
                                        <span class="badge badge-orange">⭐ مميز</span>
                                    {% endif %}
                                </h3>

                                <div class="price">
                                    💰 {{ ad['price'] }} د.ت
                                </div>

                                {% if ad['status'] == 'sold' %}

                                    <p class="status-sold">
                                        🔴 تم البيع
                                    </p>

                                {% else %}

                                    <p class="status-available">
                                        🟢 متوفر
                                    </p>

                                {% endif %}

                                <p class="category">
                                    📂 {{ ad['category'] }}
                                    •
                                    📍 {{ ad['location'] }}
                                </p>

                                <p class="views">
                                    👁️ {{ ad['views'] or 0 }}
                                    مشاهدة
                                </p>

                                <span class="btn">
                                    👁️ التفاصيل
                                </span>

                            </div>

                        </div>

                    </a>

                {% else %}

                    <div class="admin-card">

                        🔎 ما لقيناش إعلانات مطابقة.

                    </div>

                {% endfor %}

            </div>

        </div>

        <footer>
            Sou9na © 2026 🇹🇳
        </footer>

        """,
        ads=ads,
        category=category,
        sort=sort,
        search=search,
        categories=CATEGORIES
    )


# =========================================================
# LOGIN
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if is_logged():
        return redirect("/")

    error = ""

    if request.method == "POST":

        identifier = request.form.get(
            "identifier",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        conn = get_db()

        user = conn.execute(
            """
            SELECT *
            FROM users
            WHERE LOWER(email) = ?
               OR LOWER(username) = ?
            """,
            (
                identifier,
                identifier
            )
        ).fetchone()

        conn.close()

        valid = False

        if user:

            try:

                valid = check_password_hash(
                    user["password"],
                    password
                )

            except (ValueError, TypeError):

                valid = (
                    user["password"] == password
                )

        if valid and user["is_banned"]:
            error = "🚫 حسابك موقوف من الإدارة."
            if user["ban_reason"]:
                error += " السبب: " + str(user["ban_reason"])

        elif valid:

            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["is_admin"] = user["is_admin"]

            try:
                conn = get_db()
                conn.execute(
                    "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?",
                    (user["id"],)
                )
                conn.commit()
                conn.close()
            except sqlite3.Error:
                pass

            return redirect("/")

        error = """
        الإيميل أو اسم المستخدم أو كلمة السر غلط.
        """

    return render_template_string(
        STYLE + """

        <div class="container">

            <div class="form-box">

                <div style="
                    text-align:center;
                    background:linear-gradient(
                        135deg,
                        #5b21b6,
                        #7c3aed
                    );
                    color:white;
                    padding:18px;
                    border-radius:14px;
                    margin-bottom:18px;
                ">

                    <h1>
                        Sou9na 🇹🇳
                    </h1>

                    <p>
                        مرحبا بيك 👋
                    </p>

                </div>

                <h2>
                    تسجيل الدخول 🔐
                </h2>

                {% if error %}

                    <div class="alert">
                        {{ error }}
                    </div>

                {% endif %}

                <form method="POST">

                    <input
                        type="text"
                        name="identifier"
                        placeholder="📧 الإيميل أو اسم المستخدم"
                        required
                    >

                    <input
                        type="password"
                        name="password"
                        placeholder="🔐 كلمة السر"
                        required
                    >

                    <button
                        type="submit"
                        style="width:100%;"
                    >
                        🚀 دخول
                    </button>

                </form>

                <br>

                <a href="/register">
                    ما عندكش حساب؟
                    إنشاء حساب
                </a>

            </div>

        </div>

        """,
        error=error
    )


# =========================================================
# REGISTER
# =========================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if is_logged():
        return redirect("/")

    error = ""

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        normalized_phone = normalize_phone(phone)

        if not email or not password:

            error = "اكتب الإيميل وكلمة السر."

        elif "@" not in email:

            error = "الإيميل غير صحيح."

        elif len(password) < 6:

            error = """
            كلمة السر لازم تكون 6 أحرف على الأقل.
            """

        elif phone and len(normalized_phone) < 8:

            error = "رقم الهاتف غير صحيح."

        else:

            conn = get_db()

            existing_email = conn.execute(
                """
                SELECT id
                FROM users
                WHERE LOWER(email) = ?
                """,
                (email,)
            ).fetchone()

            existing_phone = None

            if normalized_phone:

                users_with_phone = conn.execute(
                    """
                    SELECT id, phone
                    FROM users
                    WHERE phone IS NOT NULL
                    AND phone != ''
                    """
                ).fetchall()

                for old_user in users_with_phone:

                    old_phone = normalize_phone(
                        old_user["phone"] or ""
                    )

                    if old_phone == normalized_phone:

                        existing_phone = old_user
                        break

            if existing_email:

                conn.close()

                error = """
                ❌ هذا الإيميل مستعمل في حساب آخر.
                """

            elif existing_phone:

                conn.close()

                error = """
                ❌ رقم الهاتف هذا مستعمل في حساب آخر.
                """

            else:

                username = email.split("@")[0]

                original_username = username
                counter = 1

                while conn.execute(
                    """
                    SELECT id
                    FROM users
                    WHERE username = ?
                    """,
                    (username,)
                ).fetchone():

                    username = (
                        original_username
                        + str(counter)
                    )

                    counter += 1

                conn.execute(
                    """
                    INSERT INTO users
                    (
                        username,
                        password,
                        phone,
                        email,
                        is_admin,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        username,
                        generate_password_hash(password),
                        phone,
                        email,
                        0
                    )
                )

                conn.commit()
                conn.close()

                return redirect("/login")

    return render_template_string(
        STYLE + """

        <div class="container">

            <div class="form-box">

                <div style="
                    text-align:center;
                    background:linear-gradient(
                        135deg,
                        #5b21b6,
                        #7c3aed
                    );
                    color:white;
                    padding:15px;
                    border-radius:14px;
                    margin-bottom:18px;
                ">

                    <h1>
                        Sou9na 🇹🇳
                    </h1>

                    <p>
                        إنشاء حساب جديد 👋
                    </p>

                </div>

                <h2>
                    إنشاء حساب 👤
                </h2>

                {% if error %}

                    <div class="alert">
                        {{ error }}
                    </div>

                {% endif %}

                <form method="POST">

                    <input
                        type="email"
                        name="email"
                        placeholder="📧 البريد الإلكتروني"
                        required
                    >

                    <input
                        type="password"
                        name="password"
                        placeholder="🔐 كلمة السر"
                        minlength="6"
                        required
                    >

                    <input
                        type="tel"
                        name="phone"
                        placeholder="📱 رقم الهاتف"
                    >

                    <button
                        type="submit"
                        style="width:100%;"
                    >
                        🚀 إنشاء الحساب
                    </button>

                </form>

                <br>

                <a href="/login">
                    عندك حساب؟
                    تسجيل الدخول
                </a>

            </div>

        </div>

        """,
        error=error
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/login")
 # =========================================================
# ADD AD
# =========================================================

@app.route("/add", methods=["GET", "POST"])
def add():

    if not is_logged():
        return redirect("/login")

    error = ""

    if request.method == "POST":

        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        price = request.form.get("price", "").strip()
        category = request.form.get("category", "").strip()
        location = request.form.get("location", "").strip()

        images = request.files.getlist("images")
        filenames = []

        if not title or not price or not category or not location:

            error = "لازم تعمر الاسم والسعر والتصنيف والمكان."

        else:

            for image in images[:5]:

                if image and image.filename:

                    filename = secure_filename(
                        str(time.time_ns()) + "_" + image.filename
                    )

                    image.save(
                        os.path.join(
                            UPLOAD_FOLDER,
                            filename
                        )
                    )

                    filenames.append(filename)

            image_names = "|".join(filenames)

            conn = get_db()

            conn.execute(
                """
                INSERT INTO ads
                (
                    title,
                    description,
                    price,
                    category,
                    location,
                    image,
                    user_id,
                    views,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    description,
                    price,
                    category,
                    location,
                    image_names,
                    session["user_id"],
                    0,
                    "available"
                )
            )

            conn.commit()
            conn.close()

            return redirect("/")

    return render_template_string(
        STYLE + """

        <nav>

            <div class="nav-container">

                <div class="logo">
                    📢 نشر إعلان - Sou9na
                </div>

                <div class="nav-buttons">

                    <a href="/">
                        🏠 الرئيسية
                    </a>

                    <a href="/profile">
                        👤 حسابي
                    </a>

                    <a href="/messages">
                        💬 الرسائل
                    </a>

                </div>

            </div>

        </nav>

        <div class="container">

            <div class="form-box">

                <h2>
                    📢 نشر منتج
                </h2>

                {% if error %}

                    <div class="alert">
                        {{ error }}
                    </div>

                {% endif %}

                <form
                    method="POST"
                    enctype="multipart/form-data"
                >

                    <input
                        type="text"
                        name="title"
                        placeholder="📦 اسم المنتج"
                        maxlength="100"
                        required
                    >

                    <textarea
                        name="description"
                        placeholder="📝 وصف المنتج"
                        rows="5"
                        maxlength="3000"
                    ></textarea>

                    <input
                        type="number"
                        name="price"
                        placeholder="💰 السعر بالدينار"
                        min="0"
                        step="0.01"
                        required
                    >

                    <select
                        name="category"
                        required
                    >

                        <option value="">
                            📂 اختر التصنيف
                        </option>

                        {% for icon, c in categories %}

                            <option value="{{ c }}">
                                {{ icon }} {{ c }}
                            </option>

                        {% endfor %}

                    </select>

                    <input
                        type="text"
                        name="location"
                        placeholder="📍 المكان"
                        maxlength="100"
                        required
                    >

                    <label>
                        📷 صور المنتج (حتى 5 صور)
                    </label>

                    <input
                        type="file"
                        name="images"
                        accept="image/*"
                        multiple
                    >

                    <button
                        type="submit"
                        style="width:100%;"
                    >
                        🚀 نشر المنتج
                    </button>

                </form>

            </div>

        </div>

        """,
        error=error,
        categories=CATEGORIES
    )


# =========================================================
# AD DETAILS
# =========================================================

@app.route("/ad/<int:ad_id>")
def ad_details(ad_id):

    if not is_logged():
        return redirect("/login")

    conn = get_db()

    ad = conn.execute(
        """
        SELECT
            ads.*,
            users.username,
            users.phone
        FROM ads

        LEFT JOIN users
        ON ads.user_id = users.id

        WHERE ads.id = ?
        """,
        (ad_id,)
    ).fetchone()

    if not ad:

        conn.close()

        return render_template_string(
            STYLE + """

            <div class="container">

                <div class="form-box">

                    <h2>
                        الإعلان غير موجود ❌
                    </h2>

                    <a
                        class="btn"
                        href="/"
                    >
                        🏠 العودة للرئيسية
                    </a>

                </div>

            </div>

            """
        ), 404

    # زيادة عدد المشاهدات
    conn.execute(
        """
        UPDATE ads
        SET views = COALESCE(views, 0) + 1
        WHERE id = ?
        """,
        (ad_id,)
    )

    conn.commit()

    # التحقق هل الإعلان في المفضلة
    favorite = conn.execute(
        """
        SELECT id
        FROM favorites
        WHERE user_id = ?
        AND ad_id = ?
        """,
        (
            session["user_id"],
            ad_id
        )
    ).fetchone()

    conn.close()

    images = []

    if ad["image"]:

        images = [
            x
            for x in ad["image"].split("|")
            if x
        ]

    return render_template_string(
        STYLE + """

        <nav>

            <div class="nav-container">

                <div class="logo">
                    🛒 Sou9na 🇹🇳
                </div>

                <div class="nav-buttons">

                    <a href="/">
                        🏠 الرئيسية
                    </a>

                    <a href="/messages">
                        💬 الرسائل
                    </a>

                    <a href="/favorites">
                        ❤️ المفضلة
                    </a>

                    <a href="/profile">
                        👤 حسابي
                    </a>

                </div>

            </div>

        </nav>

        <div class="container">

            <div class="detail">

                {% if images %}

                    <img
                        src="/static/uploads/{{ images[0] }}"
                    >

                    {% if images|length > 1 %}

                        <div class="grid"
                             style="margin-top:10px;">

                            {% for image in images[1:] %}

                                <img
                                    src="/static/uploads/{{ image }}"
                                    style="
                                        width:100%;
                                        height:120px;
                                        object-fit:cover;
                                        border-radius:10px;
                                    "
                                >

                            {% endfor %}

                        </div>

                    {% endif %}

                {% else %}

                    <div style="
                        width:100%;
                        height:250px;
                        background:#eee;
                        display:flex;
                        align-items:center;
                        justify-content:center;
                        border-radius:12px;
                        font-size:50px;
                    ">
                        📷
                    </div>

                {% endif %}

                <h1>
                    {{ ad['title'] }}
                </h1>

                <div class="price">
                    💰 {{ ad['price'] }} د.ت
                </div>

                {% if ad['status'] == 'sold' %}

                    <p class="status-sold">
                        🔴 تم البيع
                    </p>

                {% else %}

                    <p class="status-available">
                        🟢 المنتج متوفر
                    </p>

                {% endif %}

                <p class="views">
                    👁️ {{ (ad['views'] or 0) + 1 }}
                    مشاهدة
                </p>

                <p>
                    👤 البائع:
                    <b>
                        {{ ad['username'] or 'غير معروف' }}
                    </b>
                </p>

                <hr>

                <h3>
                    📝 وصف المنتج
                </h3>

                <p>
                    {{ ad['description'] or 'لا يوجد وصف للمنتج.' }}
                </p>

                <hr>

                <p>
                    📂 التصنيف:
                    <b>{{ ad['category'] }}</b>
                </p>

                <p>
                    📍 المكان:
                    <b>{{ ad['location'] }}</b>
                </p>

                <br>

                {% if favorite %}

                    <a
                        class="favorite-btn"
                        href="/favorite/{{ ad['id'] }}"
                    >
                        💔 إزالة من المفضلة
                    </a>

                {% else %}

                    <a
                        class="favorite-btn"
                        href="/favorite/{{ ad['id'] }}"
                    >
                        ❤️ أضف للمفضلة
                    </a>

                {% endif %}

                {% if ad['phone']
                   and ad['user_id'] != session.get('user_id') %}

                    <br><br>

                    <a
                        class="btn"
                        href="tel:{{ ad['phone'] }}"
                    >
                        📞 اتصل بالبائع
                    </a>

                {% endif %}

                {% if ad['user_id']
                   and ad['user_id'] != session.get('user_id') %}

                    <br><br>

                    <a
                        class="btn btn-blue"
                        href="/chat/{{ ad['user_id'] }}"
                    >
                        💬 راسل البائع
                    </a>

                    <div class="report-box">

                        <h3>
                            🚨 الإبلاغ عن الإعلان
                        </h3>

                        <form
                            method="POST"
                            action="/report/{{ ad['id'] }}"
                        >

                            <select
                                name="reason"
                                required
                            >

                                <option value="">
                                    اختر سبب التبليغ
                                </option>

                                {% for reason in report_reasons %}

                                    <option value="{{ reason }}">
                                        {{ reason }}
                                    </option>

                                {% endfor %}

                            </select>

                            <textarea
                                name="details"
                                rows="4"
                                maxlength="1000"
                                placeholder="تفاصيل إضافية (اختياري)"
                            ></textarea>

                            <button
                                type="submit"
                                class="btn-orange"
                                onclick="
                                    return confirm(
                                        'متأكد تحب تبعث التبليغ؟'
                                    );
                                "
                            >
                                🚨 إرسال التبليغ
                            </button>

                        </form>

                    </div>

                {% endif %}

                {% if session.get("user_id") == ad["user_id"]
                   or session.get("is_admin") %}

                    <br><br>

                    {% if ad['status'] == 'available' %}

                        <a
                            class="btn btn-green"
                            href="/mark-sold/{{ ad['id'] }}"
                            onclick="
                                return confirm(
                                    'تأكد أن المنتج تم بيعه؟'
                                );
                            "
                        >
                            ✅ تحديد كمباع
                        </a>

                    {% else %}

                        <a
                            class="btn btn-blue"
                            href="/mark-available/{{ ad['id'] }}"
                        >
                            🔄 إرجاع كمتوفر
                        </a>

                    {% endif %}

                    <br><br>

                    <a
                        class="btn btn-danger"
                        href="/delete/{{ ad['id'] }}"
                        onclick="
                            return confirm(
                                'متأكد تحب تحذف الإعلان؟'
                            );
                        "
                    >
                        🗑️ حذف الإعلان
                    </a>

                {% endif %}

            </div>

        </div>

        """,
        ad=ad,
        images=images,
        favorite=favorite,
        report_reasons=REPORT_REASONS
    )


# =========================================================
# FAVORITE
# =========================================================

@app.route("/favorite/<int:ad_id>")
def favorite(ad_id):

    if not is_logged():
        return redirect("/login")

    conn = get_db()

    ad = conn.execute(
        """
        SELECT id
        FROM ads
        WHERE id = ?
        """,
        (ad_id,)
    ).fetchone()

    if not ad:

        conn.close()
        return redirect("/")

    existing = conn.execute(
        """
        SELECT id
        FROM favorites
        WHERE user_id = ?
        AND ad_id = ?
        """,
        (
            session["user_id"],
            ad_id
        )
    ).fetchone()

    if existing:

        conn.execute(
            """
            DELETE FROM favorites
            WHERE user_id = ?
            AND ad_id = ?
            """,
            (
                session["user_id"],
                ad_id
            )
        )

    else:

        conn.execute(
            """
            INSERT INTO favorites
            (
                user_id,
                ad_id
            )
            VALUES (?, ?)
            """,
            (
                session["user_id"],
                ad_id
            )
        )

    conn.commit()
    conn.close()

    return redirect(
        "/ad/" + str(ad_id)
    )


# =========================================================
# FAVORITES PAGE
# =========================================================

@app.route("/favorites")
def favorites():

    if not is_logged():
        return redirect("/login")

    conn = get_db()

    ads = conn.execute(
        """
        SELECT
            ads.*,
            users.username
        FROM favorites

        JOIN ads
        ON favorites.ad_id = ads.id

        LEFT JOIN users
        ON ads.user_id = users.id

        WHERE favorites.user_id = ?

        ORDER BY favorites.id DESC
        """,
        (session["user_id"],)
    ).fetchall()

    conn.close()

    return render_template_string(
        STYLE + """

        <nav>

            <div class="nav-container">

                <div class="logo">
                    ❤️ المفضلة - Sou9na
                </div>

                <div class="nav-buttons">

                    <a href="/">
                        🏠 الرئيسية
                    </a>

                    <a href="/messages">
                        💬 الرسائل
                    </a>

                    <a href="/profile">
                        👤 حسابي
                    </a>

                </div>

            </div>

        </nav>

        <div class="container">

            <div class="form-box">

                <h2>
                    ❤️ إعلاناتي المفضلة
                </h2>

                {% if ads %}

                    {% for ad in ads %}

                        <div class="admin-card">

                            <h3>
                                {{ ad['title'] }}
                            </h3>

                            <p class="price">
                                💰 {{ ad['price'] }} د.ت
                            </p>

                            <p>
                                📍 {{ ad['location'] }}
                            </p>

                            {% if ad['status'] == 'sold' %}

                                <p class="status-sold">
                                    🔴 تم البيع
                                </p>

                            {% else %}

                                <p class="status-available">
                                    🟢 متوفر
                                </p>

                            {% endif %}

                            <a
                                class="btn"
                                href="/ad/{{ ad['id'] }}"
                            >
                                👁️ مشاهدة
                            </a>

                            <a
                                class="btn btn-danger"
                                href="/favorite/{{ ad['id'] }}"
                            >
                                💔 إزالة
                            </a>

                        </div>

                    {% endfor %}

                {% else %}

                    <div class="admin-card">

                        ❤️ ما عندك حتى إعلان في المفضلة.

                    </div>

                {% endif %}

            </div>

        </div>

        """,
        ads=ads
    )


# =========================================================
# REPORT
# =========================================================

@app.route("/report/<int:ad_id>", methods=["POST"])
def report_ad(ad_id):

    if not is_logged():
        return redirect("/login")

    current_user = session["user_id"]

    reason = request.form.get(
        "reason",
        ""
    ).strip()

    details = request.form.get(
        "details",
        ""
    ).strip()

    if reason not in REPORT_REASONS:
        return redirect("/ad/" + str(ad_id))

    conn = get_db()

    ad = conn.execute(
        """
        SELECT *
        FROM ads
        WHERE id = ?
        """,
        (ad_id,)
    ).fetchone()

    if not ad:

        conn.close()
        return redirect("/")

    if ad["user_id"] == current_user:

        conn.close()
        return redirect("/ad/" + str(ad_id))

    existing = conn.execute(
        """
        SELECT id
        FROM reports
        WHERE ad_id = ?
        AND reporter_id = ?
        """,
        (
            ad_id,
            current_user
        )
    ).fetchone()

    if not existing:

        conn.execute(
            """
            INSERT INTO reports
            (
                ad_id,
                reporter_id,
                reason,
                details
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                ad_id,
                current_user,
                reason,
                details
            )
        )

        conn.commit()

    conn.close()

    return redirect(
        "/ad/" + str(ad_id)
    )


# =========================================================
# MARK SOLD
# =========================================================

@app.route("/mark-sold/<int:ad_id>")
def mark_sold(ad_id):

    if not is_logged():
        return redirect("/login")

    conn = get_db()

    ad = conn.execute(
        """
        SELECT user_id
        FROM ads
        WHERE id = ?
        """,
        (ad_id,)
    ).fetchone()

    if ad:

        if (
            ad["user_id"] == session["user_id"]
            or session.get("is_admin")
        ):

            conn.execute(
                """
                UPDATE ads
                SET status = 'sold'
                WHERE id = ?
                """,
                (ad_id,)
            )

            conn.commit()

    conn.close()

    return redirect(
        "/ad/" + str(ad_id)
    )


# =========================================================
# MARK AVAILABLE
# =========================================================

@app.route("/mark-available/<int:ad_id>")
def mark_available(ad_id):

    if not is_logged():
        return redirect("/login")

    conn = get_db()

    ad = conn.execute(
        """
        SELECT user_id
        FROM ads
        WHERE id = ?
        """,
        (ad_id,)
    ).fetchone()

    if ad:

        if (
            ad["user_id"] == session["user_id"]
            or session.get("is_admin")
        ):

            conn.execute(
                """
                UPDATE ads
                SET status = 'available'
                WHERE id = ?
                """,
                (ad_id,)
            )

            conn.commit()

    conn.close()

    return redirect(
        "/ad/" + str(ad_id)
    )


# =========================================================
# DELETE AD
# =========================================================

@app.route("/delete/<int:ad_id>")
def delete_ad(ad_id):

    if not is_logged():
        return redirect("/login")

    conn = get_db()

    ad = conn.execute(
        """
        SELECT *
        FROM ads
        WHERE id = ?
        """,
        (ad_id,)
    ).fetchone()

    if ad:

        allowed = (
            ad["user_id"] == session["user_id"]
            or session.get("is_admin")
        )

        if allowed:

            if ad["image"]:

                for filename in ad["image"].split("|"):

                    if not filename:
                        continue

                    path = os.path.join(
                        UPLOAD_FOLDER,
                        filename
                    )

                    if os.path.exists(path):

                        try:
                            os.remove(path)
                        except OSError:
                            pass

            conn.execute(
                """
                DELETE FROM favorites
                WHERE ad_id = ?
                """,
                (ad_id,)
            )

            conn.execute(
                """
                DELETE FROM reports
                WHERE ad_id = ?
                """,
                (ad_id,)
            )

            conn.execute(
                """
                DELETE FROM ads
                WHERE id = ?
                """,
                (ad_id,)
            )

            conn.commit()

    conn.close()

    return redirect("/")


# =========================================================
# PROFILE
# =========================================================

@app.route("/profile")
def profile():

    if not is_logged():
        return redirect("/login")

    conn = get_db()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        """,
        (session["user_id"],)
    ).fetchone()

    ads = conn.execute(
        """
        SELECT *
        FROM ads
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (session["user_id"],)
    ).fetchall()

    total_ads = conn.execute(
        """
        SELECT COUNT(*)
        FROM ads
        WHERE user_id = ?
        """,
        (session["user_id"],)
    ).fetchone()[0]

    total_views = conn.execute(
        """
        SELECT COALESCE(SUM(views), 0)
        FROM ads
        WHERE user_id = ?
        """,
        (session["user_id"],)
    ).fetchone()[0]

    total_favorites = conn.execute(
        """
        SELECT COUNT(*)
        FROM favorites
        WHERE user_id = ?
        """,
        (session["user_id"],)
    ).fetchone()[0]

    conn.close()

    return render_template_string(
        STYLE + """

        <div class="container">

            <div class="form-box">

                <div class="welcome">

                    👋 مرحباً
                    <b>{{ user['username'] }}</b>

                </div>

                <h2>
                    👤 حسابي
                </h2>

                <p>
                    👤 المستخدم:
                    <b>{{ user['username'] }}</b>
                </p>

                <p>
                    📧 الإيميل:
                    <b>
                        {{ user['email'] or 'غير موجود' }}
                    </b>
                </p>

                <p>
                    📱 رقم الهاتف:
                    <b>
                        {{ user['phone'] or 'غير موجود' }}
                    </b>
                </p>

                <hr>

                <div class="admin-stats">

                    <div class="stat">

                        <div style="font-size:28px;">
                            📢
                        </div>

                        <div class="stat-number">
                            {{ total_ads }}
                        </div>

                        <div>
                            الإعلانات
                        </div>

                    </div>

                    <div class="stat">

                        <div style="font-size:28px;">
                            👁️
                        </div>

                        <div class="stat-number">
                            {{ total_views }}
                        </div>

                        <div>
                            المشاهدات
                        </div>

                    </div>

                    <div class="stat">

                        <div style="font-size:28px;">
                            ❤️
                        </div>

                        <div class="stat-number">
                            {{ total_favorites }}
                        </div>

                        <div>
                            المفضلة
                        </div>

                    </div>

                    <div class="stat">

                        <div style="font-size:28px;">
                            🆔
                        </div>

                        <div class="stat-number">
                            {{ user['id'] }}
                        </div>

                        <div>
                            رقم الحساب
                        </div>

                    </div>

                </div>

                <hr>

                <h3>
                    📢 إعلاناتي
                </h3>

                {% for ad in ads %}

                    <div class="admin-card">

                        <h3>
                            {{ ad['title'] }}
                        </h3>

                        <p class="price">
                            💰 {{ ad['price'] }} د.ت
                        </p>

                        <p>
                            👁️ {{ ad['views'] or 0 }}
                            مشاهدة
                        </p>

                        {% if ad['status'] == 'sold' %}

                            <p class="status-sold">
                                🔴 تم البيع
                            </p>

                        {% else %}

                            <p class="status-available">
                                🟢 متوفر
                            </p>

                        {% endif %}

                        <a
                            class="btn"
                            href="/ad/{{ ad['id'] }}"
                        >
                            👁️ مشاهدة
                        </a>

                        {% if ad['status'] == 'available' %}

                            <a
                                class="btn btn-green"
                                href="/mark-sold/{{ ad['id'] }}"
                            >
                                ✅ مباع
                            </a>

                        {% else %}

                            <a
                                class="btn btn-blue"
                                href="/mark-available/{{ ad['id'] }}"
                            >
                                🔄 متوفر
                            </a>

                        {% endif %}

                        <a
                            class="btn btn-danger"
                            href="/delete/{{ ad['id'] }}"
                            onclick="
                                return confirm(
                                    'حذف الإعلان؟'
                                );
                            "
                        >
                            🗑️ حذف
                        </a>

                    </div>

                {% else %}

                    <p>
                        ما عندك حتى إعلان.
                    </p>

                {% endfor %}

                <br>

                <a
                    class="btn"
                    href="/messages"
                >
                    💬 الرسائل
                </a>

                <a
                    class="btn"
                    href="/favorites"
                >
                    ❤️ المفضلة
                </a>

                <a
                    class="btn"
                    href="/add"
                >
                    📢 نشر إعلان
                </a>

                {% if session.get("is_admin") %}

                    <a
                        class="btn btn-blue"
                        href="/admin"
                    >
                        🛡️ لوحة Admin
                    </a>

                {% endif %}

                <a
                    class="btn btn-danger"
                    href="/logout"
                >
                    🚪 خروج
                </a>

            </div>

        </div>

        """,
        user=user,
        ads=ads,
        total_ads=total_ads,
        total_views=total_views,
        total_favorites=total_favorites
    )


# =========================================================
# MESSAGES
# =========================================================

@app.route("/messages")
def messages():

    if not is_logged():
        return redirect("/login")

    current_user = session["user_id"]

    conn = get_db()

    users = conn.execute(
        """
        SELECT
            u.id,
            u.username,
            u.phone,

            (
                SELECT message
                FROM messages m
                WHERE
                    (
                        m.sender_id = ?
                        AND m.receiver_id = u.id
                    )
                    OR
                    (
                        m.sender_id = u.id
                        AND m.receiver_id = ?
                    )
                ORDER BY m.id DESC
                LIMIT 1
            ) AS last_message

        FROM users u

        WHERE u.id != ?
        AND u.username != ?

        ORDER BY u.username ASC
        """,
        (
            current_user,
            current_user,
            current_user,
            "so9na.com"
        )
    ).fetchall()

    conn.close()

    return render_template_string(
        STYLE + """

        <nav>

            <div class="nav-container">

                <div class="logo">
                    💬 الرسائل - Sou9na
                </div>

                <div class="nav-buttons">

                    <a href="/">
                        🏠 الرئيسية
                    </a>

                    <a href="/favorites">
                        ❤️ المفضلة
                    </a>

                    <a href="/profile">
                        👤 حسابي
                    </a>

                    <a href="/logout">
                        🚪 خروج
                    </a>

                </div>

            </div>

        </nav>

        <div class="container">

            <div class="form-box">

                <h2>
                    💬 مراسلات المستخدمين
                </h2>

                <p style="color:#777;">
                    هنا تظهر حسابات المستخدمين للمراسلة.
                </p>

                {% for user in users %}

                    <a
                        class="chat-user"
                        href="/chat/{{ user['id'] }}"
                    >

                        <b>
                            👤 {{ user['username'] }}
                        </b>

                        {% if user['phone'] %}

                            <br>

                            <small>
                                📱 {{ user['phone'] }}
                            </small>

                        {% endif %}

                        {% if user['last_message'] %}

                            <p style="
                                color:#777;
                                margin:7px 0 0;
                            ">
                                {{ user['last_message'][:80] }}
                            </p>

                        {% else %}

                            <p style="
                                color:#999;
                                margin:7px 0 0;
                            ">
                                لا توجد رسائل بعد
                            </p>

                        {% endif %}

                        <span style="
                            float:right;
                            color:#7c3aed;
                        ">
                            💬
                        </span>

                    </a>

                {% else %}

                    <div class="admin-card">

                        لا توجد حسابات أخرى للمراسلة حالياً.

                    </div>

                {% endfor %}

            </div>

        </div>

        """,
        users=users
    )


# =========================================================
# CHAT
# =========================================================

@app.route("/chat/<int:user_id>", methods=["GET", "POST"])
def chat(user_id):

    if not is_logged():
        return redirect("/login")

    current_user = session["user_id"]

    if user_id == current_user:
        return redirect("/messages")

    conn = get_db()

    receiver = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()

    if not receiver:

        conn.close()
        return redirect("/messages")

    # منع مراسلة حساب الأدمن الأساسي
    if receiver["username"] == "so9na.com":

        conn.close()
        return redirect("/messages")

    if request.method == "POST":

        message = request.form.get(
            "message",
            ""
        ).strip()

        if message:

            if len(message) > 2000:
                message = message[:2000]

            conn.execute(
                """
                INSERT INTO messages
                (
                    sender_id,
                    receiver_id,
                    message
                )
                VALUES (?, ?, ?)
                """,
                (
                    current_user,
                    user_id,
                    message
                )
            )

            conn.commit()

        conn.close()

        return redirect(
            "/chat/" + str(user_id)
        )

    messages_list = conn.execute(
        """
        SELECT
            messages.*,
            users.username
        FROM messages

        LEFT JOIN users
        ON messages.sender_id = users.id

        WHERE
            (
                messages.sender_id = ?
                AND messages.receiver_id = ?
            )
            OR
            (
                messages.sender_id = ?
                AND messages.receiver_id = ?
            )

        ORDER BY messages.id ASC
        """,
        (
            current_user,
            user_id,
            user_id,
            current_user
        )
    ).fetchall()

    conn.close()

    return render_template_string(
        STYLE + """

        <nav>

            <div class="nav-container">

                <div class="logo">
                    💬 {{ receiver['username'] }}
                </div>

                <div class="nav-buttons">

                    <a href="/messages">
                        💬 الرسائل
                    </a>

                    <a href="/">
                        🏠 الرئيسية
                    </a>

                </div>

            </div>

        </nav>

        <div class="container">

            <div class="chat-box">

                <div class="chat-header">

                    <b>
                        👤 {{ receiver['username'] }}
                    </b>

                    {% if receiver['phone'] %}

                        <div style="
                            font-size:12px;
                            margin-top:4px;
                        ">
                            📱 {{ receiver['phone'] }}
                        </div>

                    {% endif %}

                </div>

                <div
                    class="messages"
                    id="messages"
                >

                    {% for msg in messages_list %}

                        <div class="
                            message-row
                            {% if msg['sender_id'] == session.get('user_id') %}
                                mine
                            {% else %}
                                theirs
                            {% endif %}
                        ">

                            <div class="message-bubble">

                                {{ msg['message'] }}

                                <span class="message-time">
                                    {{ msg['created_at'] }}
                                </span>

                            </div>

                        </div>

                    {% else %}

                        <div style="
                            text-align:center;
                            color:#888;
                            margin-top:40px;
                        ">

                            👋 ابدأ المحادثة الآن

                        </div>

                    {% endfor %}

                </div>

                <form
                    method="POST"
                    class="message-form"
                >

                    <textarea
                        name="message"
                        class="message-input"
                        placeholder="اكتب رسالتك..."
                        rows="1"
                        maxlength="2000"
                        required
                    ></textarea>

                    <button type="submit">
                        إرسال
                    </button>

                </form>

            </div>

        </div>

        <script>

        const box =
            document.getElementById("messages");

        if (box) {
            box.scrollTop = box.scrollHeight;
        }

        </script>

        """,
        receiver=receiver,
        messages_list=messages_list
    )
# =========================================================
# ADMIN PANEL - النسخة المتقدمة
# =========================================================

ADMIN_ACTIONS = {
    "promote": "ترقية مستخدم إلى Admin",
    "demote": "إزالة صلاحية Admin",
    "ban": "حظر مستخدم",
    "unban": "رفع حظر مستخدم",
    "delete_user": "حذف حساب مستخدم",
    "delete_ad": "حذف إعلان",
    "feature_ad": "تمييز إعلان",
    "unfeature_ad": "إزالة تمييز إعلان",
    "report_done": "إغلاق تبليغ",
    "report_delete_ad": "حذف إعلان بسبب تبليغ",
}


def admin_error():
    return "ممنوع الدخول ❌", 403


@app.route("/admin")
def admin():
    if not admin_required():
        return admin_error()

    search = request.args.get("search", "").strip()
    user_filter = request.args.get("user_filter", "all").strip()
    ad_filter = request.args.get("ad_filter", "all").strip()
    report_filter = request.args.get("report_filter", "all").strip()

    conn = get_db()

    # إحصائيات موسعة
    stats = {
        "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "admins": conn.execute("SELECT COUNT(*) FROM users WHERE is_admin=1").fetchone()[0],
        "banned": conn.execute("SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0],
        "ads": conn.execute("SELECT COUNT(*) FROM ads").fetchone()[0],
        "available": conn.execute("SELECT COUNT(*) FROM ads WHERE status='available'").fetchone()[0],
        "sold": conn.execute("SELECT COUNT(*) FROM ads WHERE status='sold'").fetchone()[0],
        "featured": conn.execute("SELECT COUNT(*) FROM ads WHERE featured=1").fetchone()[0],
        "messages": conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
        "reports": conn.execute("SELECT COUNT(*) FROM reports WHERE status='pending'").fetchone()[0],
        "views": conn.execute("SELECT COALESCE(SUM(views),0) FROM ads").fetchone()[0],
    }

    # المستخدمون
    user_query = """
        SELECT id, username, email, phone, is_admin, is_banned,
               ban_reason, created_at, last_login
        FROM users
        WHERE 1=1
    """
    user_params = []

    if search:
        user_query += """
            AND (
                username LIKE ?
                OR email LIKE ?
                OR phone LIKE ?
            )
        """
        sv = "%" + search + "%"
        user_params.extend([sv, sv, sv])

    if user_filter == "admins":
        user_query += " AND is_admin=1"
    elif user_filter == "banned":
        user_query += " AND is_banned=1"
    elif user_filter == "normal":
        user_query += " AND is_admin=0 AND is_banned=0"

    user_query += " ORDER BY id DESC LIMIT 200"

    users = conn.execute(user_query, user_params).fetchall()

    # الإعلانات
    ad_query = """
        SELECT ads.*, users.username
        FROM ads
        LEFT JOIN users ON ads.user_id = users.id
        WHERE 1=1
    """
    ad_params = []

    if search:
        ad_query += """
            AND (
                ads.title LIKE ?
                OR ads.description LIKE ?
                OR ads.location LIKE ?
                OR users.username LIKE ?
            )
        """
        sv = "%" + search + "%"
        ad_params.extend([sv, sv, sv, sv])

    if ad_filter == "available":
        ad_query += " AND ads.status='available'"
    elif ad_filter == "sold":
        ad_query += " AND ads.status='sold'"
    elif ad_filter == "featured":
        ad_query += " AND ads.featured=1"

    ad_query += " ORDER BY ads.id DESC LIMIT 200"
    ads = conn.execute(ad_query, ad_params).fetchall()

    # التبليغات
    report_query = """
        SELECT
            reports.*,
            ads.title AS ad_title,
            ads.user_id AS ad_owner_id,
            users.username AS reporter_username
        FROM reports
        LEFT JOIN ads ON reports.ad_id = ads.id
        LEFT JOIN users ON reports.reporter_id = users.id
        WHERE 1=1
    """
    report_params = []

    if report_filter == "pending":
        report_query += " AND reports.status='pending'"
    elif report_filter == "done":
        report_query += " AND reports.status='done'"

    report_query += " ORDER BY reports.id DESC LIMIT 200"
    reports = conn.execute(report_query, report_params).fetchall()

    logs = conn.execute("""
        SELECT admin_logs.*, users.username AS admin_username
        FROM admin_logs
        LEFT JOIN users ON admin_logs.admin_id = users.id
        ORDER BY admin_logs.id DESC
        LIMIT 50
    """).fetchall()

    conn.close()

    return render_template_string(
        STYLE + """
        <style>
        .admin-topbar {
            display:flex; gap:8px; flex-wrap:wrap; align-items:center;
            margin-bottom:12px;
        }
        .admin-filter {
            background:white; padding:12px; border-radius:13px;
            box-shadow:0 2px 8px #0001; margin-bottom:12px;
        }
        .admin-grid {
            display:grid; grid-template-columns:repeat(2,minmax(0,1fr));
            gap:8px;
        }
        .admin-small {
            font-size:12px; color:#666; line-height:1.6;
        }
        .badge {
            display:inline-block; padding:5px 8px; border-radius:999px;
            font-size:12px; font-weight:bold; margin:2px;
            background:#f3e8ff; color:#6d28d9;
        }
        .badge-danger { background:#fee2e2; color:#991b1b; }
        .badge-green { background:#dcfce7; color:#166534; }
        .badge-orange { background:#ffedd5; color:#9a3412; }
        .admin-actions form { display:inline-block; margin:2px; }
        .admin-actions button { font-size:13px; padding:9px 11px; }
        .log-item {
            background:#f8f7ff; padding:10px; border-radius:10px;
            margin:6px 0; font-size:13px;
        }
        @media(max-width:600px){
            .admin-grid{grid-template-columns:1fr;}
        }
        </style>

        <nav>
            <div class="nav-container">
                <div class="logo">🛡️ Sou9na Admin</div>
                <div class="nav-buttons">
                    <a href="/">🏠 الرئيسية</a>
                    <a href="/profile">👤 حسابي</a>
                    <a href="/logout">🚪 خروج</a>
                </div>
            </div>
        </nav>

        <div class="container">

            <div class="admin-header">
                <h1>🛡️ لوحة التحكم المتقدمة</h1>
                <p>مرحباً <b>{{ session.get("username") }}</b></p>
                <p class="admin-small" style="color:#eee;">
                    إدارة المستخدمين والإعلانات والتبليغات ومراقبة نشاط الإدارة.
                </p>
            </div>

            <div class="admin-grid">
                <div class="stat">👥<div class="stat-number">{{ stats.users }}</div>المستخدمين</div>
                <div class="stat">🛡️<div class="stat-number">{{ stats.admins }}</div>Admins</div>
                <div class="stat">🚫<div class="stat-number">{{ stats.banned }}</div>الموقوفين</div>
                <div class="stat">📢<div class="stat-number">{{ stats.ads }}</div>الإعلانات</div>
                <div class="stat">🟢<div class="stat-number">{{ stats.available }}</div>متوفرة</div>
                <div class="stat">🔴<div class="stat-number">{{ stats.sold }}</div>مباعة</div>
                <div class="stat">⭐<div class="stat-number">{{ stats.featured }}</div>مميزة</div>
                <div class="stat">👁️<div class="stat-number">{{ stats.views }}</div>المشاهدات</div>
                <div class="stat">💬<div class="stat-number">{{ stats.messages }}</div>الرسائل</div>
                <div class="stat">🚨<div class="stat-number">{{ stats.reports }}</div>تبليغات معلقة</div>
            </div>

            <div class="admin-filter">
                <h3>🔎 بحث وفلاتر</h3>
                <form method="GET">
                    <input name="search" value="{{ search }}"
                           placeholder="ابحث باسم المستخدم أو الإيميل أو الهاتف أو الإعلان...">

                    <select name="user_filter">
                        <option value="all" {% if user_filter=="all" %}selected{% endif %}>👥 كل المستخدمين</option>
                        <option value="admins" {% if user_filter=="admins" %}selected{% endif %}>🛡️ Admin فقط</option>
                        <option value="banned" {% if user_filter=="banned" %}selected{% endif %}>🚫 الموقوفين</option>
                        <option value="normal" {% if user_filter=="normal" %}selected{% endif %}>👤 عاديين</option>
                    </select>

                    <select name="ad_filter">
                        <option value="all" {% if ad_filter=="all" %}selected{% endif %}>📢 كل الإعلانات</option>
                        <option value="available" {% if ad_filter=="available" %}selected{% endif %}>🟢 متوفرة</option>
                        <option value="sold" {% if ad_filter=="sold" %}selected{% endif %}>🔴 مباعة</option>
                        <option value="featured" {% if ad_filter=="featured" %}selected{% endif %}>⭐ مميزة</option>
                    </select>

                    <select name="report_filter">
                        <option value="all" {% if report_filter=="all" %}selected{% endif %}>🚨 كل التبليغات</option>
                        <option value="pending" {% if report_filter=="pending" %}selected{% endif %}>⏳ معلقة</option>
                        <option value="done" {% if report_filter=="done" %}selected{% endif %}>✅ تمت المراجعة</option>
                    </select>

                    <button type="submit">🔎 تطبيق</button>
                    <a class="btn btn-gray" href="/admin">إعادة ضبط</a>
                </form>
            </div>

            <h2>👥 إدارة المستخدمين</h2>
            {% for user in users %}
                <div class="user-admin-card">
                    <h3>👤 {{ user["username"] }}</h3>
                    <p>🆔 {{ user["id"] }} &nbsp; 📧 {{ user["email"] or "بدون إيميل" }}</p>
                    <p>📱 {{ user["phone"] or "بدون هاتف" }}</p>
                    <p class="admin-small">
                        📅 التسجيل: {{ user["created_at"] or "غير معروف" }}<br>
                        🕒 آخر دخول: {{ user["last_login"] or "لم يدخل بعد" }}
                    </p>

                    {% if user["is_admin"] %}
                        <span class="badge">🛡️ Admin</span>
                    {% else %}
                        <span class="badge">👤 مستخدم</span>
                    {% endif %}

                    {% if user["is_banned"] %}
                        <span class="badge badge-danger">🚫 موقوف</span>
                        {% if user["ban_reason"] %}
                            <p>سبب الإيقاف: <b>{{ user["ban_reason"] }}</b></p>
                        {% endif %}
                    {% endif %}

                    <div class="admin-actions">
                        {% if user["username"] == "so9na.com" %}
                            <span class="badge badge-orange">👑 الأدمن الأساسي — محمي</span>
                        {% else %}
                            {% if user["is_admin"] %}
                                <form method="POST" action="/admin/demote/{{ user['id'] }}">
                                    <button class="btn btn-orange" type="submit"
                                            onclick="return confirm('تنحي صلاحية Admin؟')">👤 نحي Admin</button>
                                </form>
                            {% else %}
                                <form method="POST" action="/admin/promote/{{ user['id'] }}">
                                    <button class="btn btn-green" type="submit"
                                            onclick="return confirm('تعطيه صلاحية Admin؟')">🛡️ أعطي Admin</button>
                                </form>
                            {% endif %}

                            {% if user["is_banned"] %}
                                <form method="POST" action="/admin/unban/{{ user['id'] }}">
                                    <button class="btn btn-blue" type="submit">🔓 رفع الحظر</button>
                                </form>
                            {% else %}
                                <form method="POST" action="/admin/ban/{{ user['id'] }}">
                                    <input type="text" name="reason" maxlength="200"
                                           placeholder="سبب الحظر" required>
                                    <button class="btn btn-orange" type="submit"
                                            onclick="return confirm('متأكد تحب توقف الحساب؟')">🚫 إيقاف</button>
                                </form>
                            {% endif %}

                            <form method="POST" action="/admin/delete-user/{{ user['id'] }}">
                                <button class="btn btn-danger" type="submit"
                                        onclick="return confirm('الحذف نهائي. متأكد؟')">🗑️ حذف</button>
                            </form>
                        {% endif %}
                    </div>
                </div>
            {% else %}
                <div class="admin-card">ما فماش مستخدمين مطابقين.</div>
            {% endfor %}

            <hr>
            <h2>📢 إدارة الإعلانات</h2>
            {% for ad in ads %}
                <div class="admin-card">
                    <h3>{{ ad["title"] }}</h3>
                    <p class="price">💰 {{ ad["price"] }} د.ت</p>
                    <p>📂 {{ ad["category"] }} • 📍 {{ ad["location"] }}</p>
                    <p>👤 {{ ad["username"] or "غير معروف" }} • 👁️ {{ ad["views"] or 0 }}</p>

                    {% if ad["status"] == "sold" %}
                        <span class="badge badge-danger">🔴 مباع</span>
                    {% else %}
                        <span class="badge badge-green">🟢 متوفر</span>
                    {% endif %}

                    {% if ad["featured"] %}
                        <span class="badge badge-orange">⭐ مميز</span>
                    {% endif %}

                    <div class="admin-actions">
                        <a class="btn btn-blue" href="/ad/{{ ad['id'] }}">👁️ مشاهدة</a>

                        {% if ad["featured"] %}
                            <form method="POST" action="/admin/unfeature-ad/{{ ad['id'] }}">
                                <button class="btn btn-orange" type="submit">☆ إزالة التمييز</button>
                            </form>
                        {% else %}
                            <form method="POST" action="/admin/feature-ad/{{ ad['id'] }}">
                                <button class="btn btn-green" type="submit">⭐ تمييز</button>
                            </form>
                        {% endif %}

                        <form method="POST" action="/admin/delete-ad/{{ ad['id'] }}">
                            <button class="btn btn-danger" type="submit"
                                    onclick="return confirm('حذف الإعلان نهائياً؟')">🗑️ حذف</button>
                        </form>
                    </div>
                </div>
            {% else %}
                <div class="admin-card">ما فماش إعلانات مطابقة.</div>
            {% endfor %}

            <hr>
            <h2>🚨 مراجعة التبليغات</h2>
            {% for report in reports %}
                <div class="report-card {% if report['status']=='done' %}report-done{% endif %}">
                    <h3>🚨 {{ report["reason"] }}</h3>
                    <p>📢 الإعلان: <b>{{ report["ad_title"] or "محذوف" }}</b></p>
                    <p>👤 المبلّغ: {{ report["reporter_username"] or "غير معروف" }}</p>
                    <p>📝 {{ report["details"] or "بدون تفاصيل" }}</p>
                    <p>الحالة:
                        {% if report["status"] == "pending" %}
                            <span class="badge badge-orange">⏳ معلقة</span>
                        {% else %}
                            <span class="badge badge-green">✅ تمت المراجعة</span>
                        {% endif %}
                    </p>

                    {% if report["status"] == "pending" %}
                        <form method="POST" action="/admin/report-done/{{ report['id'] }}" style="display:inline;">
                            <button class="btn btn-green" type="submit">✅ تمت المراجعة</button>
                        </form>

                        {% if report["ad_id"] %}
                            <form method="POST" action="/admin/report-delete-ad/{{ report['id'] }}" style="display:inline;">
                                <button class="btn btn-danger" type="submit"
                                        onclick="return confirm('تحب تحذف الإعلان بسبب التبليغ؟')">🗑️ حذف الإعلان</button>
                            </form>
                        {% endif %}
                    {% endif %}
                </div>
            {% else %}
                <div class="admin-card">ما فماش تبليغات.</div>
            {% endfor %}

            <hr>
            <h2>📋 سجل عمليات الإدارة</h2>
            <div class="admin-card">
                {% for log in logs %}
                    <div class="log-item">
                        <b>{{ log["admin_username"] or "Admin محذوف" }}</b>
                        — {{ log["action"] }}
                        {% if log["details"] %}<br>{{ log["details"] }}{% endif %}
                        <div class="admin-small">{{ log["created_at"] }}</div>
                    </div>
                {% else %}
                    ما فماش عمليات مسجلة.
                {% endfor %}
            </div>

        </div>
        """,
        stats=stats,
        users=users,
        ads=ads,
        reports=reports,
        logs=logs,
        search=search,
        user_filter=user_filter,
        ad_filter=ad_filter,
        report_filter=report_filter
    )


# =========================================================
# ADMIN: PROMOTE / DEMOTE
# =========================================================

@app.route("/admin/promote/<int:user_id>", methods=["POST"])
def admin_promote(user_id):
    if not admin_required():
        return admin_error()

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    if user and user["username"] != "so9na.com":
        conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (user_id,))
        conn.commit()
        log_admin_action(
            ADMIN_ACTIONS["promote"], "user", user_id,
            "المستخدم: " + str(user["username"])
        )

    conn.close()
    return redirect("/admin")


@app.route("/admin/demote/<int:user_id>", methods=["POST"])
def admin_demote(user_id):
    if not admin_required():
        return admin_error()

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    if user and user["username"] != "so9na.com" and user_id != session.get("user_id"):
        conn.execute("UPDATE users SET is_admin=0 WHERE id=?", (user_id,))
        conn.commit()
        log_admin_action(
            ADMIN_ACTIONS["demote"], "user", user_id,
            "المستخدم: " + str(user["username"])
        )

    conn.close()
    return redirect("/admin")


# =========================================================
# ADMIN: BAN / UNBAN
# =========================================================

@app.route("/admin/ban/<int:user_id>", methods=["POST"])
def admin_ban_user(user_id):
    if not admin_required():
        return admin_error()

    reason = request.form.get("reason", "").strip()[:200]

    if not reason:
        return redirect("/admin")

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    if user and user["username"] != "so9na.com" and user_id != session.get("user_id"):
        conn.execute(
            "UPDATE users SET is_banned=1, ban_reason=? WHERE id=?",
            (reason, user_id)
        )
        conn.commit()
        log_admin_action(
            ADMIN_ACTIONS["ban"], "user", user_id,
            "المستخدم: " + str(user["username"]) + " | السبب: " + reason
        )

    conn.close()
    return redirect("/admin")


@app.route("/admin/unban/<int:user_id>", methods=["POST"])
def admin_unban_user(user_id):
    if not admin_required():
        return admin_error()

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    if user and user["username"] != "so9na.com":
        conn.execute(
            "UPDATE users SET is_banned=0, ban_reason='' WHERE id=?",
            (user_id,)
        )
        conn.commit()
        log_admin_action(
            ADMIN_ACTIONS["unban"], "user", user_id,
            "المستخدم: " + str(user["username"])
        )

    conn.close()
    return redirect("/admin")


# =========================================================
# ADMIN: FEATURE / DELETE AD
# =========================================================

@app.route("/admin/feature-ad/<int:ad_id>", methods=["POST"])
def admin_feature_ad(ad_id):
    if not admin_required():
        return admin_error()

    conn = get_db()
    ad = conn.execute("SELECT id, title FROM ads WHERE id=?", (ad_id,)).fetchone()

    if ad:
        conn.execute("UPDATE ads SET featured=1 WHERE id=?", (ad_id,))
        conn.commit()
        log_admin_action(
            ADMIN_ACTIONS["feature_ad"], "ad", ad_id,
            "الإعلان: " + str(ad["title"])
        )

    conn.close()
    return redirect("/admin")


@app.route("/admin/unfeature-ad/<int:ad_id>", methods=["POST"])
def admin_unfeature_ad(ad_id):
    if not admin_required():
        return admin_error()

    conn = get_db()
    ad = conn.execute("SELECT id, title FROM ads WHERE id=?", (ad_id,)).fetchone()

    if ad:
        conn.execute("UPDATE ads SET featured=0 WHERE id=?", (ad_id,))
        conn.commit()
        log_admin_action(
            ADMIN_ACTIONS["unfeature_ad"], "ad", ad_id,
            "الإعلان: " + str(ad["title"])
        )

    conn.close()
    return redirect("/admin")


@app.route("/admin/delete-ad/<int:ad_id>", methods=["POST"])
def admin_delete_ad(ad_id):
    if not admin_required():
        return admin_error()

    conn = get_db()
    ad = conn.execute("SELECT * FROM ads WHERE id=?", (ad_id,)).fetchone()

    if not ad:
        conn.close()
        return redirect("/admin")

    # حذف الصور
    if ad["image"]:
        for filename in ad["image"].split("|"):
            if not filename:
                continue
            path = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    conn.execute("DELETE FROM reports WHERE ad_id=?", (ad_id,))
    conn.execute("DELETE FROM favorites WHERE ad_id=?", (ad_id,))
    conn.execute("DELETE FROM ads WHERE id=?", (ad_id,))
    conn.commit()

    log_admin_action(
        ADMIN_ACTIONS["delete_ad"], "ad", ad_id,
        "الإعلان: " + str(ad["title"])
    )

    conn.close()
    return redirect("/admin")


# =========================================================
# ADMIN: REPORT ACTIONS
# =========================================================

@app.route("/admin/report-done/<int:report_id>", methods=["POST"])
def admin_report_done(report_id):
    if not admin_required():
        return admin_error()

    conn = get_db()
    report = conn.execute(
        "SELECT id FROM reports WHERE id=?",
        (report_id,)
    ).fetchone()

    if report:
        conn.execute(
            "UPDATE reports SET status='done' WHERE id=?",
            (report_id,)
        )
        conn.commit()
        log_admin_action(
            ADMIN_ACTIONS["report_done"], "report", report_id
        )

    conn.close()
    return redirect("/admin")


@app.route("/admin/report-delete-ad/<int:report_id>", methods=["POST"])
def admin_report_delete_ad(report_id):
    if not admin_required():
        return admin_error()

    conn = get_db()
    report = conn.execute(
        """
        SELECT reports.id, reports.ad_id, ads.title, ads.image
        FROM reports
        LEFT JOIN ads ON reports.ad_id = ads.id
        WHERE reports.id=?
        """,
        (report_id,)
    ).fetchone()

    if not report:
        conn.close()
        return redirect("/admin")

    ad_id = report["ad_id"]

    if ad_id:
        if report["image"]:
            for filename in report["image"].split("|"):
                if not filename:
                    continue
                path = os.path.join(UPLOAD_FOLDER, filename)
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass

        conn.execute("DELETE FROM reports WHERE ad_id=?", (ad_id,))
        conn.execute("DELETE FROM favorites WHERE ad_id=?", (ad_id,))
        conn.execute("DELETE FROM ads WHERE id=?", (ad_id,))

    conn.execute("UPDATE reports SET status='done' WHERE id=?", (report_id,))
    conn.commit()

    log_admin_action(
        ADMIN_ACTIONS["report_delete_ad"], "report", report_id,
        "حذف الإعلان: " + str(report["title"] or "محذوف")
    )

    conn.close()
    return redirect("/admin")


# =========================================================
# ADMIN: DELETE USER
# =========================================================

@app.route("/admin/delete-user/<int:user_id>", methods=["POST"])
def admin_delete_user(user_id):
    if not admin_required():
        return admin_error()

    if user_id == session.get("user_id"):
        return redirect("/admin")

    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE id=?",
        (user_id,)
    ).fetchone()

    if not user or user["username"] == "so9na.com":
        conn.close()
        return redirect("/admin")

    # حذف صور إعلانات المستخدم
    ads = conn.execute(
        "SELECT image FROM ads WHERE user_id=?",
        (user_id,)
    ).fetchall()

    for ad in ads:
        if ad["image"]:
            for filename in ad["image"].split("|"):
                if not filename:
                    continue
                path = os.path.join(UPLOAD_FOLDER, filename)
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass

    conn.execute("DELETE FROM reports WHERE reporter_id=?", (user_id,))
    conn.execute(
        """
        DELETE FROM reports
        WHERE ad_id IN (SELECT id FROM ads WHERE user_id=?)
        """,
        (user_id,)
    )
    conn.execute("DELETE FROM favorites WHERE user_id=?", (user_id,))
    conn.execute(
        """
        DELETE FROM favorites
        WHERE ad_id IN (SELECT id FROM ads WHERE user_id=?)
        """,
        (user_id,)
    )
    conn.execute("DELETE FROM ads WHERE user_id=?", (user_id,))
    conn.execute(
        "DELETE FROM messages WHERE sender_id=? OR receiver_id=?",
        (user_id, user_id)
    )
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()

    log_admin_action(
        ADMIN_ACTIONS["delete_user"], "user", user_id,
        "المستخدم: " + str(user["username"])
    )

    conn.close()
    return redirect("/admin")


# =========================================================
# ULTRA V3 - PERFORMANCE / MONITORING / ADMIN API
# =========================================================

def ensure_ultra_v3_db():
    """Create optional indexes and an admin audit table."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS admin_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            action TEXT NOT NULL,
            target_type TEXT,
            target_id INTEGER,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)",
        "CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone)",
        "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
        "CREATE INDEX IF NOT EXISTS idx_ads_user ON ads(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_ads_status ON ads(status)",
        "CREATE INDEX IF NOT EXISTS idx_ads_category ON ads(category)",
        "CREATE INDEX IF NOT EXISTS idx_ads_created ON ads(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_messages_receiver ON messages(receiver_id)",
        "CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status)",
        "CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id)",
    ]
    for sql in indexes:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


def ultra_admin_required():
    return bool(session.get("user_id") and session.get("is_admin"))


def ultra_audit(action, target_type=None, target_id=None, details=""):
    try:
        conn = get_db()
        conn.execute("""
            INSERT INTO admin_audit
            (admin_id, action, target_type, target_id, details)
            VALUES (?, ?, ?, ?, ?)
        """, (
            session.get("user_id"),
            action,
            target_type,
            target_id,
            details[:1000]
        ))
        conn.commit()
        conn.close()
    except Exception:
        pass


@app.after_request
def ultra_headers(response):
    # Lightweight security/performance headers.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


@app.route("/health")
def ultra_health():
    """Simple health check for hosting providers."""
    try:
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return jsonify({
            "status": "ok",
            "service": "Sou9na",
            "version": "Ultra V3"
        })
    except Exception:
        return jsonify({"status": "error"}), 500


@app.route("/admin/api/stats")
def ultra_admin_stats():
    if not ultra_admin_required():
        return jsonify({"error": "forbidden"}), 403

    conn = get_db()
    stats = {
        "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "admins": conn.execute(
            "SELECT COUNT(*) FROM users WHERE is_admin=1"
        ).fetchone()[0],
        "ads": conn.execute("SELECT COUNT(*) FROM ads").fetchone()[0],
        "available_ads": conn.execute(
            "SELECT COUNT(*) FROM ads WHERE status='available'"
        ).fetchone()[0],
        "sold_ads": conn.execute(
            "SELECT COUNT(*) FROM ads WHERE status='sold'"
        ).fetchone()[0],
        "views": conn.execute(
            "SELECT COALESCE(SUM(views),0) FROM ads"
        ).fetchone()[0],
        "messages": conn.execute(
            "SELECT COUNT(*) FROM messages"
        ).fetchone()[0],
        "pending_reports": conn.execute(
            "SELECT COUNT(*) FROM reports WHERE status='pending'"
        ).fetchone()[0],
        "favorites": conn.execute(
            "SELECT COUNT(*) FROM favorites"
        ).fetchone()[0],
    }
    conn.close()
    return jsonify(stats)


@app.route("/admin/api/search")
def ultra_admin_search():
    if not ultra_admin_required():
        return jsonify({"error": "forbidden"}), 403

    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"users": [], "ads": []})

    like = "%" + q + "%"
    conn = get_db()

    users = conn.execute("""
        SELECT id, username, phone, email, is_admin
        FROM users
        WHERE username LIKE ?
           OR phone LIKE ?
           OR email LIKE ?
        ORDER BY id DESC
        LIMIT 50
    """, (like, like, like)).fetchall()

    ads = conn.execute("""
        SELECT ads.id, ads.title, ads.price, ads.category,
               ads.location, ads.status, users.username
        FROM ads
        LEFT JOIN users ON ads.user_id = users.id
        WHERE ads.title LIKE ?
           OR ads.description LIKE ?
           OR ads.category LIKE ?
           OR ads.location LIKE ?
           OR users.username LIKE ?
        ORDER BY ads.id DESC
        LIMIT 50
    """, (like, like, like, like, like)).fetchall()

    conn.close()

    return jsonify({
        "users": [dict(x) for x in users],
        "ads": [dict(x) for x in ads]
    })


@app.route("/admin/api/audit")
def ultra_admin_audit():
    if not ultra_admin_required():
        return jsonify({"error": "forbidden"}), 403

    conn = get_db()
    rows = conn.execute("""
        SELECT admin_audit.*,
               users.username AS admin_username
        FROM admin_audit
        LEFT JOIN users ON users.id = admin_audit.admin_id
        ORDER BY admin_audit.id DESC
        LIMIT 100
    """).fetchall()
    conn.close()

    return jsonify({"audit": [dict(x) for x in rows]})


# Maintenance mode can be enabled on the hosting panel with:
# SOU9NA_MAINTENANCE=1
@app.before_request
def ultra_maintenance():
    if os.environ.get("SOU9NA_MAINTENANCE") == "1":
        allowed = {
            "/login", "/logout", "/health", "/static/favicon.ico"
        }
        if request.path not in allowed and not session.get("is_admin"):
            return """
            <div style="font-family:Arial;text-align:center;padding:70px">
                <h1>🛠️ الموقع تحت الصيانة</h1>
                <p>نرجعولك قريباً.</p>
            </div>
            """, 503


# Initialize optional V3 database improvements.
ensure_ultra_v3_db()


# =========================================================
# ADMIN PRO V4 - PROFESSIONAL DASHBOARD
# =========================================================

@app.route("/admin/pro")
def admin_pro():
    if not ultra_admin_required():
        return "ممنوع الدخول ❌", 403

    conn = get_db()

    stats = {
        "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "admins": conn.execute("SELECT COUNT(*) FROM users WHERE is_admin=1").fetchone()[0],
        "ads": conn.execute("SELECT COUNT(*) FROM ads").fetchone()[0],
        "views": conn.execute("SELECT COALESCE(SUM(views),0) FROM ads").fetchone()[0],
        "messages": conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
        "reports": conn.execute(
            "SELECT COUNT(*) FROM reports WHERE status='pending'"
        ).fetchone()[0],
        "favorites": conn.execute("SELECT COUNT(*) FROM favorites").fetchone()[0]
    }

    category_rows = conn.execute("""
        SELECT category, COUNT(*) AS total
        FROM ads
        GROUP BY category
        ORDER BY total DESC
        LIMIT 10
    """).fetchall()

    status_rows = conn.execute("""
        SELECT status, COUNT(*) AS total
        FROM ads
        GROUP BY status
    """).fetchall()

    daily_rows = conn.execute("""
        SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS total
        FROM ads
        GROUP BY day
        ORDER BY day DESC
        LIMIT 14
    """).fetchall()
    daily_rows = list(reversed(daily_rows))

    user_daily_rows = conn.execute("""
        SELECT substr(rowid, 1, 10) AS dummy, COUNT(*) AS total
        FROM users
        GROUP BY dummy
        LIMIT 0
    """).fetchall()

    recent_users = conn.execute("""
        SELECT id, username, phone, email, is_admin
        FROM users
        ORDER BY id DESC
        LIMIT 8
    """).fetchall()

    recent_ads = conn.execute("""
        SELECT ads.id, ads.title, ads.price, ads.status,
               ads.views, users.username
        FROM ads
        LEFT JOIN users ON users.id = ads.user_id
        ORDER BY ads.id DESC
        LIMIT 8
    """).fetchall()

    conn.close()

    chart_categories = [
        {"label": r["category"], "total": r["total"]}
        for r in category_rows
    ]
    chart_status = [
        {"label": r["status"], "total": r["total"]}
        for r in status_rows
    ]
    chart_daily = [
        {"day": r["day"], "total": r["total"]}
        for r in daily_rows
    ]

    return render_template_string(
        STYLE + """
        <style>
        .pro-wrap{max-width:1200px;margin:auto;padding:18px}
        .pro-top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
        .pro-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin:18px 0}
        .pro-stat,.pro-card{background:white;border-radius:18px;padding:18px;box-shadow:0 6px 22px rgba(0,0,0,.07)}
        .pro-stat b{display:block;font-size:28px;margin-top:7px}
        .chart-box{height:300px;position:relative}
        .bar-chart{display:flex;align-items:flex-end;height:230px;gap:10px;padding:15px 5px 0}
        .bar-item{flex:1;min-width:20px;text-align:center}
        .bar{width:100%;border-radius:8px 8px 2px 2px;background:#6c5ce7;min-height:4px}
        .bar-item small{display:block;font-size:11px;margin-top:6px;overflow:hidden;text-overflow:ellipsis}
        .line-chart{height:230px;display:flex;align-items:flex-end;gap:6px;padding:10px}
        .line-point{flex:1;text-align:center}
        .line-dot{margin:auto;width:13px;height:13px;border-radius:50%;background:#20a36a}
        .table-wrap{overflow:auto}
        table{width:100%;border-collapse:collapse}
        th,td{padding:10px;border-bottom:1px solid #eee;text-align:right}
        .badge{display:inline-block;padding:5px 9px;border-radius:999px;background:#eee}
        .ok{background:#dff7e8;color:#18794e}.warn{background:#fff1c9;color:#8a6500}
        @media(max-width:600px){.pro-wrap{padding:10px}.pro-stat b{font-size:23px}}
        </style>

        <div class="pro-wrap">
            <div class="pro-top">
                <div>
                    <h1>🛡️ لوحة Admin Pro</h1>
                    <p>مراقبة الموقع والإحصائيات في مكان واحد</p>
                </div>
                <a class="btn" href="/admin">← لوحة الإدارة</a>
            </div>

            <div class="pro-grid">
                <div class="pro-stat">👥 المستخدمين<b>{{ stats.users }}</b></div>
                <div class="pro-stat">🛡️ الأدمن<b>{{ stats.admins }}</b></div>
                <div class="pro-stat">📢 الإعلانات<b>{{ stats.ads }}</b></div>
                <div class="pro-stat">👁️ المشاهدات<b>{{ stats.views }}</b></div>
                <div class="pro-stat">💬 الرسائل<b>{{ stats.messages }}</b></div>
                <div class="pro-stat">🚨 تبليغات معلقة<b>{{ stats.reports }}</b></div>
                <div class="pro-stat">❤️ المفضلة<b>{{ stats.favorites }}</b></div>
            </div>

            <div class="pro-card">
                <h2>📈 الإعلانات المنشورة حسب الأيام</h2>
                <div class="chart-box">
                    <div class="bar-chart">
                    {% set maxv = (chart_daily|map(attribute='total')|list|max if chart_daily else 1) %}
                    {% for x in chart_daily %}
                        <div class="bar-item">
                            <div class="bar" style="height:{{ ((x.total / maxv) * 210)|int }}px" title="{{ x.total }}"></div>
                            <small>{{ x.day[5:] }}</small>
                        </div>
                    {% endfor %}
                    </div>
                </div>
            </div>

            <br>

            <div class="pro-grid" style="grid-template-columns:repeat(auto-fit,minmax(320px,1fr))">
                <div class="pro-card">
                    <h2>📊 الإعلانات حسب التصنيف</h2>
                    {% set maxc = (chart_categories|map(attribute='total')|list|max if chart_categories else 1) %}
                    {% for x in chart_categories %}
                        <div style="margin:10px 0">
                            <div style="display:flex;justify-content:space-between">
                                <span>{{ x.label }}</span><b>{{ x.total }}</b>
                            </div>
                            <div style="height:9px;background:#eee;border-radius:8px">
                                <div style="height:9px;border-radius:8px;background:#6c5ce7;width:{{ ((x.total/maxc)*100)|int }}%"></div>
                            </div>
                        </div>
                    {% else %}
                        <p>ما فماش بيانات.</p>
                    {% endfor %}
                </div>

                <div class="pro-card">
                    <h2>📌 حالة الإعلانات</h2>
                    {% for x in chart_status %}
                        <p style="display:flex;justify-content:space-between">
                            <span>{{ x.label }}</span>
                            <b class="badge">{{ x.total }}</b>
                        </p>
                    {% else %}
                        <p>ما فماش بيانات.</p>
                    {% endfor %}
                </div>
            </div>

            <br>

            <div class="pro-card">
                <h2>👥 آخر المستخدمين</h2>
                <div class="table-wrap">
                <table>
                    <tr><th>ID</th><th>المستخدم</th><th>الهاتف</th><th>الصلاحية</th></tr>
                    {% for u in recent_users %}
                    <tr>
                        <td>{{ u.id }}</td>
                        <td>{{ u.username }}</td>
                        <td>{{ u.phone or "-" }}</td>
                        <td>
                            {% if u.is_admin %}
                            <span class="badge ok">Admin</span>
                            {% else %}
                            <span class="badge">User</span>
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </table>
                </div>
            </div>

            <br>

            <div class="pro-card">
                <h2>📢 آخر الإعلانات</h2>
                <div class="table-wrap">
                <table>
                    <tr><th>ID</th><th>الإعلان</th><th>البائع</th><th>المشاهدات</th><th>الحالة</th></tr>
                    {% for a in recent_ads %}
                    <tr>
                        <td>{{ a.id }}</td>
                        <td>{{ a.title }}</td>
                        <td>{{ a.username or "-" }}</td>
                        <td>{{ a.views or 0 }}</td>
                        <td><span class="badge">{{ a.status }}</span></td>
                    </tr>
                    {% endfor %}
                </table>
                </div>
            </div>
        </div>
        """,
        stats=stats,
        chart_categories=chart_categories,
        chart_status=chart_status,
        chart_daily=chart_daily,
        recent_users=recent_users,
        recent_ads=recent_ads
    )



# =========================================================
# USERS PRO V5 - USER EXPERIENCE FEATURES
# =========================================================

def ensure_users_pro_v5_db():
    conn = get_db()

    tables = [
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            link TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS follows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            follower_id INTEGER NOT NULL,
            followed_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(follower_id, followed_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ad_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad_id INTEGER NOT NULL,
            viewer_id INTEGER,
            viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ]
    for sql in tables:
        conn.execute(sql)

    for sql in [
        "CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read)",
        "CREATE INDEX IF NOT EXISTS idx_follows_followed ON follows(followed_id)",
        "CREATE INDEX IF NOT EXISTS idx_views_ad ON ad_views(ad_id)",
    ]:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()


def user_notification(user_id, title, message, link="/"):
    try:
        conn = get_db()
        conn.execute("""
            INSERT INTO notifications(user_id,title,message,link)
            VALUES(?,?,?,?)
        """, (user_id, title[:100], message[:500], link))
        conn.commit()
        conn.close()
    except Exception:
        pass


@app.context_processor
def users_pro_context():
    if not session.get("user_id"):
        return {"unread_notifications": 0}
    try:
        conn = get_db()
        n = conn.execute("""
            SELECT COUNT(*) FROM notifications
            WHERE user_id=? AND is_read=0
        """, (session["user_id"],)).fetchone()[0]
        conn.close()
        return {"unread_notifications": n}
    except Exception:
        return {"unread_notifications": 0}


@app.route("/notifications")
def user_notifications():
    if not is_logged():
        return redirect("/login")

    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM notifications
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 100
    """, (session["user_id"],)).fetchall()
    conn.execute("""
        UPDATE notifications SET is_read=1
        WHERE user_id=?
    """, (session["user_id"],))
    conn.commit()
    conn.close()

    return render_template_string(
        STYLE + """
        <div class="container">
            <div class="form-box">
                <h2>🔔 إشعاراتي</h2>
                {% for n in rows %}
                <div class="admin-card">
                    <h3>{{ n.title }}</h3>
                    <p>{{ n.message }}</p>
                    <small>{{ n.created_at }}</small>
                    {% if n.link %}
                    <br><a class="btn btn-blue" href="{{ n.link }}">فتح</a>
                    {% endif %}
                </div>
                {% else %}
                <p>ما عندك حتى إشعار.</p>
                {% endfor %}
            </div>
        </div>
        """,
        rows=rows
    )


@app.route("/follow/<int:user_id>", methods=["POST", "GET"])
def follow_user(user_id):
    if not is_logged():
        return redirect("/login")

    me = session["user_id"]
    if me == user_id:
        return redirect(request.referrer or "/")

    conn = get_db()
    target = conn.execute(
        "SELECT id, username FROM users WHERE id=?", (user_id,)
    ).fetchone()

    if not target:
        conn.close()
        return redirect(request.referrer or "/")

    existing = conn.execute("""
        SELECT id FROM follows
        WHERE follower_id=? AND followed_id=?
    """, (me, user_id)).fetchone()

    if existing:
        conn.execute("DELETE FROM follows WHERE id=?", (existing["id"],))
    else:
        conn.execute("""
            INSERT INTO follows(follower_id, followed_id)
            VALUES(?,?)
        """, (me, user_id))
        conn.commit()
        conn.close()
        user_notification(
            user_id,
            "👤 متابع جديد",
            "شخص جديد بدا يتابع حسابك.",
            "/user/" + str(me)
        )
        return redirect(request.referrer or "/")

    conn.commit()
    conn.close()
    return redirect(request.referrer or "/")


@app.route("/user/<int:user_id>")
def public_user_profile(user_id):
    conn = get_db()
    user = conn.execute("""
        SELECT id, username, phone, email, is_admin
        FROM users WHERE id=?
    """, (user_id,)).fetchone()

    if not user:
        conn.close()
        return "المستخدم غير موجود", 404

    ads = conn.execute("""
        SELECT * FROM ads
        WHERE user_id=?
        ORDER BY id DESC
    """, (user_id,)).fetchall()

    followers = conn.execute(
        "SELECT COUNT(*) FROM follows WHERE followed_id=?",
        (user_id,)
    ).fetchone()[0]

    following = conn.execute(
        "SELECT COUNT(*) FROM follows WHERE follower_id=?",
        (user_id,)
    ).fetchone()[0]

    is_following = False
    if session.get("user_id"):
        is_following = bool(conn.execute("""
            SELECT id FROM follows
            WHERE follower_id=? AND followed_id=?
        """, (session["user_id"], user_id)).fetchone())

    conn.close()

    return render_template_string(
        STYLE + """
        <div class="container">
            <div class="form-box">
                <h2>👤 {{ user.username }}</h2>
                {% if user.is_admin %}<p>🛡️ Admin</p>{% endif %}

                <div class="admin-stats">
                    <div class="stat"><div class="stat-number">{{ followers }}</div>المتابعين</div>
                    <div class="stat"><div class="stat-number">{{ following }}</div>يتابع</div>
                    <div class="stat"><div class="stat-number">{{ ads|length }}</div>الإعلانات</div>
                </div>

                {% if session.get("user_id") and session.get("user_id") != user.id %}
                <form method="post" action="/follow/{{ user.id }}">
                    <button class="btn btn-blue" type="submit">
                        {% if is_following %}❌ إلغاء المتابعة{% else %}➕ متابعة{% endif %}
                    </button>
                </form>
                {% endif %}

                <hr>
                <h3>📢 إعلانات {{ user.username }}</h3>
                {% for ad in ads %}
                <div class="admin-card">
                    <h3>{{ ad.title }}</h3>
                    <p class="price">💰 {{ ad.price }} د.ت</p>
                    <p>📍 {{ ad.location }}</p>
                    <p>👁️ {{ ad.views or 0 }}</p>
                    <a class="btn" href="/ad/{{ ad.id }}">👁️ مشاهدة</a>
                </div>
                {% else %}
                <p>ما عندوش إعلانات.</p>
                {% endfor %}
            </div>
        </div>
        """,
        user=user, ads=ads, followers=followers,
        following=following, is_following=is_following
    )


@app.route("/my-activity")
def my_activity():
    if not is_logged():
        return redirect("/login")

    uid = session["user_id"]
    conn = get_db()

    ads_count = conn.execute(
        "SELECT COUNT(*) FROM ads WHERE user_id=?", (uid,)
    ).fetchone()[0]
    views = conn.execute("""
        SELECT COALESCE(SUM(views),0) FROM ads WHERE user_id=?
    """, (uid,)).fetchone()[0]
    favorites = conn.execute("""
        SELECT COUNT(*) FROM favorites f
        JOIN ads a ON a.id=f.ad_id
        WHERE a.user_id=?
    """, (uid,)).fetchone()[0]
    followers = conn.execute(
        "SELECT COUNT(*) FROM follows WHERE followed_id=?", (uid,)
    ).fetchone()[0]

    conn.close()

    return render_template_string(
        STYLE + """
        <div class="container">
            <div class="form-box">
                <h2>📊 نشاطي</h2>
                <div class="admin-stats">
                    <div class="stat">📢<div class="stat-number">{{ ads_count }}</div>إعلاناتي</div>
                    <div class="stat">👁️<div class="stat-number">{{ views }}</div>مشاهدات</div>
                    <div class="stat">❤️<div class="stat-number">{{ favorites }}</div>مفضلات</div>
                    <div class="stat">👥<div class="stat-number">{{ followers }}</div>متابعين</div>
                </div>
            </div>
        </div>
        """,
        ads_count=ads_count, views=views,
        favorites=favorites, followers=followers
    )


# Initialize V5 user features.
ensure_users_pro_v5_db()


# =========================================================
# START
# =========================================================

init_db()

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )