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
            visit_time TIMESTAMP
        )
    """)

    conn.commit()
    cur.close()
    conn.close()

init_db()

# 🔥 IP'yi alan yer burası
def get_ip():
    if request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0]
    return request.remote_addr

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/visit", methods=["POST"])
def visit():
    ip = get_ip()
    now = datetime.utcnow()

    conn = get_connection()
    cur = conn.cursor()

    # Daha önce gelmiş mi?
    cur.execute("SELECT id FROM visitors WHERE ip=%s", (ip,))
    exists = cur.fetchone()

    if not exists:
        cur.execute(
            "INSERT INTO visitors (ip, visit_time) VALUES (%s, %s)",
            (ip, now)
        )
        conn.commit()

    cur.execute("SELECT COUNT(DISTINCT ip) FROM visitors")
    total = cur.fetchone()[0]

    cur.close()
    conn.close()

    return jsonify({
        "ip": ip,
        "total": total
    })
