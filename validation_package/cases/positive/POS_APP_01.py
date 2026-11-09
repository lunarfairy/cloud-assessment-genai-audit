"""photoapp - alternative solution 1: strict DB-API cursors, instr() search, character-loop sanitiser."""
import string
import uuid
from datetime import datetime, timezone

_ALLOWED_CONTENT = ("image/jpeg", "image/png")
_LIMIT = 5 * 1024 * 1024
_SAFE = frozenset(string.ascii_letters + string.digits + "._-")
_COLUMNS = ("id", "title", "description", "s3_key", "uploaded_at")


def _utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _rows_as_dicts(cursor):
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, r)) for r in cursor.fetchall()]


def init_db(conn):
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS photos (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               title TEXT NOT NULL,
               description TEXT,
               s3_key TEXT NOT NULL,
               uploaded_at TEXT NOT NULL
           )"""
    )
    conn.commit()


def save_photo_metadata(conn, title, description, s3_key):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO photos (title, description, s3_key, uploaded_at) VALUES (?, ?, ?, ?)",
        [title, description, s3_key, _utc_now()],
    )
    new_id = cur.lastrowid
    conn.commit()
    return int(new_id)


def search_photos(conn, term):
    cur = conn.cursor()
    cur.execute(
        "SELECT id, title, description, s3_key, uploaded_at FROM photos "
        "WHERE instr(lower(title), lower(?)) > 0 OR instr(lower(ifnull(description, '')), lower(?)) > 0 "
        "ORDER BY id",
        [term, term],
    )
    return _rows_as_dicts(cur)


def _base_name(filename):
    name = filename
    for sep in ("/", "\\"):
        name = name.rpartition(sep)[2]
    return name


def _sanitise(filename):
    return "".join(ch if ch in _SAFE else "_" for ch in _base_name(filename))


def upload_photo(s3, bucket, filename, data, content_type):
    if content_type not in _ALLOWED_CONTENT:
        raise ValueError("only JPEG and PNG images are accepted")
    if len(data) > _LIMIT:
        raise ValueError("photo exceeds 5 MiB")
    key = "/".join(["photos", uuid.uuid4().hex, _sanitise(filename)])
    s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
    return key


def photo_url(s3, bucket, key, expires=3600):
    if isinstance(expires, bool) or not isinstance(expires, int) or not (1 <= expires <= 3600):
        raise ValueError("expires must be an integer number of seconds from 1 to 3600")
    return s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires)


def handle_upload(conn, s3, bucket, title, description, filename, data, content_type):
    key = upload_photo(s3, bucket, filename, data, content_type)
    try:
        return save_photo_metadata(conn, title, description, key)
    except BaseException:
        s3.delete_object(Bucket=bucket, Key=key)
        raise
