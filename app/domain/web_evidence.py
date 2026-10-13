"""Fixed public platform procedures, separate from merchant facts and visitor data."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.domain.answer_policy import fold


class HelpTopic(StrEnum):
    DELIVERY = 'digital_delivery'
    REFUND = 'refund_process'
    SUPPORT = 'product_support'


@dataclass(frozen=True, slots=True)
class HelpSource:
    topic: HelpTopic
    article_id: str
    title: str
    url: str


SOURCES = (
    HelpSource(
        HelpTopic.DELIVERY,
        '209033897',
        'Hotmart · entrega digital',
        'https://help.hotmart.com/es/article/209033897/-como-recibire-el-producto-que-compre-en-hotmart-',
    ),
    HelpSource(
        HelpTopic.REFUND,
        '360061973392',
        'Hotmart · solicitud de reembolso',
        'https://help.hotmart.com/es/article/360061973392/como-solicitar-el-reembolso-de-mi-compra',
    ),
    HelpSource(
        HelpTopic.SUPPORT,
        '9312940657933',
        'Hotmart · ayuda sobre el producto',
        'https://help.hotmart.com/es/article/9312940657933/tenho-duvidas-referentes-ao-produto-que-comprei',
    ),
)
MAX_WEB_EVIDENCE_CHARS = 8000


@dataclass(frozen=True, slots=True)
class WebEvidence:
    source: HelpSource
    text: str
    sha256: str
    verified_at: datetime

    @property
    def id(self) -> str:
        return f'hotmart:{self.source.article_id}'


_DENIED = re.compile(
    r'\b(?:password|contrasena|credencial\w*|api key|clave secreta|system prompt|'
    r'instrucciones internas|datos de clientes|other customers|orders? status|'
    r'pedido ajeno|mi pedido|mi transaccion)\b|'
    r'\b(?:haz|ejecuta|tramita|procesa|realiza|issue|process|execute)\b.{0,45}'
    r'\b(?:reembolso|refund|pago|payment|compra|purchase|pedido|order)\b'
)


def topics_for(question: str, previous_question: str = '') -> tuple[HelpTopic, ...]:
    """Deterministic scope; external services never see this local selection input."""
    query = fold(question)
    if _DENIED.search(query):
        return ()
    # Only an explicitly referential short follow-up inherits the preceding visitor topic.
    if len(query) < 90 and re.search(r'\b(?:eso|entonces|y si|ese caso|that|then|what if)\b', query):
        query = f'{query} {fold(previous_question)}'
        if _DENIED.search(query):
            return ()
    topics: list[HelpTopic] = []
    if re.search(r'\b(?:reembolso|devolucion|refund|garantia)\b', query):
        topics.append(HelpTopic.REFUND)
    if re.search(r'\b(?:recibo|recibir|entrega|acceso|acceder|access|delivery|receive|descarga)\b', query):
        topics.append(HelpTopic.DELIVERY)
    if re.search(r'\b(?:soporte|support|productor|producer|falta contenido|missing content)\b', query):
        topics.append(HelpTopic.SUPPORT)
    return tuple(topics)


def evidence_payload(items: tuple[WebEvidence, ...]) -> str:
    return json.dumps(
        [
            {
                'id': item.id,
                'title': item.source.title,
                'text': item.text,
                'verified_at': item.verified_at.isoformat(),
                'sha256': item.sha256,
                'scope': 'general_platform_procedure_not_merchant_facts',
            }
            for item in items
        ],
        ensure_ascii=False,
        separators=(',', ':'),
    )


_GUARANTEE_DAYS = re.compile(
    r'\bgarantia\b[^.!?;\n]{0,45}?\b(\d+)\s+dias\b|'
    r'\b(\d+)\s+dias\b[^.!?;\n]{0,35}?\bgarantia\b|'
    r'\bguarantee\b[^.!?;\n]{0,45}?\b(\d+)\s+days\b|'
    r'\b(\d+)[- ]day\b[^.!?;\n]{0,35}?\bguarantee\b'
)
_PRIVATE_DETAIL_REQUEST = re.compile(
    r'\b(?:dime|enviame|comparte conmigo|pasame|indicame|tell me|send me|share with me|give me)\b'
    r'[^.!?;\n]{0,45}?\b(?:correo|email|e-mail|numero de (?:pedido|transaccion|compra)|'
    r'order number|transaction (?:number|id)|purchase (?:number|id))\b'
)
_REFUND_ENTITLEMENT = re.compile(
    r'\b(?:tu compra|your purchase)\s+(?:es elegible|is eligible|cumple los requisitos)\b|'
    r'\b(?:reembolso|refund)\b[^.!?;\n]{0,35}?\b(?:garantizado|guaranteed|sera aprobado|will be approved)\b|'
    r'\b(?:garantizado|guaranteed)\b[^.!?;\n]{0,35}?\b(?:reembolso|refund)\b'
)


_CATEGORICAL_PROCESSING_DELAY = re.compile(
    r'(?:^|[.!?;\n])\s*(?:'
    r'(?:la solicitud|el reembolso) no se procesa (?:de inmediato|inmediatamente)|'
    r'(?:the request|the refund|the refund request) is not processed immediately)\b'
)


def negated_at(text: str, position: int) -> bool:
    prefix = re.split(r'[.!?;,\n]|\b(?:pero|but|however|y|and)\b', text[max(0, position - 80) : position])[-1]
    negation = re.search(r'\b(?:no|not|nunca|never)\s+(?:\w+\s+){0,4}$', prefix)
    if negation is None:
        return False
    # A reminder not to forget asserts the following policy; it does not deny it.
    return not re.match(r'(?:no|not|nunca|never)\s+(?:olvida|olvides|olvidar|forget)\b', negation.group())


def unsupported_platform_policy(text: str, merchant_policy_texts: tuple[str, ...]) -> bool:
    """Bounded positive-claim guard, not a claim of complete semantic entailment checking."""
    normalized = fold(text)
    if _CATEGORICAL_PROCESSING_DELAY.search(normalized):
        return True
    # Merchant's published buyer window; processing/bank delays elsewhere are not guarantee terms.
    days = {
        int(match.group(1))
        for policy in merchant_policy_texts
        for match in re.finditer(r'\b(?:tienes|dispones de)\s+(\d+)\s+dias\b', fold(policy))
    }
    for match in _GUARANTEE_DAYS.finditer(normalized):
        day_group = next(index for index, group in enumerate(match.groups(), 1) if group is not None)
        if int(match.group(day_group)) not in days and not negated_at(normalized, match.start(day_group)):
            return True
    for match in [*_REFUND_ENTITLEMENT.finditer(normalized), *_PRIVATE_DETAIL_REQUEST.finditer(normalized)]:
        assertion = re.search(
            r'\b(?:garantizado|guaranteed|sera aprobado|will be approved|es elegible|is eligible|cumple los requisitos)\b',
            match.group(),
        )
        position = match.start() + assertion.start() if assertion else match.start()
        if not negated_at(normalized, position):
            return True
    return False
