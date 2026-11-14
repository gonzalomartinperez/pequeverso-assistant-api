"""Idempotency includes content and all effective visitor policy fields."""

from dataclasses import replace

from hypothesis import example, given
from hypothesis import strategies as st

from app.application.chat import _request_hash
from app.domain.visitor_context import VisitorContext


@given(
    content=st.text(alphabet='abcXYZ012 áñü🙂\n\r\t\x00"\\', max_size=80),
    page=st.one_of(st.none(), st.sampled_from(["/", "/soporte"])),
    opened=st.sampled_from(["/", "/soporte"]),
    current=st.sampled_from(["/", "/privacidad"]),
    presentation=st.sampled_from(["compact", "expanded", "page"]),
    language=st.sampled_from([None, "es"]),
)
@example(
    content="¿Precio?",
    page=None,
    opened="/",
    current="/privacidad",
    presentation="compact",
    language=None,
)
def test_request_hash_tracks_every_field(content, page, opened, current, presentation, language):
    """Row 9: every effective field independently changes a deterministic hash."""
    context = VisitorContext(opened, current, presentation)
    original = _request_hash(content, page, context, language)
    assert _request_hash(content, page, context, language) == original
    changes = [
        (content + "!", page, context, language),
        (content, "/soporte" if page != "/soporte" else "/", context, language),
        (
            content,
            page,
            replace(context, opened_path="/soporte" if opened == "/" else "/"),
            language,
        ),
        (
            content,
            page,
            replace(context, current_path="/privacidad" if current == "/" else "/"),
            language,
        ),
        (
            content,
            page,
            replace(context, presentation="expanded" if presentation != "expanded" else "compact"),
            language,
        ),
        (content, page, context, "es" if language is None else None),
    ]
    assert all(_request_hash(*changed) != original for changed in changes)
