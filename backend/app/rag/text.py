"""Arabic/English text normalisation and tokenisation (pure Python, no dependencies)."""
from __future__ import annotations

import re
import unicodedata
from typing import List

_DIACRITICS = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭ]")
_TOKEN = re.compile(r"[a-z0-9ء-ي]+")
_DIGITS = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩"
    "۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789",
)
_CHAR_MAP = str.maketrans({
    "أ": "ا",  # أ -> ا
    "إ": "ا",  # إ -> ا
    "آ": "ا",  # آ -> ا
    "ٱ": "ا",  # ٱ -> ا
    "ى": "ي",  # ى -> ي
    "ئ": "",   # dropped, so بطيء / بطيئ / بطيئة agree
    "ء": "",   # dropped
    "ؤ": "و",  # ؤ -> و
    "ة": "ه",  # ة -> ه
    "ـ": "",        # tatweel
})

# وال بال كال فال لل ال  +  Egyptian progressive/future verb prefixes (بي بت هي هت) + conjunction و
_PREFIXES = ("وال", "بال", "كال", "فال", "لل", "ال", "بي", "بت", "هي", "هت", "و")
_SUFFIXES = ("ات", "ون", "ين", "ان", "ها", "هم", "ه")  # ات ون ين ان ها هم ه

STOPWORDS = frozenset(
    """
    في من على الى عن مع هل ما ماذا لماذا كيف انا انت هو هي هم نحن هذا هذه ذلك تلك
    ان كان كانت يكون لا لم لن قد او ثم كل بعد قبل عند لي لك له لها فيه فيها به بها
    ايه ايش عندي عندك بتاعي بتاعتي بتاعنا لوحده معايا ده دي دا دول مش مفيش مافيش عايز عاوز عايزه عاوزه اللي لو بس كده كدا يا ازاي ليه امتي فين جت جات
    الشهر ده اوي جدا خالص حاجه شويه
    the a an is are was were be to of in on for and or with my i me it this that how what why do does
    """.split()
)


# Egyptian-dialect / spelling variants -> one canonical token (applied to documents and queries alike).
# Extend freely: keys and values are normalised automatically (see DIALECT_MAP below).
_RAW_DIALECT = {
    "نت": "انترنت", "النت": "انترنت", "انترنت": "انترنت", "internet": "انترنت", "net": "انترنت", "wifi": "واي",
    "باسورد": "كلمه", "بسورد": "كلمه", "password": "كلمه", "pass": "كلمه",
    "فاصل": "مقطوع", "فصل": "مقطوع", "بيفصل": "مقطوع", "بتفصل": "مقطوع", "يفصل": "مقطوع", "تفصل": "مقطوع",
    "قاطع": "مقطوع", "قطع": "مقطوع", "انقطاع": "مقطوع", "واقع": "مقطوع", "وقع": "مقطوع",
    "غالي": "اعلي", "غلي": "اعلي", "زياده": "اعلي", "زياد": "اعلي", "كبيره": "اعلي",
    "بيتخصم": "خصم", "اتخصم": "خصم", "بيخصم": "خصم", "خصمت": "خصم", "تخصم": "خصم", "خصم": "خصم",
    "الغي": "الغاء", "الغاء": "الغاء", "الغ": "الغاء", "كنسل": "الغاء", "cancel": "الغاء",
    "دفعت": "دفع", "ادفع": "دفع", "بدفع": "دفع", "دفع": "دفع", "سدد": "دفع", "سداد": "دفع",
    "هاتف": "موبايل", "تليفون": "موبايل", "محمول": "موبايل", "موبيل": "موبايل", "phone": "موبايل", "mobile": "موبايل",
    "فتح": "فتح", "تفتح": "فتح", "يفتح": "فتح", "افتح": "فتح", "بتفتح": "فتح", "بيفتح": "فتح",
    "قفل": "قفل", "تقفل": "قفل", "يقفل": "قفل", "اقفل": "قفل", "بيقفل": "قفل", "بتقفل": "قفل",
    "يغلق": "قفل", "تغلق": "قفل", "اغلق": "قفل", "غلق": "قفل", "ينغلق": "قفل", "بيتقفل": "قفل",
    "كتير": "كثير", "كثير": "كثير", "كثيرا": "كثير",
    "بطي": "بطي", "ببط": "بطي", "slow": "بطي",
    "ضعيف": "ضعيف", "ضعف": "ضعيف",
    "فلوس": "مبلغ", "مبالغ": "مبلغ", "رصيد": "رصيد",
    "راوتر": "راوتر", "router": "راوتر", "روتر": "راوتر", "مودم": "راوتر", "modem": "راوتر",
}


def normalize(text: str) -> str:
    """Lower-case, strip diacritics/tatweel, unify alef/ya/ta-marbuta, ASCII digits."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower()
    text = _DIACRITICS.sub("", text)
    text = text.translate(_DIGITS).translate(_CHAR_MAP)
    return text


DIALECT_MAP = {normalize(k): normalize(v) for k, v in _RAW_DIALECT.items()}


def stem(token: str) -> str:
    """Very light stemmer: strips common Arabic prefixes/suffixes and English plural 's'."""
    if token.isascii():
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            return token[:-1]
        return token
    for prefix in _PREFIXES:
        if token.startswith(prefix) and len(token) - len(prefix) >= 3:
            token = token[len(prefix):]
            break
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            token = token[: -len(suffix)]
            break
    return token


def tokenize(text: str, *, drop_stopwords: bool = True) -> List[str]:
    tokens: List[str] = []
    for raw in _TOKEN.findall(normalize(text)):
        if drop_stopwords and raw in STOPWORDS:
            continue
        tok = DIALECT_MAP.get(raw) or DIALECT_MAP.get(stem(raw)) or stem(raw)
        if len(tok) < 2 and not tok.isdigit():
            continue
        tokens.append(tok)
    return tokens


def has_arabic(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06ff" for ch in text or "")
