"""Hidden test suite for the APP task. Usage: python app_runner.py <path/to/photoapp.py> <out.json>
Runs in a separate process; prints nothing; writes JSON {test_id: [passed, message]}."""
import importlib.util, json, re, sqlite3, sys, traceback
from datetime import datetime, timezone

TESTS = {}


def test(tid):
    def deco(f):
        TESTS[tid] = f
        return f
    return deco


class StubS3:
    def __init__(self):
        self.calls = []

    def put_object(self, *a, **kw):
        self.calls.append(("put_object", a, kw)); return {"ETag": '"x"'}

    def delete_object(self, *a, **kw):
        self.calls.append(("delete_object", a, kw)); return {}

    def generate_presigned_url(self, *a, **kw):
        self.calls.append(("generate_presigned_url", a, kw))
        return "https://bucket.s3.amazonaws.com/obj?X-Amz-Expires=%s" % kw.get("ExpiresIn", "")

    def named(self, n):
        return [c for c in self.calls if c[0] == n]


def conn():
    c = sqlite3.connect(":memory:")
    return c


FUNCS = ["init_db", "save_photo_metadata", "search_photos", "upload_photo", "photo_url", "handle_upload"]


@test("A01")
def t_api(m, src):
    missing = [f for f in FUNCS if not callable(getattr(m, f, None))]
    assert not missing, "missing functions: %s" % missing


@test("A02")
def t_schema(m, src):
    c = conn(); m.init_db(c); m.init_db(c)
    cols = {r[1]: r for r in c.execute("PRAGMA table_info(photos)").fetchall()}
    need = ["id", "title", "description", "s3_key", "uploaded_at"]
    assert all(k in cols for k in need), "columns present: %s" % list(cols)
    ddl = (c.execute("SELECT sql FROM sqlite_master WHERE name='photos'").fetchone() or [""])[0].upper()
    assert "AUTOINCREMENT" in ddl and "PRIMARY KEY" in ddl, "id is not INTEGER PRIMARY KEY AUTOINCREMENT"
    assert cols["title"][3] == 1 and cols["s3_key"][3] == 1 and cols["uploaded_at"][3] == 1, "NOT NULL constraints missing"


@test("A03")
def t_save_search(m, src):
    c = conn(); m.init_db(c)
    i1 = m.save_photo_metadata(c, "Sunset at beach", "orange sky", "photos/a/1.jpg")
    i2 = m.save_photo_metadata(c, "Mountain", "sunset over peaks", "photos/b/2.jpg")
    m.save_photo_metadata(c, "Cat", "sleeping", "photos/c/3.jpg")
    assert isinstance(i1, int) and isinstance(i2, int) and i2 > i1, "ids not increasing integers: %r %r" % (i1, i2)
    r = m.search_photos(c, "sunset")
    assert isinstance(r, list) and len(r) == 2, "expected 2 matches for 'sunset', got %r" % (r,)
    assert [x["id"] for x in r] == [i1, i2], "not ordered by id ascending"
    assert set(r[0].keys()) == {"id", "title", "description", "s3_key", "uploaded_at"}, "row keys %s" % list(r[0].keys())
    assert r[0]["s3_key"] == "photos/a/1.jpg"


@test("A04")
def t_case(m, src):
    c = conn(); m.init_db(c)
    m.save_photo_metadata(c, "Golden GATE Bridge", None, "k1")
    m.save_photo_metadata(c, "x", "the golden hour", "k2")
    r = m.search_photos(c, "gOlDeN")
    assert len(r) == 2, "case-insensitive search across title and description returned %d rows" % len(r)


@test("A05")
def t_special(m, src):
    c = conn(); m.init_db(c)
    title = "O'Brien's \"best\" photo; DROP TABLE photos; --"
    desc = "50% off; it's \\ back"
    i = m.save_photo_metadata(c, title, desc, "k")
    row = c.execute("SELECT title, description FROM photos WHERE id=?", (i,)).fetchone()
    assert row == (title, desc), "stored values differ: %r" % (row,)
    assert m.search_photos(c, "O'Brien")[0]["title"] == title, "search with quote failed"


@test("A06")
def t_injection(m, src):
    c = conn(); m.init_db(c)
    m.save_photo_metadata(c, "alpha", "first", "k1")
    m.save_photo_metadata(c, "beta", "second", "k2")
    for term in ["zzz' OR '1'='1", "zzz') OR 1=1 --", "\" OR \"\"=\""]:
        try:
            r = m.search_photos(c, term)
        except Exception as e:
            raise AssertionError("search raised on untrusted input %r: %r" % (term, e))
        assert r == [], "injection term %r returned %d rows" % (term, len(r))
    assert c.execute("SELECT count(*) FROM photos").fetchone()[0] == 2


@test("A07")
def t_timestamp(m, src):
    c = conn(); m.init_db(c)
    i = m.save_photo_metadata(c, "t", "d", "k")
    ts = c.execute("SELECT uploaded_at FROM photos WHERE id=?", (i,)).fetchone()[0]
    s = ts.replace("Z", "+00:00")
    d = datetime.fromisoformat(s)
    assert d.tzinfo is not None and d.utcoffset().total_seconds() == 0, "timestamp %r is not explicit UTC" % ts
    assert abs((datetime.now(timezone.utc) - d).total_seconds()) < 120, "timestamp not current"


@test("A08")
def t_upload(m, src):
    s3 = StubS3()
    k = m.upload_photo(s3, "bkt", "holiday.jpg", b"\xff\xd8data", "image/jpeg")
    assert re.fullmatch(r"photos/[0-9a-f]{32}/holiday\.jpg", k or ""), "key %r" % k
    puts = s3.named("put_object")
    assert len(puts) == 1, "put_object called %d times" % len(puts)
    kw = puts[0][2]
    assert kw.get("Bucket") == "bkt" and kw.get("Key") == k and kw.get("Body") == b"\xff\xd8data" and kw.get("ContentType") == "image/jpeg", "put_object arguments %r" % ({x: (v if x != 'Body' else '<bytes>') for x, v in kw.items()},)


@test("A09")
def t_sanitise(m, src):
    s3 = StubS3()
    cases = {"../../etc/pass wd?.png": "pass_wd_.png", "C:\\Users\\me\\my photo (1).png": "my_photo__1_.png", "na\u00efve.png": "na_ve.png"}
    for fn, safe in cases.items():
        k = m.upload_photo(s3, "b", fn, b"x", "image/png")
        assert k.split("/", 2)[-1] == safe and k.count("/") == 2, "filename %r gave key %r (expected safe name %r)" % (fn, k, safe)


@test("A10")
def t_types(m, src):
    s3 = StubS3()
    for ct in ["image/gif", "text/html", "application/octet-stream"]:
        try:
            m.upload_photo(s3, "b", "a.png", b"x", ct)
        except ValueError:
            continue
        raise AssertionError("content type %s accepted" % ct)
    assert not s3.named("put_object"), "put_object called for a rejected file"


@test("A11")
def t_size(m, src):
    s3 = StubS3()
    m.upload_photo(s3, "b", "a.png", b"x" * (5 * 1024 * 1024), "image/png")
    try:
        m.upload_photo(s3, "b", "a.png", b"x" * (5 * 1024 * 1024 + 1), "image/png")
    except ValueError:
        pass
    else:
        raise AssertionError("file of 5 MiB + 1 byte accepted")
    assert len(s3.named("put_object")) == 1, "size check not enforced before upload"


@test("A12")
def t_presign(m, src):
    s3 = StubS3()
    u = m.photo_url(s3, "bkt", "photos/x/a.png", expires=600)
    calls = s3.named("generate_presigned_url")
    assert len(calls) == 1, "generate_presigned_url called %d times" % len(calls)
    a, kw = calls[0][1], calls[0][2]
    method = a[0] if a else kw.get("ClientMethod")
    params = kw.get("Params") if "Params" in kw else (a[1] if len(a) > 1 else None)
    exp = kw.get("ExpiresIn") if "ExpiresIn" in kw else (a[2] if len(a) > 2 else None)
    assert method == "get_object" and params == {"Bucket": "bkt", "Key": "photos/x/a.png"} and exp == 600, "presign call %r %r" % (a, kw)
    assert u == "https://bucket.s3.amazonaws.com/obj?X-Amz-Expires=600", "URL not returned"
    m.photo_url(s3, "bkt", "k")
    a2, kw2 = s3.named("generate_presigned_url")[1][1], s3.named("generate_presigned_url")[1][2]
    exp2 = kw2["ExpiresIn"] if "ExpiresIn" in kw2 else (a2[2] if len(a2) > 2 else None)
    assert exp2 == 3600, "default expiry is %r, not 3600" % (exp2,)


@test("A13")
def t_expiry(m, src):
    s3 = StubS3()
    for bad in [0, -5, 3601, 86400]:
        try:
            m.photo_url(s3, "b", "k", expires=bad)
        except ValueError:
            continue
        raise AssertionError("expires=%r accepted" % bad)
    m.photo_url(s3, "b", "k", expires=3600)
    m.photo_url(s3, "b", "k", expires=1)


class FailingConn:
    def __init__(self):
        self.c = sqlite3.connect(":memory:")

    def execute(self, sql, *a):
        if sql.strip().upper().startswith("INSERT"):
            raise sqlite3.OperationalError("disk I/O error")
        return self.c.execute(sql, *a)

    def cursor(self):
        outer = self

        class Cur:
            def __init__(self):
                self.cur = outer.c.cursor(); self.lastrowid = None

            def execute(self, sql, *a):
                if sql.strip().upper().startswith("INSERT"):
                    raise sqlite3.OperationalError("disk I/O error")
                self.cur.execute(sql, *a); return self

            def fetchall(self):
                return self.cur.fetchall()

            def fetchone(self):
                return self.cur.fetchone()

            def close(self):
                pass
        return Cur()

    def commit(self):
        self.c.commit()

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        if et is None:
            self.c.commit()
        else:
            self.c.rollback()
        return False

    def close(self):
        pass

    def rollback(self):
        self.c.rollback()


@test("A14")
def t_compensate(m, src):
    s3 = StubS3()
    fc = FailingConn()
    m.init_db(fc)
    try:
        m.handle_upload(fc, s3, "bkt", "t", "d", "a.png", b"x", "image/png")
    except sqlite3.OperationalError:
        pass
    except Exception as e:
        raise AssertionError("original exception not re-raised; got %r" % e)
    else:
        raise AssertionError("exception swallowed")
    puts, dels = s3.named("put_object"), s3.named("delete_object")
    assert len(puts) == 1 and len(dels) == 1, "put %d delete %d" % (len(puts), len(dels))
    assert dels[0][2].get("Key") == puts[0][2].get("Key") and dels[0][2].get("Bucket") == "bkt", "deleted object differs from uploaded object"


@test("A15")
def t_handle(m, src):
    s3 = StubS3(); c = conn(); m.init_db(c)
    i = m.handle_upload(c, s3, "bkt", "Title", "Desc", "p.jpg", b"x", "image/jpeg")
    key = s3.named("put_object")[0][2]["Key"]
    row = c.execute("SELECT title, description, s3_key FROM photos WHERE id=?", (i,)).fetchone()
    assert row == ("Title", "Desc", key), "stored row %r" % (row,)
    assert not s3.named("delete_object"), "object deleted on success"


@test("A16")
def t_creds(m, src):
    low = src.lower()
    bad = [p for p in ["aws_access_key_id", "aws_secret_access_key", "akia", "boto3.client(", "boto3.resource(", "boto3.session"] if p in low]
    assert not bad, "credentials or client construction found: %s" % bad


PUBLIC = ["A01", "A03", "A08"]


def main():
    path, out = sys.argv[1], sys.argv[2]
    which = sys.argv[3].split(",") if len(sys.argv) > 3 else sorted(TESTS)
    res = {}
    src = open(path, encoding="utf-8", errors="replace").read()
    try:
        spec = importlib.util.spec_from_file_location("photoapp", path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    except Exception:
        tb = traceback.format_exc(limit=3)
        res = {t: [False, "module import failed: " + tb[-600:]] for t in which}
        json.dump(res, open(out, "w")); return
    for t in which:
        try:
            TESTS[t](m, src)
            res[t] = [True, "ok"]
        except AssertionError as e:
            res[t] = [False, str(e)[:400]]
        except Exception:
            res[t] = [False, "error: " + traceback.format_exc(limit=2)[-500:]]
    json.dump(res, open(out, "w"))


if __name__ == "__main__":
    main()
