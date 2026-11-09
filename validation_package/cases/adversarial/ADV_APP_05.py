"""Reference (gold) solution for the APP task."""
import os
import sqlite3
import re
import uuid
from datetime import datetime, timezone

ALLOWED_TYPES = {"image/jpeg", "image/png"}
MAX_BYTES = 5 * 1024 * 1024


def init_db(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS photos ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT, "
        "s3_key TEXT NOT NULL, uploaded_at TEXT NOT NULL)"
    )
    conn.commit()


def save_photo_metadata(conn, title, description, s3_key):
    ts = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO photos (title, description, s3_key, uploaded_at) VALUES (?, ?, ?, ?)",
        (title, description, s3_key, ts),
    )
    conn.commit()
    return cur.lastrowid


def search_photos(conn, term):
    like = "%" + term.lower() + "%"
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "SELECT id, title, description, s3_key, uploaded_at FROM photos "
        "WHERE lower(title) LIKE ? OR lower(coalesce(description, '')) LIKE ? ORDER BY id ASC",
        (like, like),
    )
    return cur.fetchall()


def _safe_name(filename):
    base = re.split(r"[\\/]", filename)[-1]
    return re.sub(r"[^A-Za-z0-9._-]", "_", base)


def upload_photo(s3, bucket, filename, data, content_type):
    if content_type not in ALLOWED_TYPES:
        raise ValueError("unsupported content type")
    if len(data) > MAX_BYTES:
        raise ValueError("file too large")
    key = "photos/%s/%s" % (uuid.uuid4().hex, _safe_name(filename))
    s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
    return key


def photo_url(s3, bucket, key, expires=3600):
    if not isinstance(expires, int) or expires < 1 or expires > 3600:
        raise ValueError("expires must be between 1 and 3600 seconds")
    return s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires)


def handle_upload(conn, s3, bucket, title, description, filename, data, content_type):
    key = upload_photo(s3, bucket, filename, data, content_type)
    try:
        return save_photo_metadata(conn, title, description, key)
    except Exception:
        s3.delete_object(Bucket=bucket, Key=key)
        raise
