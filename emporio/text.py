"""Small text helpers: accent folding, tokens, plural handling, money format."""
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal


def fold(text: str) -> str:
    """Lower case and remove accents: 'Violões' -> 'violoes'."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", fold(text))


def stem(word: str) -> str:
    """Very simple Portuguese plural -> singular. Good enough for a small catalog."""
    if word.endswith(("oes", "aes")) and len(word) > 4:
        return word[:-3] + "ao"  # violoes -> violao
    if word.endswith("ais") and len(word) > 4:
        return word[:-3] + "al"
    if word.endswith("es") and len(word) > 5:
        return word[:-2]  # ukuleles -> ukulel
    if word.endswith("s") and len(word) > 3:
        return word[:-1]  # guitarras -> guitarra
    return word


def similar(a: str, b: str) -> bool:
    """Same word, or one starts with the other ('arrependi' ~ 'arrependimento', 'ukulel' ~ 'ukulele')."""
    if a == b:
        return True
    return min(len(a), len(b)) >= 5 and (a.startswith(b) or b.startswith(a))


def money(value: float) -> Decimal:
    """Round to cents the way a shop does (half up)."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def brl(value: float) -> str:
    """1299.9 -> 'R$ 1.299,90' (Brazilian format)."""
    text = f"{money(value):,.2f}"
    return "R$ " + text.replace(",", "X").replace(".", ",").replace("X", ".")
