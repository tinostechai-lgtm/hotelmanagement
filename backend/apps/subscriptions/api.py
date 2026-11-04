import json

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.tenants.middleware import resolve_restaurant

from . import razorpay_client
from .models import FEATURES, Plan, SaasPayment, Subscription


class PlanSerializer(serializers.ModelSerializer):
    feature_labels = serializers.ListField(read_only=True)

    class Meta:
        model = Plan
        exclude = ["razorpay_plan_monthly", "razorpay_plan_yearly"]


@api_view(["GET"])
@permission_classes([AllowAny])
def plans(request):
    return Response({"features": FEATURES, "plans": PlanSerializer(Plan.objects.filter(is_public=True), many=True).data})


def _owner_restaurant(request):
    r = resolve_restaurant(request, request.user)
    m = getattr(request, "membership", None)
    if not r or not m or not m.can("billing"):
        return None
    return r


def gst(amount):
    return (amount * 18 / 100).quantize(amount.__class__("0.01"))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def current(request):
    r = resolve_restaurant(request, request.user)
    sub = r.subscription if r else None
    return Response({
        "plan": PlanSerializer(sub.plan).data if sub else None, "status": sub.status if sub else None, "cycle": sub.cycle if sub else None,
        "current_period_end": sub.current_period_end if sub else None, "days_left": sub.days_left if sub else 0,
        "is_active": sub.is_active if sub else False,
        "payments": [{"id": p.id, "plan": p.plan.name, "amount": str(p.amount + p.gst), "status": p.status, "date": p.created_at}
                     for p in (r.saas_payments.all()[:20] if r else [])],
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def checkout(request):
    """Create a Razorpay order for a plan. Returns Razorpay Checkout options."""
    r = _owner_restaurant(request)
    if not r:
        return Response({"detail": "Only the owner can manage the subscription"}, status=403)
    plan = Plan.objects.filter(code=request.data.get("plan"), is_public=True).first()
    if not plan or not plan.price_monthly:
        return Response({"detail": "Choose a valid plan (contact sales for Enterprise)"}, status=400)
    cycle = "yearly" if request.data.get("cycle") == "yearly" else "monthly"
    amount = plan.price_yearly if cycle == "yearly" else plan.price_monthly
    tax = gst(amount)
    order = razorpay_client.create_order(amount + tax, f"sub-{r.id}-{plan.code}", {"restaurant": r.id, "plan": plan.code, "cycle": cycle})
    SaasPayment.objects.create(restaurant=r, plan=plan, cycle=cycle, amount=amount, gst=tax, razorpay_order_id=order["id"])
    return Response({
        "key": settings.RAZORPAY_KEY_ID or "rzp_test_demo", "order_id": order["id"], "amount": order["amount"], "currency": "INR",
        "name": "Servora", "description": f"{plan.name} plan — {cycle}", "demo": bool(order.get("demo")),
        "prefill": {"name": str(request.user), "contact": request.user.username, "email": request.user.email},
    })


@transaction.atomic
def _mark_paid(pay, payment_id):
    if pay.status == "paid":
        return
    pay.status, pay.razorpay_payment_id, pay.paid_at = "paid", payment_id, timezone.now()
    pay.save()
    sub = pay.restaurant.subscription
    if sub is None or sub.plan_id != pay.plan_id:
        sub = Subscription(restaurant=pay.restaurant, plan=pay.plan, current_period_end=timezone.now())
    if sub.status != "active":
        sub.current_period_end = timezone.now()
    sub.plan = pay.plan
    sub.activate(pay.cycle)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def verify(request):
    r = _owner_restaurant(request)
    d = request.data
    pay = SaasPayment.objects.filter(restaurant=r, razorpay_order_id=d.get("razorpay_order_id")).first()
    if not pay:
        return Response({"detail": "Payment not found"}, status=404)
    if not razorpay_client.verify_payment(d.get("razorpay_order_id"), d.get("razorpay_payment_id"), d.get("razorpay_signature")):
        pay.status = "failed"
        pay.save()
        return Response({"detail": "Payment verification failed"}, status=400)
    _mark_paid(pay, d.get("razorpay_payment_id", "demo"))
    return Response({"ok": True, "plan": pay.plan.name, "valid_till": pay.restaurant.subscription.current_period_end})


@csrf_exempt
def webhook(request):
    """Razorpay webhook: payment.captured / order.paid for both SaaS plans and
    restaurant customer orders. Configure URL: /api/razorpay/webhook"""
    if request.method != "POST":
        return HttpResponse(status=405)
    if not razorpay_client.verify_webhook(request.body, request.headers.get("X-Razorpay-Signature", "")):
        return HttpResponse("bad signature", status=400)
    event = json.loads(request.body or b"{}")
    if event.get("event") in ("payment.captured", "order.paid"):
        ent = event["payload"]["payment"]["entity"]
        oid, pid = ent.get("order_id"), ent.get("id")
        pay = SaasPayment.objects.filter(razorpay_order_id=oid).first()
        if pay:
            _mark_paid(pay, pid)
        else:
            from apps.operations.models import Payment
            from apps.operations.services import confirm_payment

            p = Payment.objects.filter(razorpay_order_id=oid, status="pending").first()
            if p:
                confirm_payment(p, pid)
    return HttpResponse("ok")
