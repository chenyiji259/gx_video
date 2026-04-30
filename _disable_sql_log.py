import os
from pathlib import Path

def load_env(p):
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

load_env(Path(__file__).parent / ".env")

import psycopg2

conn = psycopg2.connect(
    host="8.134.170.191", port=5432,
    user="vidumuse", password=os.environ["POSTGRES_PASSWORD"],
    dbname="vidumuse", connect_timeout=10,
)
conn.autocommit = True
with conn.cursor() as cur:
    cur.execute("ALTER SYSTEM SET log_statement = 'none';")
    cur.execute("SELECT pg_reload_conf();")
    print("pg_reload_conf:", cur.fetchone())
conn.close()
print("完成：log_statement 已关闭，立即生效。")
