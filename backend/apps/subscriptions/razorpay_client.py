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


def enabled():
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)


def _client():
    import razorpay

    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def create_order(amount, receipt, notes=None):
    paise = int((Decimal(str(amount)) * 100).quantize(Decimal("1")))
    if not enabled():
        return {"id": "order_demo_" + secrets.token_hex(7), "amount": paise, "currency": "INR", "demo": True}
    return _client().order.create({"amount": paise, "currency": "INR", "receipt": receipt[:40], "notes": notes or {}})


def verify_payment(order_id, payment_id, signature):
    if not enabled():
        return order_id.startswith("order_demo_")
    msg = f"{order_id}|{payment_id}".encode()
    expected = hmac.new(settings.RAZORPAY_KEY_SECRET.encode(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def verify_webhook(body: bytes, signature: str):
    secret = settings.RAZORPAY_WEBHOOK_SECRET
    if not secret:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def refund(payment_id, amount=None):
    if not enabled():
        return {"id": "rfnd_demo", "status": "processed"}
    data = {"amount": int(Decimal(str(amount)) * 100)} if amount else {}
    return _client().payment.refund(payment_id, data)
