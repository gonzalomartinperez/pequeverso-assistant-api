"""A bounded public-information provenance policy, independent of generation or retrieval.

Recognize only short meta-questions about the information in the conversation. Product
identity comes from the active catalog or immediate typed history, never from a guessed
product default or a claim that the producer, an order or availability was authenticated.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.domain.answer_policy import fold
from app.domain.catalog import Catalog
from app.domain.conversation import Message, Notice, Role
from app.domain.language import Language
from app.domain.redaction import EMAIL_PLACEHOLDER, PHONE_PLACEHOLDER

_MAX_CHARS = 240
_WORD = re.compile(r'[a-z]+')
_INFO = re.compile(
    r'\b(?:datos|informacion|info|respuesta|respuestas|dices|afirmas|data|information|facts|answer|answers|details)\b'
)
_WHERE = re.compile(r'\b(?:donde|where|como|how)\b')
_SOURCE = re.compile(r'\b(?:fuente|fuentes|source|sources)\b')
_ORIGIN = re.compile(
    r'\b(?:origen|procedencia|provenance|from|sacas|obtienes|obtenes|sale|salen|viene|vienen|proviene|provienen|procede|proceden|tomas|consultas|extraes|consigues|get|getting|obtain|come|comes)\b'
)
_BASED = re.compile(
    r'\b(?:en que te basas|en que se basa|sobre que te basas)\b|\b(?:base|based|basing)\b.*\bon\b'
)
# Reject mixed requests before checking the small conversational vocabulary. These topics
# need the existing language/security/grounding paths rather than an informational shortcut.
_OUT_OF_SCOPE = re.compile(
    r'\b(?:precio|precios|cuesta|cuestan|coste|costo|price|prices|cost|costs|stock|disponible|available|'
    r'promocion|descuento|discount|comprar|compra|pagar|pago|payment|buy|order|orders|pedido|pedidos|'
    r'garantia|guarantee|devolucion|refund|download|descargar|descarga|acceso|access|entrega|delivery|'
    r'pdf|paginas|pages|incluye|incluyen|includes|include|bonos|bonuses|contenido|format|formato|'
    r'salud|medico|medical|health|diagnostico|anemia|alergia|alergias|cura|curar|cure|treat|'
    r'atraganta|choking|recomendar|recommend|codigo|code|prompt|prompts|instrucciones|instructions|'
    r'system|interno|interna|internal|secreto|secret|secrets|clave|key|keys|credenciales|credentials|'
    r'cliente|clientes|customer|customers|personales|personal|database|sql|api)\b'
)
_PROVENANCE_VOCABULARY = (
    'son tienes tenes utiliza utilizas extraes consigues '
    'a about afirmas al algo alguna algunas alguno algunos all an and answer answers are as at basa '
    'basais basan basas base based basing baso by can catalog catalogo citar cite come comes como con '
    'consult consultas consulted contas could cual cuales cuando cuentas dar data datos de decir decirme '
    'del details detalles dices did dime do does donde el ella ellas ellos en es esa esas ese esos esta '
    'estas este estos explain explicame explicarme facts favor for from fuente fuentes get getting give '
    'gracias guia guias guide guides gustaria have how i in indicar indicas info informacion information '
    'is it la las lo los manual material materials me mi mis my obtain obtenes obtienes of on or origen '
    'para please podes podria podrias por porfavor porque procede proceden procedencia product producto '
    'productos products provenance proviene provienen public publica publicada publicado published puede '
    'puedes que quiero re respuesta respuestas s sabe saber sabes sacas sale salen se sobre some source '
    'sources su sus te tell thank thanks that the their them these this those ti tienda to toda todas '
    'todo todos tomas tu tus un una unas unos us usa usas use using viene vienen what where which who why '
    'with would you your '
)
_WORDS = frozenset(_PROVENANCE_VOCABULARY.split())


def _identities(question: str, catalog: Catalog) -> frozenset[str]:
    found: set[str] = set()
    for product in catalog.products:
        if any(
            re.search(r'(?<!\w)' + re.escape(fold(value)) + r'(?!\w)', question)
            for value in (product.id, product.id.replace('-', ' '), product.name)
        ):
            found.add(product.id)
    return frozenset(found)


def _provenance_only(question: str, catalog: Catalog) -> bool:
    if not question or len(question) > _MAX_CHARS or '\n' in question:
        return False
    text = fold(question)
    for marker in (EMAIL_PLACEHOLDER, PHONE_PLACEHOLDER):
        text = text.replace(fold(marker), ' ')
    words_only = text
    for value in (
        catalog.site.name,
        *(value for p in catalog.products for value in (p.name, p.id, p.id.replace('-', ' '))),
    ):
        words_only = re.sub(r'(?<!\w)' + re.escape(fold(value)) + r'(?!\w)', ' ', words_only)
    if _OUT_OF_SCOPE.search(words_only):
        return False
    if not set(_WORD.findall(words_only)).issubset(_WORDS):
        return False
    return bool(
        _SOURCE.search(words_only)
        or _BASED.search(words_only)
        or (
            _INFO.search(words_only)
            and _ORIGIN.search(words_only)
            and (_WHERE.search(words_only) or re.search(r'\b(?:origen|procedencia|provenance)\b', words_only))
        )
    )


def _local_reply(catalog: Catalog, language: Language, product_id: str | None = None) -> str:
    product = catalog.product(product_id) if product_id is not None else None
    if language is Language.EN:
        base = f'I use the public information published by {catalog.site.name}'
        return (
            f'{base} about “{product.name}”.'
            if product is not None
            else base + '. Which product would you like to ask about?'
        )
    base = f'Me baso en la información pública de {catalog.site.name}'
    return (
        f'{base} sobre «{product.name}».'
        if product is not None
        else base + '. ¿Sobre cuál de los productos quieres consultar?'
    )


def _bare_identity(question: str, catalog: Catalog) -> frozenset[str]:
    text = fold(question.strip())
    return frozenset(
        product.id
        for product in catalog.products
        if text in {fold(product.name), fold(product.id), fold(product.id.replace('-', ' '))}
    )


def _plain_local_answer(answer: Message) -> bool:
    details = answer.details
    return not (
        details.products
        or details.resources
        or details.links
        or details.sources
        or details.follow_ups
        or details.notices
    )


def _clarified_identity(question: str, catalog: Catalog, history: Sequence[Message]) -> frozenset[str]:
    if len(history) < 2 or history[-2].role is not Role.USER or history[-1].role is not Role.ASSISTANT:
        return frozenset()
    previous_question, answer = history[-2:]
    if (
        not _provenance_only(previous_question.content, catalog)
        or not _plain_local_answer(answer)
        or answer.content not in {_local_reply(catalog, Language.ES), _local_reply(catalog, Language.EN)}
    ):
        return frozenset()
    named = _bare_identity(question, catalog)
    return named if len(named) == 1 else frozenset()


def _previous_identity(history: Sequence[Message], catalog: Catalog) -> frozenset[str]:
    if not history or history[-1].role is not Role.ASSISTANT:
        return frozenset()
    answer = history[-1]
    question = history[-2] if len(history) > 1 and history[-2].role is Role.USER else None
    if any(
        notice in answer.details.notices
        for notice in (Notice.PAYMENT_DATA_REFUSED, Notice.LANGUAGE_UNSUPPORTED, Notice.ANSWER_REPLACED)
    ):
        return frozenset()
    typed = frozenset(p.id for p in answer.details.products if catalog.product(p.id) is not None)
    named = _identities(fold(question.content), catalog) if question is not None else frozenset()
    if len(typed) == len(answer.details.products) == 1:
        # A contradictory latest question is not authority for the previous card's identity.
        return typed if not named or named == typed else frozenset()
    if answer.details.products:
        return frozenset()  # Multiple/unknown references must not select an older product.
    if question is not None and len(named) == 1:
        if _provenance_only(question.content, catalog):
            return named  # Only the immediate explicit provenance turn; never search older text.
        identity = next(iter(named))
        if (
            _bare_identity(question.content, catalog) == named
            and _plain_local_answer(answer)
            and answer.content
            in {
                _local_reply(catalog, Language.ES, identity),
                _local_reply(catalog, Language.EN, identity),
            }
        ):
            return named  # The exact preceding local clarification completion, not inferred history.
    return frozenset()


def provenance_reply(
    question: str, catalog: Catalog, history: Sequence[Message], language: Language
) -> str | None:
    """Return a brief local origin answer, or None to retain the ordinary assistant flow."""
    clarified = _clarified_identity(question, catalog, history)
    if not _provenance_only(question, catalog) and not clarified:
        return None
    named = clarified or _identities(fold(question), catalog)
    if not named and history and history[-1].role is Role.ASSISTANT:
        for source in history[-1].details.sources:
            document = catalog.document(source.id)
            if document is None or document.url != source.url:
                # External or historical evidence keeps its existing attribution flow.
                return None
    selected = named or _previous_identity(history, catalog)
    if not selected and len(catalog.products) == 1:
        selected = frozenset((catalog.products[0].id,))
    product = catalog.product(next(iter(selected))) if len(selected) == 1 else None
    if product is not None:
        return _local_reply(catalog, language, product.id)
    if not selected:
        return _local_reply(catalog, language)
    if language is Language.EN:
        return f'I use the public information published by {catalog.site.name}.'
    return f'Me baso en la información pública de {catalog.site.name}.'
