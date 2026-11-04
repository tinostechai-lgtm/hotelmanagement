"""Customer segments & campaign sending for restaurant marketing."""
from datetime import timedelta

from django.core import signing
from django.db.models import Q
from django.utils import timezone

from .models import CampaignDelivery, Customer

BATCH = 200  # recipients per request (keeps each serverless call well under the time limit)


def segment_queryset(restaurant, segment, tag=""):
    qs = Customer.objects.filter(restaurant=restaurant, marketing_opt_in=True)
    now = timezone.now()
    if segment == "new":
        qs = qs.filter(visits__lte=1)
    elif segment == "regulars":
        qs = qs.filter(visits__gte=5)
    elif segment == "lapsed30":
        qs = qs.filter(Q(last_visit__lt=now - timedelta(days=30)))
    elif segment == "lapsed60":
        qs = qs.filter(Q(last_visit__lt=now - timedelta(days=60)))
    elif segment == "birthday":
        qs = qs.filter(birthday__month=timezone.localdate().month)
    elif segment == "top":
        qs = qs.filter(total_spent__gte=15000)
    elif segment == "tag" and tag:
        qs = qs.filter(tags__icontains=tag)
    return qs


def eligible(campaign):
    qs = segment_queryset(campaign.restaurant, campaign.segment, campaign.tag)
    if campaign.channel == "email":
        qs = qs.exclude(email="")
    else:
        qs = qs.exclude(phone="")
    return qs


def store_link(restaurant):
    from apps.superadmin.models import get_settings

    base = get_settings().site_url.rstrip("/")
    return f"{base}/s/{restaurant.slug}/" if base else f"/s/{restaurant.slug}/"


def render_message(campaign, customer):
    text = campaign.message
    for k, v in {"{name}": (customer.name or "there").split(" ")[0], "{restaurant}": campaign.restaurant.name,
                 "{link}": store_link(campaign.restaurant), "{coupon}": campaign.coupon.code if campaign.coupon else ""}.items():
        text = text.replace(k, v)
    return text


def unsubscribe_token(customer):
    return signing.dumps({"c": customer.pk}, salt="servora-unsub")


def send_batch(campaign):
    """Send to the next batch of not-yet-contacted customers. Returns (sent, failed, remaining)."""
    from apps.superadmin import messaging

    done_ids = CampaignDelivery.objects.filter(campaign=campaign).values_list("customer_id", flat=True)
    todo = list(eligible(campaign).exclude(pk__in=done_ids)[:BATCH])
    sent = failed = 0
    for c in todo:
        text = render_message(campaign, c)
        if campaign.channel == "email":
            from apps.superadmin.models import get_settings

            base = get_settings().site_url.rstrip("/")
            ok, err = messaging.send_email(c.email, campaign.subject or campaign.name, "campaign",
                                           {"body": text, "restaurant": campaign.restaurant, "link": store_link(campaign.restaurant),
                                            "unsubscribe_url": f"{base}/unsubscribe/{unsubscribe_token(c)}/" if base else ""})
        elif campaign.channel == "whatsapp":
            ok, err = messaging.send_whatsapp(c.phone, text)
        else:
            ok, err = messaging.send_sms(c.phone, text)
        CampaignDelivery.objects.create(campaign=campaign, customer=c, ok=ok, error=(err or "")[:200])
        sent += ok
        failed += not ok
    campaign.sent += sent
    campaign.failed += failed
    remaining = eligible(campaign).exclude(pk__in=CampaignDelivery.objects.filter(campaign=campaign).values_list("customer_id", flat=True)).count()
    campaign.status = "sending" if remaining else "sent"
    campaign.sent_at = timezone.now()
    campaign.save()
    return sent, failed, remaining
