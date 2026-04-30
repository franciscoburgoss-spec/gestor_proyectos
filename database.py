import sqlite3
from pathlib import Path

DATABASE = Path(__file__).parent / "data" / "proyectos.db"
SCHEMA = Path(__file__).parent / "schema.sql"

def get_db():
    conn = sqlite3.connect(str(DATABASE))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    db = get_db()
    with open(SCHEMA, "r", encoding="utf-8") as f:
        db.executescript(f.read())
    db.commit()
    db.close()

if __name__ == "__main__":
    init_db()
    print("Base de datos inicializada en", DATABASE)
