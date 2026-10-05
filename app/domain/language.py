"""Reply-language decision for one turn (Spanish or English; anything else gets a short notice).

The model is told which language to use; it does not decide on its own. The decision reads the
visitor's own words only: quoted passages, URLs, e-mail addresses, code and catalog product names
are removed first, so a quoted English sentence or an instruction hidden in data cannot switch the
language. When the message itself is too short or mixed to decide, the language of the
conversation so far wins, then the interface locale (a preference, not an order), then Spanish.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from enum import StrEnum


class Language(StrEnum):
    ES = 'es'
    EN = 'en'


class Detected(StrEnum):
    ES = 'es'
    EN = 'en'
    OTHER = 'other'
    UNKNOWN = 'unknown'


_QUOTED = re.compile(r'"[^"]*"|“[^”]*”|«[^»]*»|`[^`]*`|(?<!\w)\'[^\']{6,}\'(?!\w)')
_CODE = re.compile(r'```.*?```', re.DOTALL)
_URLISH = re.compile(r'\S+@\S+|(?:https?://|www\.)\S+|\b\S+\.(?:com|net|org|io|ar|es|mx)\S*', re.IGNORECASE)
_WORD = re.compile(r"[a-zñçãõâêôàèìòùäëïöü']+")

_ES = frozenset(
    [
        'el',
        'la',
        'los',
        'las',
        'de',
        'del',
        'que',
        'y',
        'en',
        'un',
        'una',
        'es',
        'por',
        'para',
        'con',
        'no',
        'se',
        'lo',
        'al',
        'como',
        'mas',
        'pero',
        'sus',
        'le',
        'ya',
        'o',
        'este',
        'esta',
        'si',
        'porque',
        'muy',
        'sin',
        'sobre',
        'tambien',
        'me',
        'hay',
        'donde',
        'quien',
        'desde',
        'todo',
        'nos',
        'cuando',
        'hola',
        'gracias',
        'quiero',
        'puedo',
        'tiene',
        'tengo',
        'cuanto',
        'cuesta',
        'precio',
        'hijo',
        'hija',
        'nino',
        'nina',
        'anos',
        'edad',
        'kit',
        'incluye',
        'sirve',
        'imprimir',
        'comprar',
        'pago',
        'reembolso',
        'garantia',
        'cual',
        'cuales',
        'que',
        'como',
        'sabe',
        'lee',
        'leer',
        'escribir',
        'letras',
        'mi',
        'tu',
        'su',
        'usted',
        'vos',
        'hace',
        'donde',
        'necesito',
        'busco',
        'ayuda',
        'hijos',
        'ninos',
        'favor',
    ]
)
_EN = frozenset(
    [
        "i'm",
        "i'd",
        "i'll",
        "we're",
        "we've",
        "you're",
        "she's",
        "he's",
        "it's",
        "what's",
        "that's",
        "don't",
        "doesn't",
        "isn't",
        "can't",
        'looking',
        'something',
        'like',
        'know',
        'best',
        'old',
        'kid',
        'teacher',
        'homeschooling',
        'printable',
        'thank',
        'the',
        'and',
        'is',
        'are',
        'of',
        'to',
        'in',
        'for',
        'with',
        'what',
        'how',
        'does',
        'do',
        'can',
        'my',
        'it',
        'this',
        'that',
        'which',
        'you',
        'your',
        'on',
        'be',
        'have',
        'has',
        'from',
        'at',
        'about',
        'kit',
        'include',
        'includes',
        'price',
        'cost',
        'much',
        'child',
        'kids',
        'son',
        'daughter',
        'old',
        'years',
        'print',
        'buy',
        'payment',
        'refund',
        'guarantee',
        'hello',
        'hi',
        'thanks',
        'please',
        'want',
        'need',
        'help',
        'reading',
        'read',
        'write',
        'letters',
        'age',
        'would',
        'should',
        'could',
        'is',
        'there',
        'any',
        'we',
        'our',
        'me',
        'if',
        'or',
        'not',
    ]
)
# Frequent function words of languages we do not answer in (Portuguese, French, Italian, German).
_OTHER = frozenset(
    [
        'voce',
        'você',
        'não',
        'nao',
        'obrigado',
        'obrigada',
        'quanto',
        'custa',
        'meu',
        'minha',
        'filho',
        'filha',
        'anos',
        'crianca',
        'criança',
        'livro',
        'também',
        'tambem',
        'isso',
        'esse',
        'essa',
        'est',
        'le',
        'les',
        'des',
        'une',
        'pour',
        'avec',
        'mon',
        'ma',
        'fils',
        'fille',
        'ans',
        'combien',
        'coûte',
        'coute',
        'merci',
        'bonjour',
        'enfant',
        'aussi',
        'il',
        'ist',
        'und',
        'der',
        'die',
        'das',
        'ich',
        'nicht',
        'kind',
        'wie',
        'viel',
        'kostet',
        'danke',
        'ciao',
        'grazie',
        'quanto',
        'costa',
        'mio',
        'figlio',
        'figlia',
        'bambino',
        'anni',
        'anche',
        'sono',
    ]
)
# Words shared by Spanish and English (or product vocabulary) carry no signal.
_NEUTRAL = frozenset(['a', 'no', 'kit', 'pdf', 'ok', 'usd', 'hotmart', 'pequeverso'])


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize('NFKD', text.lower())
    return ''.join(c for c in decomposed if not unicodedata.combining(c))


def visitor_words(text: str, product_names: Iterable[str] = ()) -> list[str]:
    stripped = _CODE.sub(' ', text)
    stripped = _QUOTED.sub(' ', stripped)
    stripped = _URLISH.sub(' ', stripped)
    lowered = stripped.lower()
    for name in product_names:
        if name:
            lowered = lowered.replace(name.lower(), ' ')
    return _WORD.findall(lowered)


def detect(text: str, product_names: Iterable[str] = ()) -> Detected:
    words = [w for w in visitor_words(text, product_names) if w not in _NEUTRAL]
    if not words:
        return Detected.UNKNOWN
    folded = [_fold(w) for w in words]
    es = sum(1 for w in folded if w in _ES) + sum(2 for w in words if any(c in w for c in 'ñ¿¡'))
    en = sum(1 for w in folded if w in _EN)
    other = sum(1 for w in words if w in _OTHER or _fold(w) in _OTHER) + sum(
        2 for w in words if any(c in w for c in 'çãõ')
    )
    if text.lstrip().startswith(('¿', '¡')):
        es += 2
    best = max(es, en, other)
    if best == 0 or (best < 2 and len(words) > 2):
        return Detected.UNKNOWN
    leaders = [
        label
        for label, score in ((Detected.ES, es), (Detected.EN, en), (Detected.OTHER, other))
        if score == best
    ]
    if len(leaders) != 1:
        return Detected.UNKNOWN
    return leaders[0]


def reply_language(
    question: str,
    previous: Sequence[Language],
    ui_locale: Language | None,
    product_names: Iterable[str] = (),
) -> Language | None:
    """Language for this answer, or None when the visitor writes in an unsupported language."""
    detected = detect(question, product_names)
    if detected is Detected.ES:
        return Language.ES
    if detected is Detected.EN:
        return Language.EN
    if detected is Detected.OTHER:
        return None
    if previous:
        return previous[-1]
    return ui_locale or Language.ES
