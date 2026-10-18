"""Bounded public-catalog scope facts, separate from private history and generation."""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.domain.answer_policy import fold
from app.domain.catalog import Catalog
from app.domain.conversation import Message, Notice, Role
from app.domain.language import Language
from app.domain.redaction import EMAIL_PLACEHOLDER, PHONE_PLACEHOLDER

_CATALOG = re.compile(r'\b(?:catalogo|catalog|catalogue)\b')
_SOURCES = re.compile(r'\b(?:fuentes|sources)\b')
_OTHER = re.compile(
    r'\b(?:otros|otras|ajenas|ajenos|clientes|compradores|personas|other|others|customer|customers|buyers|people)\b'
)
_PRIVATE = re.compile(r'\b(?:privado|privada|privados|privadas|personales|private|personal|sensitive)\b')
_CONVERSATIONS = re.compile(
    r'\b(?:conversacion|conversaciones|chats|chat|mensajes|messages|conversations|conversation|historial|history)\b'
)
_CONTENT = re.compile(r'\b(?:datos|consultas|preguntas|data|questions|queries)\b')
_OWN = re.compile(r'\b(?:mi|mis|mio|mia|mios|mias|my|mine|our|ours|me|i)\b')
_OUT_OF_SCOPE = re.compile(
    r'\b(?:precio|precios|cuesta|price|prices|cost|stock|comprar|compra|pago|pagos|buy|payment|'
    r'pedido|pedidos|order|orders|refund|devolucion|garantia|guarantee|medical|medico|salud|health|'
    r'anemia|alergias|alergia|cura|cure|tratamiento|treatment|download|descarga|descargar|pdf|'
    r'clave|claves|key|keys|password|passwords|credenciales|credentials|codigo|code|prompt|'
    r'instrucciones|instructions|system|sql|api|muestra|muestrame|dame|show|reveal|print|ignora|ignore)\b'
)
_VOCABULARY_TEXT = (
    'a al alimenta alimentan almacenadas almacenados almacenan alguna algunas algun algunos an and are '
    'as at basa basan base based buyers by can catalog catalogo catalogue chat chats clientes '
    'compradores con contiene contienen contain contains conversacion conversaciones conversation '
    'conversations consultas could customer customers data datos de del derivan do does el ellas ellos '
    'en entran es esa esas ese esos esta estas este estos estan estar feed feeds for forman from fuente '
    'fuentes has have hay i include included includes incluyendo incluir incluyen incluye informacion '
    'information incorporan incorpora incorporates incorporate incorporates is it la las los lo '
    'materiales me mensajes messages no o of on or other others otras otros para part parte people personales '
    'personas personal please por preguntas private privada privadas privado privados product productos '
    'products public publica publicas publico publicos published published queries que questions s se '
    'sensitive si sobre son source sources su sus te that the their them these this those to tu tus un '
    'una unas unos usan usa usais usar use used uses using va van y you your '
)
_VOCABULARY = frozenset(_VOCABULARY_TEXT.split())


def catalog_scope_reply(
    question: str, catalog: Catalog, history: Sequence[Message], language: Language
) -> str | None:
    """Answer only catalog inclusion of other people's private data, never own-history queries."""
    if not question or len(question) > 240 or '\n' in question:
        return None
    text = fold(question)
    for marker in (EMAIL_PLACEHOLDER, PHONE_PLACEHOLDER):
        text = text.replace(fold(marker), ' ')
    if _OWN.search(text) or _OUT_OF_SCOPE.search(text):
        return None
    if not set(re.findall(r'[a-z]+', text)).issubset(_VOCABULARY):
        return None
    explicit_catalog = bool(_CATALOG.search(text))
    if not (explicit_catalog or _SOURCES.search(text)) or not _OTHER.search(text):
        return None
    if not (_CONVERSATIONS.search(text) or (_CONTENT.search(text) and _PRIVATE.search(text))):
        return None
    if not explicit_catalog and history and history[-1].role is Role.ASSISTANT:
        answer = history[-1]
        if Notice.ANSWER_REPLACED in answer.details.notices:
            return None
        for source in answer.details.sources:
            document = catalog.document(source.id)
            if document is None or document.url != source.url:
                return None  # Do not reinterpret an external/historical source's data policy.
    if language is Language.EN:
        return (
            'The catalog contains public product information; it does not include other '
            "people's conversations or private data."
        )
    return (
        'El catálogo contiene información pública sobre los productos; no incorpora '
        'conversaciones ni datos privados de otras personas.'
    )
