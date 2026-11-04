"""Outbound email / SMS / WhatsApp using credentials from the super admin settings.

Every function is fail-safe: it returns (ok, error) and never raises, so a
mis-configured provider can't break billing or ordering.
"""
import json
import logging
import urllib.parse
import urllib.request

from django.conf import settings as dj_settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string

from .models import get_settings

log = logging.getLogger("servora.messaging")


def email_connection(ps=None):
    ps = ps or get_settings()
    if "locmem" in dj_settings.EMAIL_BACKEND:  # test runner
        return get_connection()
    # Explicit SMTP connection so the "test email" button works before email is switched on.
    return get_connection("django.core.mail.backends.smtp.EmailBackend", host=ps.email_host, port=ps.email_port,
                          username=ps.email_username, password=ps.email_password, use_tls=ps.email_use_tls and not ps.email_use_ssl,
                          use_ssl=ps.email_use_ssl, timeout=10)


def send_email(to, subject, template, context=None, force=False):
    """Render ``emails/<template>.html`` and send it. ``force`` ignores the enabled flag (test email)."""
    ps = get_settings()
    to = [t for t in ([to] if isinstance(to, str) else to) if t]
    if not to:
        return False, "No recipient"
    if not (ps.email_enabled or force):
        return False, "Email is disabled in platform settings"
    if not ps.email_host and "locmem" not in dj_settings.EMAIL_BACKEND:
        return False, "SMTP host is not configured"
    ctx = {"site_url": ps.site_url.rstrip("/"), "site_name": ps.site_name, "support_email": ps.support_email, "support_phone": ps.support_phone, **(context or {})}
    html = render_to_string(f"emails/{template}.html", ctx)
    text = render_to_string("emails/_plain.txt", {"body": _strip(html)})
    sender = f"{ps.email_from_name} <{ps.email_from or ps.email_username}>"
    try:
        msg = EmailMultiAlternatives(subject, text, sender, to, connection=email_connection(ps),
                                     reply_to=[ps.support_email] if ps.support_email else None)
        msg.attach_alternative(html, "text/html")
        msg.send()
        return True, ""
    except Exception as exc:
        log.warning("Email to %s failed: %s", to, exc)
        return False, str(exc)


def _strip(html):
    import re

    text = re.sub(r"<(br|/p|/tr|/h\d|/div)[^>]*>", "\n", html)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _post(url, data=None, headers=None, json_body=None, auth=None):
    body = json.dumps(json_body).encode() if json_body is not None else urllib.parse.urlencode(data or {}).encode()
    req = urllib.request.Request(url, data=body, headers=headers or {}, method="POST")
    if json_body is not None:
        req.add_header("Content-Type", "application/json")
    if auth:
        import base64

        req.add_header("Authorization", "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode())
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.read().decode()


def _india(phone):
    digits = "".join(c for c in phone if c.isdigit())
    return digits if len(digits) > 10 else "91" + digits


def send_sms(phone, message, force=False):
    ps = get_settings()
    if ps.sms_provider == "none" or not phone:
        return False, "SMS is disabled"
    try:
        if ps.sms_provider == "twilio":
            _post(f"https://api.twilio.com/2010-04-01/Accounts/{ps.sms_account_sid}/Messages.json",
                  {"To": "+" + _india(phone), "From": ps.sms_sender_id, "Body": message}, auth=(ps.sms_account_sid, ps.sms_api_key))
        elif ps.sms_provider == "msg91":
            _post("https://control.msg91.com/api/v5/flow/", headers={"authkey": ps.sms_api_key},
                  json_body={"template_id": ps.sms_template_id, "sender": ps.sms_sender_id, "short_url": "0",
                             "recipients": [{"mobiles": _india(phone), "message": message}]})
        elif ps.sms_provider == "fast2sms":
            _post("https://www.fast2sms.com/dev/bulkV2", headers={"authorization": ps.sms_api_key},
                  json_body={"route": "q", "message": message, "numbers": phone[-10:]})
        return True, ""
    except Exception as exc:
        log.warning("SMS to %s failed: %s", phone, exc)
        return False, str(exc)


def send_whatsapp(phone, message):
    ps = get_settings()
    if not (ps.whatsapp_enabled and ps.whatsapp_token and ps.whatsapp_phone_number_id and phone):
        return False, "WhatsApp is disabled"
    try:
        _post(f"https://graph.facebook.com/v20.0/{ps.whatsapp_phone_number_id}/messages",
              headers={"Authorization": f"Bearer {ps.whatsapp_token}"},
              json_body={"messaging_product": "whatsapp", "to": _india(phone), "type": "text", "text": {"body": message}})
        return True, ""
    except Exception as exc:
        log.warning("WhatsApp to %s failed: %s", phone, exc)
        return False, str(exc)


def notify_customer(order, event):
    """Order updates to the diner by email + SMS/WhatsApp (whatever is enabled)."""
    track = f"/t/{order.tracking_token}/"
    texts = {
        "placed": f"{order.restaurant.name}: order #{order.number} received. Total Rs.{order.total}. Track: {{base}}{track}",
        "accepted": f"{order.restaurant.name}: your order #{order.number} is confirmed and being prepared.",
        "out_for_delivery": f"{order.restaurant.name}: order #{order.number} is out for delivery. Share OTP "
                            f"{getattr(getattr(order, 'delivery', None), 'otp', '')} with the rider.",
        "delivered": f"{order.restaurant.name}: order #{order.number} delivered. Enjoy your meal!",
    }
    if event not in texts:
        return
    base = get_settings().site_url.rstrip("/")
    msg = texts[event].replace("{base}", base)
    if order.customer_phone:
        ok, _ = send_whatsapp(order.customer_phone, msg)
        if not ok:
            send_sms(order.customer_phone, msg)
    email = order.customer.email if order.customer_id else ""
    if email and event == "placed":
        send_email(email, f"Order #{order.number} confirmed — {order.restaurant.name}", "order_confirmation",
                   {"order": order, "track_url": base + track})
