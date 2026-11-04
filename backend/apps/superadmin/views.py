from datetime import timedelta
from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.core.paginator import Paginator
from django.db import connection, transaction
from django.db.models import Count, Q, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.operations.models import Order
from apps.subscriptions.models import Plan, SaasPayment, Subscription
from apps.tenants.models import Restaurant

from . import messaging
from .forms import SECTIONS, PlanForm, SetupForm, SubscriptionAdjustForm, settings_form
from .models import get_settings

NAV = [("overview", "Overview", "layout-dashboard"), ("restaurants", "Restaurants", "store"), ("plans", "Plans & pricing", "badge-indian-rupee"),
       ("payments", "Payments", "receipt-indian-rupee"), ("users", "Users", "users"), ("settings", "Platform settings", "settings")]


def superuser_required(fn):
    @wraps(fn)
    def wrapper(request, *a, **kw):
        if not request.user.is_authenticated:
            return redirect(f"/login/?next={request.path}")
        if not request.user.is_superuser:
            raise Http404
        return fn(request, *a, **kw)
    return wrapper


def page(request, template, active, **ctx):
    return render(request, f"superadmin/{template}.html", {"sa_nav": NAV, "active": active, "ps": get_settings(), **ctx})


def mrr():
    total = Decimal("0")
    for s in Subscription.objects.filter(status="active", current_period_end__gte=timezone.now()).select_related("plan"):
        total += s.plan.price_yearly / 12 if s.cycle == "yearly" else s.plan.price_monthly
    return total.quantize(Decimal("1"))


def latest_subscriptions():
    """Current (latest) subscription per restaurant."""
    latest = {}
    for s in Subscription.objects.select_related("plan").order_by("restaurant_id", "-created_at"):
        latest.setdefault(s.restaurant_id, s)
    return latest


@superuser_required
def overview(request):
    now = timezone.now()
    subs = latest_subscriptions().values()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    paid = SaasPayment.objects.filter(status="paid")
    ps = get_settings()
    checklist = [
        ("Site address set", bool(ps.site_url), "general"),
        ("Razorpay keys added", bool(ps.razorpay_key_id and ps.razorpay_key_secret), "payments"),
        ("Razorpay webhook secret", bool(ps.razorpay_webhook_secret), "payments"),
        ("Email (SMTP) configured", bool(ps.email_enabled and ps.email_host), "email"),
        ("Support contact", bool(ps.support_email or ps.support_phone), "general"),
        ("Company GSTIN for invoices", bool(ps.company_gstin), "general"),
    ]
    return page(request, "overview", "overview",
                stats={
                    "restaurants": Restaurant.objects.count(),
                    "active_paid": sum(1 for s in subs if s.status == "active" and s.is_active),
                    "trials": sum(1 for s in subs if s.status == "trial" and s.is_active),
                    "expired": sum(1 for s in subs if not s.is_active),
                    "mrr": mrr(),
                    "revenue_month": paid.filter(paid_at__gte=month_start).aggregate(s=Sum("amount"))["s"] or 0,
                    "revenue_total": paid.aggregate(s=Sum("amount"))["s"] or 0,
                    "orders_today": Order.objects.filter(created_at__date=timezone.localdate()).count(),
                    "gmv_today": Order.objects.filter(created_at__date=timezone.localdate(), status="completed").aggregate(s=Sum("total"))["s"] or 0,
                },
                signups=Restaurant.objects.order_by("-created_at")[:8],
                expiring=sorted([s for s in subs if s.is_active and s.current_period_end <= now + timedelta(days=7)],
                                key=lambda s: s.current_period_end)[:10],
                recent_payments=paid.select_related("restaurant", "plan")[:8],
                checklist=checklist)


@superuser_required
def restaurants(request):
    q = request.GET.get("q", "").strip()
    qs = Restaurant.objects.select_related("owner").order_by("-created_at")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(slug__icontains=q) | Q(city__icontains=q) | Q(email__icontains=q))
    status = request.GET.get("status", "")
    subs = latest_subscriptions()
    rows = [(r, subs.get(r.id)) for r in qs]
    if status == "suspended":
        rows = [x for x in rows if not x[0].is_active]
    elif status == "trial":
        rows = [x for x in rows if x[1] and x[1].status == "trial"]
    elif status == "paid":
        rows = [x for x in rows if x[1] and x[1].status == "active"]
    elif status == "expired":
        rows = [x for x in rows if not x[1] or not x[1].is_active]
    pg = Paginator(rows, 50).get_page(request.GET.get("page"))
    return page(request, "restaurants", "restaurants", page_obj=pg, q=q, status=status)


@superuser_required
def restaurant_detail(request, pk):
    r = get_object_or_404(Restaurant, pk=pk)
    sub = r.subscription
    if request.method == "POST":
        act = request.POST.get("action")
        if act == "subscription":
            f = SubscriptionAdjustForm(request.POST)
            if f.is_valid():
                d = f.cleaned_data
                if sub is None:
                    sub = Subscription(restaurant=r, plan=d["plan"], current_period_end=d["valid_till"])
                sub.plan, sub.status, sub.cycle, sub.current_period_end = d["plan"], d["status"], d["cycle"], d["valid_till"]
                sub.save()
                messages.success(request, "Subscription updated")
            else:
                messages.error(request, f"Could not update: {f.errors.as_text()}")
        elif act == "extend":
            days = int(request.POST.get("days") or 0)
            if sub and days:
                sub.current_period_end = max(sub.current_period_end, timezone.now()) + timedelta(days=days)
                if sub.status in ("expired", "past_due"):
                    sub.status = "active"
                sub.save()
                messages.success(request, f"Extended by {days} days")
        elif act == "suspend":
            r.is_active, r.suspended_reason = False, request.POST.get("reason", "")[:200]
            r.save(update_fields=["is_active", "suspended_reason"])
            messages.success(request, f"{r.name} suspended")
        elif act == "activate":
            r.is_active, r.suspended_reason = True, ""
            r.save(update_fields=["is_active", "suspended_reason"])
            messages.success(request, f"{r.name} re-activated")
        elif act == "email_owner" and r.owner and r.owner.email:
            ok, err = messaging.send_email(r.owner.email, request.POST.get("subject", "")[:150], "admin_message",
                                           {"message": request.POST.get("message", ""), "restaurant": r})
            (messages.success if ok else messages.error)(request, "Email sent" if ok else f"Email failed: {err}")
        return redirect("superadmin:restaurant", pk=r.pk)
    week = timezone.now() - timedelta(days=7)
    orders = Order.objects.filter(restaurant=r)
    adjust = SubscriptionAdjustForm(initial={"plan": sub.plan_id if sub else None, "status": sub.status if sub else "active",
                                             "cycle": sub.cycle if sub else "monthly",
                                             "valid_till": timezone.localtime(sub.current_period_end).strftime("%Y-%m-%dT%H:%M") if sub else ""})
    return page(request, "restaurant_detail", "restaurants", r=r, sub=sub, adjust=adjust,
                staff=r.memberships.select_related("user", "role"),
                payments=r.saas_payments.select_related("plan")[:20],
                stats={"orders": orders.count(), "orders_week": orders.filter(created_at__gte=week).count(),
                       "sales_week": orders.filter(created_at__gte=week, status="completed").aggregate(s=Sum("total"))["s"] or 0,
                       "last_order": orders.order_by("-created_at").values_list("created_at", flat=True).first()})


@superuser_required
def plans(request):
    return page(request, "plans", "plans", plans=Plan.objects.all(),
                counts={p["plan_id"]: p["n"] for p in Subscription.objects.values("plan_id").annotate(n=Count("id"))})


@superuser_required
def plan_edit(request, pk=None):
    plan = get_object_or_404(Plan, pk=pk) if pk else None
    form = PlanForm(request.POST or None, instance=plan)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Plan saved")
        return redirect("superadmin:plans")
    return page(request, "plan_form", "plans", form=form, plan=plan)


@superuser_required
def payments(request):
    qs = SaasPayment.objects.select_related("restaurant", "plan")
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    return page(request, "payments", "payments", page_obj=Paginator(qs, 50).get_page(request.GET.get("page")), status=request.GET.get("status", ""))


@superuser_required
def users(request):
    User = get_user_model()
    q = request.GET.get("q", "").strip()
    qs = User.objects.order_by("-date_joined").prefetch_related("memberships__restaurant", "memberships__role")
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(email__icontains=q))
    if request.method == "POST":
        u = get_object_or_404(User, pk=request.POST.get("user"))
        act = request.POST.get("action")
        if u == request.user:
            messages.error(request, "You can't change your own account here")
        elif act == "toggle_active":
            u.is_active = not u.is_active
            u.save(update_fields=["is_active"])
            messages.success(request, f"{u} {'enabled' if u.is_active else 'disabled'}")
        elif act == "toggle_superuser":
            u.is_superuser = u.is_staff = not u.is_superuser
            u.save(update_fields=["is_superuser", "is_staff"])
            messages.success(request, f"{u} is {'now' if u.is_superuser else 'no longer'} a super admin")
        return redirect(request.get_full_path())
    return page(request, "users", "users", page_obj=Paginator(qs, 50).get_page(request.GET.get("page")), q=q)


@superuser_required
def settings_view(request, section="general"):
    if section not in SECTIONS:
        raise Http404
    ps = get_settings(fresh=True)
    Form = settings_form(section)
    form = Form(request.POST or None, instance=ps)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, f"{SECTIONS[section][0]} saved")
            return redirect("superadmin:settings", section=section)
        messages.error(request, "Please fix the errors below")
    host = request.build_absolute_uri("/").rstrip("/")
    return page(request, "settings", "settings", form=form, section=section, sections=SECTIONS, title=SECTIONS[section][0],
                webhook_url=f"{host}/api/razorpay/webhook", aggregator_url=f"{host}/api/integrations/<restaurant-slug>/<swiggy|zomato|other>/order")


@superuser_required
@require_POST
def settings_test(request, kind):
    if kind == "email":
        to = request.POST.get("to") or request.user.email
        ok, err = messaging.send_email(to, f"Test email from {get_settings().site_name}", "test", {"user": request.user}, force=True)
        msg = f"Test email sent to {to}" if ok else f"Email failed: {err}"
    elif kind == "razorpay":
        from apps.subscriptions.razorpay_client import check_credentials

        ok, msg = check_credentials()
    elif kind == "sms":
        ok, err = messaging.send_sms(request.POST.get("to", ""), f"Test SMS from {get_settings().site_name}")
        msg = "Test SMS sent" if ok else f"SMS failed: {err}"
    elif kind == "whatsapp":
        ok, err = messaging.send_whatsapp(request.POST.get("to", ""), f"Test message from {get_settings().site_name}")
        msg = "Test WhatsApp sent" if ok else f"WhatsApp failed: {err}"
    else:
        raise Http404
    (messages.success if ok else messages.error)(request, msg)
    return redirect(request.POST.get("back") or "superadmin:settings_home")


def setup(request):
    """First-run: create the platform super admin from the browser.
    Available only while no super admin exists."""
    User = get_user_model()
    if User.objects.filter(is_superuser=True).exists():
        return redirect("superadmin:overview" if request.user.is_authenticated and request.user.is_superuser else "web:login")
    form = SetupForm(request.POST or None, initial={"site_url": request.build_absolute_uri("/").rstrip("/")})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        with transaction.atomic():
            if User.objects.select_for_update().filter(is_superuser=True).exists():
                return redirect("web:login")
            first, _, last = d["name"].partition(" ")
            user = User.objects.create_superuser(username=d["phone"], email=d["email"], password=d["password"],
                                                 first_name=first, last_name=last, phone=d["phone"])
            ps = get_settings(fresh=True)
            ps.site_url = d.get("site_url") or ps.site_url
            ps.support_email = ps.support_email or d["email"]
            ps.save()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "Welcome! Finish the checklist below to go live.")
        return redirect("superadmin:overview")
    return render(request, "superadmin/setup.html", {"form": form})


def healthz(request):
    """Public health check (no secrets): app + database status."""
    from django.conf import settings

    data = {"app": "ok", "database": connection.vendor, "demo_mode": settings.DEMO_MODE}
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
        data["db_connection"] = "ok"
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        data["pending_migrations"] = len(pending)
        data["super_admin_exists"] = get_user_model().objects.filter(is_superuser=True).exists()
    except Exception as exc:
        data["db_connection"] = "error"
        data["error"] = exc.__class__.__name__
        return JsonResponse(data, status=503)
    return JsonResponse(data)
