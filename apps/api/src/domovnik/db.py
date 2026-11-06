"""Minimální přístup k databázi (F0). Plná vrstva SQLAlchemy přijde ve F1."""

import psycopg


def check_database(url: str) -> bool:
    """Vrátí True, pokud se lze připojit k databázi a odpovídá na dotaz."""
    try:
        with psycopg.connect(url, connect_timeout=2) as conn:
            row = conn.execute("SELECT 1").fetchone()
            return row is not None and row[0] == 1
    except psycopg.Error:
        return False
