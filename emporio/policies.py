"""Search inside the store manual ("RAG light").

Why not embeddings? The manual has about 30 short sections (8 pages).
Keyword search (BM25) over sections is enough, needs no extra API call,
is free, and gives the same answer every time, so it is easy to test.
The LLM writes the search words itself, so it can use the manual's vocabulary.
"""
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .config import DATA_DIR
from .text import similar, stem, tokens

STOPWORDS = set(
    "a o as os um uma de da do das dos em no na nos nas por para com sem que e ou se ao aos "
    "meu minha seu sua qual quais como quando onde posso pode voces voce eu".split()
)

# Customer words -> words used in the manual.
SYNONYMS = {
    "devolver": "devolucao arrependimento",
    "devolvo": "devolucao arrependimento",
    "arrependi": "arrependimento",
    "reembolso": "reembolso devolucao",
    "estragou": "defeito",
    "quebrou": "defeito",
    "defeituoso": "defeito",
    "parcelar": "parcelamento parcela",
    "parcelas": "parcelamento parcela",
    "abrem": "horario funcionamento",
    "fecham": "horario funcionamento",
    "aberto": "horario funcionamento",
    "entrega": "frete entrega prazo",
    "entregam": "frete entrega prazo",
    "mandam": "frete entrega",
    "rastrear": "rastreamento codigo",
    "endereco": "endereco localizacao",
    "onde": "endereco localizacao",
    "cartao": "cartao credito debito",
    "desconto": "desconto promocao pix",
    "telefone": "telefone whatsapp contato",
    "whatsapp": "telefone whatsapp contato",
    "contato": "telefone whatsapp contato email",
    "email": "email contato",
    "vendem": "comercializamos acessorios exclusivamente",
    "vende": "comercializamos acessorios exclusivamente",
    "acessorio": "acessorios comercializamos exclusivamente",
    "acessorios": "acessorios comercializamos exclusivamente",
}


@dataclass
class Chunk:
    title: str
    text: str


def _terms(text: str) -> list[str]:
    return [stem(t) for t in tokens(text) if t not in STOPWORDS]


def split_sections(markdown: str) -> list[Chunk]:
    """One chunk per '##' or '###' heading. The text before the first heading is the cover page."""
    chunks: list[Chunk] = []
    parent = ""
    title = "Capa do manual (contato e versão)"
    body: list[str] = []

    def flush():
        text = "\n".join(body).strip()
        if text:
            chunks.append(Chunk(title, text))

    for line in markdown.splitlines():
        if line.startswith("### "):
            flush()
            title, body = f"{parent} > {line[4:].strip()}", []
        elif line.startswith("## "):
            flush()
            parent = line[3:].strip()
            title, body = parent, []
        else:
            body.append(line)
    flush()
    return chunks


class PolicyIndex:
    def __init__(self, markdown: str):
        self.chunks = split_sections(markdown)
        # The title counts twice, so a section about "Garantia" wins for "garantia".
        self._tf = [Counter(_terms(c.title + " " + c.title + " " + c.text)) for c in self.chunks]
        self._len = [sum(tf.values()) for tf in self._tf]
        self._avg = sum(self._len) / len(self._len)

    def search(self, query: str, k: int = 3) -> list[dict]:
        words = tokens(query)
        expanded = words + [w for q in words for w in SYNONYMS.get(q, "").split()]
        q_terms = [t for t in dict.fromkeys(stem(w) for w in expanded) if t not in STOPWORDS]

        scores = []
        for tf, length in zip(self._tf, self._len):
            score = 0.0
            for q in q_terms:
                freq = sum(c for d, c in tf.items() if similar(q, d))
                if not freq:
                    continue
                df = sum(1 for other in self._tf if any(similar(q, d) for d in other))
                idf = math.log(1 + (len(self.chunks) - df + 0.5) / (df + 0.5))
                score += idf * freq * 2.5 / (freq + 1.5 * (0.25 + 0.75 * length / self._avg))
            scores.append(score)

        ranked = sorted(zip(scores, self.chunks), key=lambda x: -x[0])
        best = ranked[0][0] if ranked else 0
        if best <= 0:
            return []
        return [{"section": c.title, "text": c.text, "score": round(s, 2)}
                for s, c in ranked[:k] if s >= 0.35 * best]


def load_policies(path: Path = DATA_DIR / "politicas_da_loja.md") -> PolicyIndex:
    return PolicyIndex(path.read_text(encoding="utf-8"))


def section_titles(index: PolicyIndex) -> list[str]:
    return [re.sub(r"\s+", " ", c.title) for c in index.chunks]
