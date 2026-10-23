"""Fail if any tracked file mentions a former client or a private host.

The stand grew out of code written for real projects. This guard keeps their names, hosts and
proxy ids out of the public repository. Terms are stored encoded so the check does not trip on itself.
Matching ignores case, spaces and punctuation, so "Acme-Corp", "acme_corp" and "ACMECORP" are the same term.
"""

import base64
import re
import subprocess
import sys

_ENCODED = [
    "a2NhcHlsb3A=",
    "0LrQsNC/0LjQu9C+0L8=",
    "YnVsY2VwYW5hYw==",
    "cmFjcmFjZXRpbGU=",
    "Y2hqbW10ZmViY2plZHRqdWhwcXo=",
    "dnpmbnh1",
    "cmFjZXRpbGU=",
    "eXRpY3JhYw==",
    "YnVsY2VwYW5hYw==",
    "bjhubmlrb29s",
    "cmVsdXJp",
]
TERMS = [base64.b64decode(t).decode()[::-1] for t in _ENCODED]
SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".woff", ".woff2", ".mp3", ".ogg", ".pdf", ".sqlite3")
NORMALIZE = re.compile(r"[^0-9a-zа-яё]+")


def files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], capture_output=True, text=True, check=True)
    return [f for f in out.stdout.splitlines() if f and not f.lower().endswith(SKIP_SUFFIXES)]


def main() -> int:
    found = []
    for path in files():
        try:
            with open(path, encoding="utf-8") as fh:
                text = NORMALIZE.sub("", fh.read().lower())
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        hits = [i for i, term in enumerate(TERMS) if term in text]
        if hits:
            found.append(f"{path}: term #{', #'.join(str(i) for i in hits)}")
    if found:
        print("Private names found:\n" + "\n".join(found))
        return 1
    print(f"ok: {len(TERMS)} private terms, no matches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
