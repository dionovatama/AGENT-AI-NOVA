"""
Token Remote Agent.

Desain:
- Token = 'nova_agt_' + 43 karakter urlsafe (256 bit dari `secrets`).
  Entropi setinggi ini membuat SHA-256 cepat sudah memadai untuk
  penyimpanan (tidak ada yang bisa menebak offline); KDF lambat seperti
  bcrypt tidak menambah keamanan dan hanya memperlambat tiap handshake.
- DB hanya menyimpan hash (hex). Token plaintext ditampilkan SEKALI saat
  dibuat/di-rotate.
- Perbandingan memakai hmac.compare_digest (constant-time). Saat agent
  tidak ditemukan, perbandingan tetap dijalankan terhadap hash dummy agar
  waktu respons tidak membocorkan apakah agent_id ada.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

TOKEN_PREFIX = "nova_agt_"
_TOKEN_RE = re.compile(r"^nova_agt_[A-Za-z0-9_-]{43}$")
_MAX_PRESENTED_LENGTH = 256


def generate_agent_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_agent_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_well_formed_token(token: object) -> bool:
    return isinstance(token, str) and _TOKEN_RE.fullmatch(token) is not None


# Hash dummy untuk jalur "agent tidak ada" (lihat docstring modul).
DUMMY_TOKEN_HASH = hash_agent_token(TOKEN_PREFIX + "x" * 43)


def verify_agent_token(presented: object, stored_hash: str) -> bool:
    """
    True hanya jika token berformat benar DAN hash-nya sama dengan
    stored_hash. Selalu melakukan hashing + compare_digest, apa pun
    isi 'presented', supaya jalur gagal & sukses punya biaya serupa.
    """
    if isinstance(presented, str) and len(presented) <= _MAX_PRESENTED_LENGTH:
        candidate = presented
    else:
        candidate = ""
    digest = hash_agent_token(candidate)
    hashes_match = hmac.compare_digest(
        digest.encode("ascii"), stored_hash.encode("ascii", "ignore")
    )
    return hashes_match and is_well_formed_token(candidate)
