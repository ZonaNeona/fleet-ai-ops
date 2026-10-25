"""Fail if any tracked file mentions a former client or a private host.

The stand grew out of code written for real projects. This guard keeps their names, hosts and proxy ids out of the
public repository. The terms themselves are not stored: only their length, a hash of their first three characters (a
cheap filter) and a hash of the whole term. Matching ignores case, spaces and punctuation, so "Acme-Corp", "acme_corp"
and "ACMECORP" are the same term.
"""

import hashlib
import re
import subprocess
import sys

TERMS = [
    (10, "9f584196", "c72089bae65e4a5825c97bb4"),
    (7, "2b2961a4", "746ee43baa8444dccce55db7"),
    (8, "27037fcc", "f89f17f1797c55146a5560cb"),
    (11, "27037fcc", "32084c3e9cefa308d151be01"),
    (6, "095cac40", "c1f49c89aa6bfbe368f7b139"),
    (9, "15f3b852", "bfcba7959bf36d2d42baad3f"),
    (8, "ae1cd330", "c07d1cfcef37eeadaabaaeca"),
    (6, "19788b99", "2b04fad95d730b7587c4315f"),
    (20, "c0d0984a", "190be7ec19db192ea70decf7"),
    (7, "21ab0e77", "392069d89757a1f66014971a"),
]
SKIP_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".ico",
    ".woff",
    ".woff2",
    ".mp3",
    ".ogg",
    ".pdf",
    ".sqlite3",
)
NORMALIZE = re.compile(r"[^0-9a-zа-яё]+")
PREFIXES = {prefix: [(length, whole) for length, p, whole in TERMS if p == prefix] for _, prefix, _ in TERMS}


def digest(value: str, size: int) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:size]


def files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], capture_output=True, text=True, check=True)
    return [f for f in out.stdout.splitlines() if f and not f.lower().endswith(SKIP_SUFFIXES)]


def mentions(text: str) -> bool:
    flat = NORMALIZE.sub("", text.lower())
    seen: set[str] = set()
    for i in range(len(flat) - 2):
        head = flat[i : i + 3]
        if head in seen:
            continue
        candidates = PREFIXES.get(digest(head, 8))
        if candidates is None:
            seen.add(head)  # a three-letter start no term has: skip it everywhere
            continue
        if any(digest(flat[i : i + length], 24) == whole for length, whole in candidates):
            return True
    return False


def main() -> int:
    found = []
    for path in files():
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        if mentions(text):
            found.append(path)
    for path in found:
        print(f"private term in {path}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
