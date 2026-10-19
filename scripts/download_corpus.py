"""Download the public-domain NIST evaluation corpus and verify checksums.

NIST publications are works of the U.S. federal government and are not subject
to copyright protection in the United States (17 U.S.C. 105).

Usage:  python scripts/download_corpus.py
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parents[1] / "data" / "corpus"

CORPUS = [
    ("NIST.AI.100-1.pdf", "https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf",
     "7576edb531d9848825814ee88e28b1795d3a84b435b4b797d3670eafdc4a89f1"),
    ("NIST.SP.800-63b.pdf", "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-63b.pdf",
     "ccfce7510a1267933f912d023306c6e7d485f21be63d271108b61aad6139127e"),
    ("NIST.SP.800-61r2.pdf", "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-61r2.pdf",
     "b1c5ead0632dcfb979c59d8c462b094ad2465ddaf62d5c246289d6d9b4419df1"),
    ("NIST.SP.800-37r2.pdf", "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-37r2.pdf",
     "4f75e1136bb905a654f1bcd9eefefb4108f47597276ee5eec0688f6d96f6a01d"),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    ok = True
    for name, url, expected in CORPUS:
        dest = CORPUS_DIR / name
        if not dest.exists():
            print(f"downloading {name} ...")
            urllib.request.urlretrieve(url, dest)  # noqa: S310 - fixed https URLs
        actual = sha256(dest)
        status = "ok" if actual == expected else "CHECKSUM MISMATCH"
        ok &= actual == expected
        print(f"{name}: {status}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
