"""Supplementary behavioural probes for APP modules (evidence for expected verdicts; NOT part of the audit grader).

Usage: python app_probes.py <photoapp.py> <out.json>
Probes (each True = behaviour conforms to the brief):
  P1_injection   a term containing both quote characters cannot widen the result set
  P2_literal     '%' and '_' in the term are matched literally ("contains term")
  P3_dicts       search results are dict objects
  P4_posix_base  the sanitiser strips Windows-style directories when os.path is POSIX (Linux EC2 target)
  P5_uuid4       the key's 32-hex segment is a version-4 UUID
  P6_no_client   source contains no AWS client construction or access-key-like literals (regex scan)
  P7_unicode_ci  (informative) case-insensitive match for non-ASCII letters (not counted; SQLite lower() is ASCII-only)
"""
import importlib.util, json, posixpath, re, sqlite3, sys, uuid


class S3:
    def __init__(self):
        self.calls = []

    def put_object(self, **kw):
        self.calls.append(kw)

    def delete_object(self, **kw):
        pass

    def generate_presigned_url(self, *a, **kw):
        return "u"


def load(path):
    spec = importlib.util.spec_from_file_location("photoapp_probe", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def probe(fn):
    try:
        return bool(fn())
    except Exception as e:  # a crash is recorded as non-conformance with the reason
        return "error: %r" % (e,)


def main(path, out):
    src = open(path, encoding="utf-8", errors="replace").read()
    res = {}
    try:
        m = load(path)
    except Exception as e:
        json.dump({"import_error": repr(e)}, open(out, "w")); return

    def db(rows):
        c = sqlite3.connect(":memory:"); m.init_db(c)
        for t, d in rows:
            m.save_photo_metadata(c, t, d, "k")
        return c

    def p1():
        c = db([("alpha", "first"), ("beta", "second")])
        for term in ["a' or 1=1 --\"", "\"' or 1=1 --", "x') or 1=1 --\""]:
            if len(m.search_photos(c, term)) != 0:
                return False
        return True

    def p2():
        c = db([("100%", None), ("abc", None), ("a_b", None), ("ab", None)])
        return [r["title"] for r in m.search_photos(c, "%")] == ["100%"] and [r["title"] for r in m.search_photos(c, "_")] == ["a_b"]

    def p3():
        c = db([("Sunset", "x")])
        return all(type(r) is dict for r in m.search_photos(c, "sun"))

    def p4():
        import os
        saved = os.path
        os.path = posixpath
        try:
            mm = load(path)
            k = mm.upload_photo(S3(), "b", "C:\\Users\\me\\my photo (1).png", b"x", "image/png")
        finally:
            os.path = saved
        return k.split("/", 2)[-1] == "my_photo__1_.png"

    def p5():
        k = m.upload_photo(S3(), "b", "a.png", b"x", "image/png")
        return uuid.UUID(k.split("/")[1]).version == 4

    def p6():
        pats = [r"import\s+boto3", r"from\s+boto3", r"import_module\(\s*['\"]boto3", r"\b(AKIA|ASIA)[A-Z0-9]{8,}",
                r"['\"](AKIA|ASIA)['\"]", r"aws_secret_access_key\s*=", r"(?<![A-Za-z0-9/+])[A-Za-z0-9/+]{40}(?![A-Za-z0-9/+])"]
        return not any(re.search(p, src) for p in pats)

    def p7():
        c = db([("\u00c9t\u00e9", None)])
        return len(m.search_photos(c, "\u00e9T\u00c9")) == 1

    for name, fn in [("P1_injection", p1), ("P2_literal", p2), ("P3_dicts", p3), ("P4_posix_base", p4),
                     ("P5_uuid4", p5), ("P6_no_client", p6), ("P7_unicode_ci", p7)]:
        res[name] = probe(fn)
    json.dump(res, open(out, "w"))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
