from flask import Flask, request, jsonify, render_template
import psycopg2
import os
from datetime import datetime

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS visitors (
            id SERIAL PRIMARY KEY,
            ip TEXT,
            user_agent TEXT,
            first_visit TIMESTAMP
        )
    """)

    conn.commit()
    cur.close()
    conn.close()


init_db()


# Railway + Proxy + Cloudflare uyumlu IP alma
def get_ip():
    if request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0].strip()
    return request.remote_addr


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/visit", methods=["POST"])
def visit():
    ip = get_ip()
    user_agent = request.headers.get("User-Agent")
    now = datetime.utcnow()

    conn = get_connection()
    cur = conn.cursor()

    # Aynı kişi mi kontrolü (IP + cihaz)
    cur.execute(
        "SELECT id FROM visitors WHERE ip=%s AND user_agent=%s",
        (ip, user_agent)
    )
    exists = cur.fetchone()

    if not exists:
        cur.execute(
            "INSERT INTO visitors (ip, user_agent, first_visit) VALUES (%s, %s, %s)",
            (ip, user_agent, now)
        )
        conn.commit()

    # GLOBAL UNIQUE SAYI
    cur.execute("SELECT COUNT(*) FROM visitors")
    total = cur.fetchone()[0]

    cur.close()
    conn.close()

    return jsonify({
        "total": total
    })
