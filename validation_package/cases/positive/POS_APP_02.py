"""photoapp - alternative solution 2: repository class, LIKE with ESCAPE, ntpath + regex sanitiser."""
import ntpath
import re
import uuid
from datetime import datetime, timezone

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ACCEPTED = frozenset({"image/jpeg", "image/png"})
UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
MIN_EXPIRY, MAX_EXPIRY = 1, 3600


class _PhotoRepository:
    DDL = ("CREATE TABLE IF NOT EXISTS photos (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, "
           "description TEXT, s3_key TEXT NOT NULL, uploaded_at TEXT NOT NULL)")
    INSERT = "INSERT INTO photos (title, description, s3_key, uploaded_at) VALUES (?, ?, ?, ?)"
    SEARCH = ("SELECT id, title, description, s3_key, uploaded_at FROM photos "
              "WHERE title LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\' ORDER BY id ASC")
    KEYS = ("id", "title", "description", "s3_key", "uploaded_at")

    def __init__(self, conn):
        self.conn = conn

    def create(self):
        self.conn.execute(self.DDL)
        self.conn.commit()

    def add(self, title, description, s3_key):
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cur = self.conn.execute(self.INSERT, (title, description, s3_key, stamp))
        self.conn.commit()
        return cur.lastrowid

    def find(self, term):
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = "%{}%".format(escaped)
        rows = self.conn.execute(self.SEARCH, (pattern, pattern)).fetchall()
        return [dict(zip(self.KEYS, row)) for row in rows]


def init_db(conn):
    _PhotoRepository(conn).create()


def save_photo_metadata(conn, title, description, s3_key):
    return _PhotoRepository(conn).add(title, description, s3_key)


def search_photos(conn, term):
    return _PhotoRepository(conn).find(term)


def safe_name(filename):
    return UNSAFE.sub("_", ntpath.basename(filename))


def upload_photo(s3, bucket, filename, data, content_type):
    if content_type not in ACCEPTED:
        raise ValueError("content type %r not allowed" % (content_type,))
    size = len(data)
    if size > MAX_UPLOAD_BYTES:
        raise ValueError("upload of %d bytes exceeds the limit" % size)
    object_key = "photos/{}/{}".format(uuid.uuid4().hex, safe_name(filename))
    s3.put_object(Bucket=bucket, Key=object_key, Body=data, ContentType=content_type)
    return object_key


def photo_url(s3, bucket, key, expires=3600):
    if type(expires) is not int or expires < MIN_EXPIRY or expires > MAX_EXPIRY:
        raise ValueError("expires out of range")
    params = {"Bucket": bucket, "Key": key}
    return s3.generate_presigned_url("get_object", Params=params, ExpiresIn=expires)


def handle_upload(conn, s3, bucket, title, description, filename, data, content_type):
    object_key = upload_photo(s3, bucket, filename, data, content_type)
    try:
        row_id = save_photo_metadata(conn, title, description, object_key)
    except Exception:
        s3.delete_object(Bucket=bucket, Key=object_key)
        raise
    return row_id
