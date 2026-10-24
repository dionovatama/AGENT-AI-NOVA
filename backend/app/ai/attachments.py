"""
Attachment yang ikut dikembalikan bersama jawaban chat (additive).

Saat ini hanya diagram Mermaid. Model ini sengaja dipisah dari
openrouter.py (AI Gateway generik) dan tools/manager.py supaya kedua
modul itu tidak perlu saling mengenal.

PENTING: `code` adalah teks Mermaid dari LLM yang SUDAH divalidasi oleh
tool diagram.create (app/tools/diagram.py). Tetap diperlakukan sebagai
data tidak tepercaya oleh frontend — dirender dengan securityLevel
'strict' dan ditampilkan lewat <img>, bukan disisipkan ke DOM.
"""

from typing import Literal

from pydantic import BaseModel


class DiagramAttachment(BaseModel):
    kind: Literal["mermaid"] = "mermaid"
    title: str
    code: str
