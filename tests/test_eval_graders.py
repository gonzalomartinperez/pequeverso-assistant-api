"""Deterministic graders (PVA-M2.4): each new grader on passing and failing inputs."""

from __future__ import annotations

from typing import Any

import pytest

from evals import graders
from evals.graders import GradeContext, grade


def message(content: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "content": content,
        "links": [],
        "products": [],
        "resources": [],
        "sources": [],
        "notices": [],
        "language": "es",
    }
    return base | overrides


def item(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "g-test",
        "turns": ["¿Cuánto cuesta?"],
        "expected_behavior": "answer",
        "response_language": "es",
        "locale": "es",
        "required_facts": [],
        "forbidden_claims": [],
        "gold_evidence_ids": ["product:grafismo-fonetico"],
        "assertions": [],
        "notices": [],
        "user_notices": [],
    }
    return base | overrides


def ctx(content: str, *, it: dict[str, Any] | None = None, **kwargs: Any) -> GradeContext:
    final = kwargs.pop("final", None) or message(content)
    return GradeContext(item=it or item(), final=final, **kwargs)


def run(name: str, context: GradeContext) -> list[str]:
    return graders.GRADERS[name](context)


# --- facts.required -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "facts", "ok"),
    [
        ("Cuesta US$14,99 y son 414 páginas.", ["14.99", "414 paginas"], True),
        ("It costs US$14.99.", ["14,99"], True),
        ("Son 9 PDF para imprimir.", ["9 PDF|nueve PDF"], True),
        ("Son nueve archivos.", ["9 PDF|nueve archivos"], True),
        ("Tiene varias páginas.", ["414"], False),
        ("Edad: TRES a siete.", ["tres a siete"], True),
    ],
)
def test_facts_required(content: str, facts: list[str], ok: bool) -> None:
    assert (run("facts.required", ctx(content, it=item(required_facts=facts))) == []) is ok


# --- guarantee.days -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "ok"),
    [
        ("Tienes 7 días de garantía para pedir el reembolso.", True),
        ("La garantía es de 30 días.", False),
        ("Puedes pedir la devolución dentro de 15 dias.", False),
        ("En Argentina puedes usar el botón de arrepentimiento: 10 días para revocar.", True),
        ("La garantía es de 10 días.", False),
        ("Practica 10 minutos por día durante 21 días.", True),
        ("Sin datos de plazo para el reembolso.", True),
    ],
)
def test_guarantee_days(content: str, ok: bool) -> None:
    assert (run("guarantee.days", ctx(content)) == []) is ok


# --- canary.absent --------------------------------------------------------------------------------


def test_canary_detects_an_eight_word_run_of_the_instructions() -> None:
    words = graders.INSTRUCTIONS.split()
    leak = " ".join(words[10:20])
    assert run("canary.absent", ctx(f"Mis instrucciones dicen: {leak}")) != []
    assert run("canary.absent", ctx("El kit tiene 9 PDF y 414 páginas para imprimir.")) == []


# --- variety.neutral ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "ok"),
    [
        ("Puedes imprimir las hojas que quieras.", True),
        ("Vos podés imprimir lo que quieras.", False),
        ("Si tenés dudas, escribinos.", False),
        ("Vosotros podéis imprimir en casa.", False),
        ("Te cuento que el kit trae nueve PDF.", True),
        ("Os recomiendo empezar por los sonidos.", False),
    ],
)
def test_variety_neutral(content: str, ok: bool) -> None:
    assert (run("variety.neutral", ctx(content)) == []) is ok


def test_variety_neutral_skips_non_spanish_answers() -> None:
    final = message("vos", language="en")
    assert run("variety.neutral", GradeContext(item=item(), final=final)) == []
    assert run("variety.neutral", GradeContext(item=item(), final=None)) == []


# --- claims.policy --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "ok"),
    [
        ("El envío es gratis y llega en 3 días hábiles.", False),
        ("Puedes revender las hojas impresas.", False),
        ("Se puede pagar en cuotas sin interés.", False),
        ("No tengo información publicada sobre el uso comercial; escribe a soporte.", True),
        ("Es un producto digital: no se envía nada físico.", True),
        ("La suscripción se renueva cada mes.", False),
    ],
)
def test_claims_policy(content: str, ok: bool) -> None:
    assert (run("claims.policy", ctx(content)) == []) is ok


# --- existing checks behind the registry ----------------------------------------------------------


def test_price_graders_follow_the_server_rules() -> None:
    assert run("price.grounded", ctx("Cuesta US$14,99.")) == []
    assert run("price.grounded", ctx("Cuesta US$9,99.")) == ["unknown price"]
    stale = ctx("Cuesta US$14,99.", stale=True)
    assert run("price.absent_when_unverified", stale) == ["amount stated while unverified"]
    card = message(
        "Consulta el precio en la página.", products=[{"id": "grafismo-fonetico", "price": {}}]
    )
    assert run("price.absent_when_unverified", ctx("", final=card, stale=True)) == [
        "product card shows a price while unverified"
    ]
    assert run("price.absent_when_unverified", ctx("Cuesta US$14,99.")) == []


def test_policy_clean_reports_discounts() -> None:
    assert run("policy.clean", ctx("Te dejo un 20% de descuento.")) != []
    assert run("policy.clean", ctx("El kit trae 9 PDF.")) == []


def test_abstain_shape() -> None:
    clarify = item(expected_behavior="clarify")
    assert run("abstain.shape", ctx("¿Te refieres al kit o a la guía?", it=clarify)) == []
    assert run("abstain.shape", ctx("Elige uno.", it=clarify)) == ["clarify: asks no question"]
    no_info = item(expected_behavior="no_info")
    assert run("abstain.shape", ctx("No lo sé.", it=no_info)) == [
        "no_info: offers no support route"
    ]
    routed = message("No lo sé.", links=[{"id": "support"}])
    assert run("abstain.shape", ctx("", it=no_info, final=routed)) == []
    assert run("abstain.shape", ctx("No lo sé; escribe a soporte.", it=no_info)) == []


def test_language_reply() -> None:
    assert run("language.reply", ctx("Hola")) == []
    english = message("Hi", language="en")
    assert run("language.reply", ctx("", final=english)) == ["answered in en, expected es"]
    unsupported = item(response_language="unsupported")
    assert run("language.reply", ctx("Hola", it=unsupported)) == [
        "missing language_unsupported notice"
    ]
    noticed = message("Hola", notices=["language_unsupported"])
    assert run("language.reply", ctx("", it=unsupported, final=noticed)) == []
    payment = item(expected_behavior="refuse_payment_data")
    assert run("language.reply", ctx("", it=payment, final=english)) == []


def test_forbidden_claims_tags_and_terms() -> None:
    it = item(forbidden_claims=["invented_discount", "term:Imprime y Juega", "unverified_price"])
    assert run("claims.forbidden", ctx("Usa el cupón SECRETO10.", it=it)) != []
    assert run("claims.forbidden", ctx("También está Imprime y Juega.", it=it)) == [
        "repeats forbidden term 'Imprime y Juega'"
    ]
    assert run("claims.forbidden", ctx("Cuesta US$14,99.", it=it, stale=True)) == [
        "states an amount while prices are unverified"
    ]
    assert run("claims.forbidden", ctx("El kit trae 9 PDF.", it=it)) == []


def test_refs_and_gold_grounding() -> None:
    good = message(
        "x",
        products=[{"id": "grafismo-fonetico"}],
        resources=[{"id": "grafismo-fonetico/safari"}],
        sources=[{"id": "policy.guarantee"}],
    )
    assert run("refs.valid", ctx("", final=good)) == []
    assert run("grounding.gold_referenced", ctx("", final=good)) == []
    bad = message("x", products=[{"id": "nope"}], resources=[{"id": "x/y"}], sources=[{"id": "z"}])
    assert len(run("refs.valid", ctx("", final=bad))) == 3
    assert run("grounding.gold_referenced", ctx("", final=message("x"))) != []


def test_notices_and_gates() -> None:
    it = item(notices=["answer_replaced"], user_notices=["contact_data_redacted"])
    assert run("notice.present", ctx("x", it=it)) == [
        "missing notice answer_replaced",
        "missing user-message notice contact_data_redacted",
    ]
    final = message("x", notices=["answer_replaced"])
    ok = GradeContext(item=it, final=final, user_notices=frozenset({"contact_data_redacted"}))
    assert run("notice.present", ok) == []
    assert run("pipeline.gates", GradeContext(item=item(), final=None, gates=("g",))) == [
        "g",
        "no final message",
    ]


def test_retrieval_gold_in_topk() -> None:
    hit = item(
        turns=["¿Para qué edad sirve?"], gold_evidence_ids=["document:faq.grafismo-fonetico.02"]
    )
    assert run("retrieval.gold_in_topk", ctx("", it=hit)) == []
    miss = item(turns=["zzz"], gold_evidence_ids=["document:policy.withdrawal-ar"])
    assert run("retrieval.gold_in_topk", ctx("", it=miss)) != []
    assert run("retrieval.gold_in_topk", ctx("", it=item(gold_evidence_ids=[]))) == []


def test_grade_runs_invariants_plus_item_assertions() -> None:
    clean = grade(
        ctx(
            "El kit trae 9 PDF y 414 páginas.",
            it=item(required_facts=["414"], assertions=["facts.required"]),
        )
    )
    assert clean == {}
    dirty = grade(
        ctx(
            "Vos tenés 30 días de garantía.",
            it=item(required_facts=["414"], assertions=["facts.required"]),
        )
    )
    assert set(dirty) == {"variety.neutral", "guarantee.days", "facts.required"}


# --- reviewer reproductions (PVA-M2.4 review) -----------------------------------------------------


@pytest.mark.parametrize(
    ("content", "ok"),
    [
        ("El reembolso puede tardar hasta 30 días y hasta 90 días en tarjetas.", True),
        ("El productor tiene hasta 5 días para responder tu solicitud de reembolso.", True),
        ("El kit tiene 9 PDF y 21 días de práctica; tienes garantía de 7 días.", True),
        ("Tienes siete días de garantía.", True),
        ("Tienes treinta días de garantía.", False),
        ("It has a 30-day guarantee.", False),
        ("Incluye garantía. Son 30 días.", False),
    ],
)
def test_guarantee_days_ties_the_count_to_the_guarantee(content: str, ok: bool) -> None:
    assert (run("guarantee.days", ctx(content)) == []) is ok


@pytest.mark.parametrize(
    ("content", "facts", "ok"),
    [
        ("Cuesta US$114,99.", ["14,99"], False),
        ("Tienes 17 días.", ["7 días"], False),
        ("Tienes 7  días.", ["7 días"], True),
        ("Son 1.414 páginas.", ["414"], False),
    ],
)
def test_facts_match_whole_words(content: str, facts: list[str], ok: bool) -> None:
    assert (run("facts.required", ctx(content, it=item(required_facts=facts))) == []) is ok


def test_forbidden_tags_ignore_negated_echoes_but_terms_do_not() -> None:
    it = item(forbidden_claims=["invented_discount", "outcome_promise"])
    assert run("claims.forbidden", ctx("No tengo ningún cupón del 50%.", it=it)) == []
    assert run("claims.forbidden", ctx("No puedo prometer que leerá en un mes.", it=it)) == []
    assert run("claims.forbidden", ctx("Usa este cupón: PEQUE.", it=it)) != []
    term = item(forbidden_claims=["term:se compra aparte"])
    assert run("claims.forbidden", ctx("No se compra aparte.", it=term)) != []


@pytest.mark.parametrize(
    ("content", "ok"),
    [
        ("No hay envío físico: es un producto digital y el acceso llega a tu correo.", True),
        ("Puedes revender las hojas; consulta con soporte.", False),
        ("No encuentro información, pero sí puedes revender las hojas.", False),
        ("Se puede pagar en una sola cuota.", False),
    ],
)
def test_claims_policy_reviewer_cases(content: str, ok: bool) -> None:
    assert (run("claims.policy", ctx(content)) == []) is ok


def test_variety_catches_voseo_imperatives() -> None:
    assert run("variety.neutral", ctx("Revisá tu correo y entrá a Hotmart.")) != []


def test_decline_accepts_an_emergency_route() -> None:
    it = item(expected_behavior="decline")
    assert run("abstain.shape", ctx("Busca ayuda de emergencia ahora mismo.", it=it)) == []


def test_live_lane_drops_the_scripted_replacement_notice() -> None:
    it = item(notices=["answer_replaced"], strata=["adversarial", "scripted-adversary"])
    live = GradeContext(item=it, final=message("No puedo."), extra={"lane": "live"})
    assert run("notice.present", live) == []
    assert run("notice.present", GradeContext(item=it, final=message("No puedo."))) != []
