"""Cache layer using Turso (libsql)."""

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

# Check if user explicitly configured Turso
_TURSO_CONFIGURED = False
DB_URL = os.getenv("TURSO_DATABASE_URL")
DB_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN")

# If no env var set, default to local file but don't create it unless asked
if not DB_URL:
    DB_URL = "file:./cache.db"
    _DEFAULT_FILE = True
else:
    _DEFAULT_FILE = False


def _get_connection() -> sqlite3.Connection:
    """Get a connection to the Turso database."""
    global _TURSO_CONFIGURED
    
    if not DB_URL or ("TURSO_DATABASE_URL" in os.environ and not DB_URL.startswith("file:")):
        raise RuntimeError("TURSO_DATABASE_URL is not configured")
    
    if DB_URL.startswith("file:"):
        # Local file-based
        db_path = DB_URL.replace("file:", "")
        # Ensure directory exists
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    # Turso remote - check if turso is available
    try:
        from turso import connect
        _TURSO_CONFIGURED = True
        return connect(DB_URL, auth_token=DB_AUTH_TOKEN)
    except ImportError:
        raise RuntimeError("Turso package not installed. Run: pip install turso python-dotenv")


def init_cache() -> None:
    """Initialize the cache database schema."""
    global _TURSO_CONFIGURED
    
    # No DB URL configured at all
    if not DB_URL:
        _TURSO_CONFIGURED = False
        return
    
    # If using default local file (no env var set) and it doesn't exist, skip caching
    if _DEFAULT_FILE and not os.path.exists(DB_URL.replace("file:", "")):
        _TURSO_CONFIGURED = False
        return
    
    try:
        conn = _get_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at)
        """)
        conn.commit()
        conn.close()
        _TURSO_CONFIGURED = True
    except Exception as e:
        # Silently disable cache if initialization fails
        _TURSO_CONFIGURED = False


def get_cache(key: str) -> Optional[dict]:
    """Get a cached value if not expired."""
    global _TURSO_CONFIGURED
    
    # Cache disabled
    if not _TURSO_CONFIGURED:
        return None
    
    try:
        conn = _get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT value, expires_at FROM cache WHERE key = ? AND expires_at > ?",
            (key, datetime.now(timezone.utc).isoformat()),
        )
        row = cur.fetchone()
        conn.close()

        if row:
            import json
            return {"value": json.loads(row["value"]), "expires_at": row["expires_at"]}
        return None
    except Exception:
        # Cache read failed, disable cache and return None
        _TURSO_CONFIGURED = False
        return None


def set_cache(key: str, value: Any, ttl_seconds: int = 3600) -> None:
    """Cache a value with TTL (default 1 hour)."""
    global _TURSO_CONFIGURED
    
    # Cache disabled
    if not _TURSO_CONFIGURED:
        return
    
    try:
        import json

        conn = _get_connection()
        cur = conn.cursor()
        # Add TTL to current time
        from datetime import timedelta
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()

        cur.execute(
            "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
            (key, json.dumps(value), expires_at),
        )
        conn.commit()
        conn.close()
    except Exception:
        # Cache write failed, disable cache
        _TURSO_CONFIGURED = False


def delete_cache(key: str) -> None:
    """Delete a cached value."""
    global _TURSO_CONFIGURED
    
    if not _TURSO_CONFIGURED:
        return
    
    try:
        conn = _get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM cache WHERE key = ?", (key,))
        conn.commit()
        conn.close()
    except Exception:
        _TURSO_CONFIGURED = False


def cleanup_expired() -> int:
    """Remove expired entries. Returns count of removed entries."""
    global _TURSO_CONFIGURED
    
    if not _TURSO_CONFIGURED:
        return 0
    
    try:
        conn = _get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM cache WHERE expires_at <= ?", (datetime.now(timezone.utc).isoformat(),))
        count = cur.rowcount
        conn.commit()
        conn.close()
        return count
    except Exception:
        _TURSO_CONFIGURED = False
        return 0


def cache_key_from_url(url: str, cookies: Optional[dict] = None) -> str:
    """Generate a cache key from URL and cookies."""
    import hashlib
    import json

    data = {"url": url, "cookies": cookies or {}}
    return f"url:{hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()}"
