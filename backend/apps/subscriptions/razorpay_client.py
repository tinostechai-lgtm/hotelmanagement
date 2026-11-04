"""Thin Razorpay wrapper (Orders API + signature verification).

Used for both SaaS plan payments and restaurant customers paying for
online / QR orders. When keys are not configured we run in *demo mode*: a
fake order id is generated and checkout is simulated so the whole flow can be
tried end-to-end without real money.
"""
import hashlib
import hmac
import secrets
from decimal import Decimal

from django.conf import settings


def _creds():
    """Super-admin settings win; environment variables are a fallback."""
    from apps.superadmin.models import get_settings

    ps = get_settings()
    return (ps.razorpay_key_id or settings.RAZORPAY_KEY_ID, ps.razorpay_key_secret or settings.RAZORPAY_KEY_SECRET,
            ps.razorpay_webhook_secret or settings.RAZORPAY_WEBHOOK_SECRET)


def key_id():
    return _creds()[0] or "rzp_test_demo"


def enabled():
    k, s, _ = _creds()
    return bool(k and s)


def _client():
    import razorpay

    k, s, _ = _creds()
    return razorpay.Client(auth=(k, s))


def check_credentials():
    """Return (ok, message) by making a harmless authenticated API call."""
    if not enabled():
        return False, "Key ID and Key Secret are required"
    try:
        _client().order.all({"count": 1})
        return True, "Connected to Razorpay"
    except Exception as exc:
        return False, f"Razorpay rejected the keys: {exc}"


def create_order(amount, receipt, notes=None):
    paise = int((Decimal(str(amount)) * 100).quantize(Decimal("1")))
    if not enabled():
        return {"id": "order_demo_" + secrets.token_hex(7), "amount": paise, "currency": "INR", "demo": True}
    return _client().order.create({"amount": paise, "currency": "INR", "receipt": receipt[:40], "notes": notes or {}})


def verify_payment(order_id, payment_id, signature):
    if not enabled():
        return order_id.startswith("order_demo_")
    msg = f"{order_id}|{payment_id}".encode()
    expected = hmac.new(_creds()[1].encode(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def verify_webhook(body: bytes, signature: str):
    secret = _creds()[2]
    if not secret:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def refund(payment_id, amount=None):
    if not enabled():
        return {"id": "rfnd_demo", "status": "processed"}
    data = {"amount": int(Decimal(str(amount)) * 100)} if amount else {}
    return _client().payment.refund(payment_id, data)
