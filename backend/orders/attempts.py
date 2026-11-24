from uuid import uuid4

from django.core.signing import BadSignature, Signer
from django.utils.crypto import salted_hmac

from cart.cart import CHECKOUT_CYCLE
from payments.models import PaymentDraft

from .models import CheckoutAttempt


def session_digest(session):
    return salted_hmac(
        "rasel.checkout.session", session.session_key or "", algorithm="sha256"
    ).hexdigest()


def current_key(session):
    cycle = session.get(CHECKOUT_CYCLE, "legacy")
    return salted_hmac(
        "rasel.checkout.cycle", cycle, secret=session_digest(session), algorithm="sha256"
    ).hexdigest()


def checkout_token(session):
    return Signer(salt=session_digest(session)).sign(current_key(session))


def submitted_key(session, token):
    if not session.session_key or not token or len(token) > 128:
        return None
    try:
        return Signer(salt=session_digest(session)).unsign(token)
    except BadSignature:
        return None


def result_for_key(session, key):
    return (
        CheckoutAttempt.objects.select_related("order", "draft", "draft__order")
        .filter(pk=key, session_digest=session_digest(session))
        .first()
    )


def closed_draft(draft):
    return (
        not draft.order_id
        and draft.stock_released_at is not None
        and draft.state in {"rejected", "cancelled", "expired", "released"}
    )


def restart_checkout(session):
    session[CHECKOUT_CYCLE] = uuid4().hex
    session.pop("active_payment_draft", None)


def existing_payment(session, *, check_attempts=False):
    """Include legacy reservations and drafts from a response the browser lost."""
    active_token = session.get("active_payment_draft")
    if active_token:
        draft = PaymentDraft.objects.select_related("order").filter(token=active_token).first()
        if draft and not closed_draft(draft):
            return draft
    if check_attempts:
        return (
            PaymentDraft.objects.select_related("order")
            .filter(
                checkout_attempt__session_digest=session_digest(session),
                order__isnull=True,
                stock_released_at__isnull=True,
            )
            .order_by("-created_at", "-pk")
            .first()
        )
    return None


def owns_draft(session, draft):
    if session.get("active_payment_draft") == str(draft.token):
        return True
    return session.session_key and CheckoutAttempt.objects.filter(
        session_digest=session_digest(session), draft=draft
    ).exists()
