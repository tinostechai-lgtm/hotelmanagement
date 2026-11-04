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
from .forms import (SECTIONS, AddClientForm, AddRestaurantUserForm, PlanForm, PlatformRoleForm, SetupForm, SubscriptionAdjustForm,
                    TeamMemberForm, settings_form)
from .models import (PLATFORM_PERMISSIONS, PlatformAuditLog, PlatformRole, PlatformStaff, get_settings,
                     platform_permissions)

# (url name, label, icon, permission needed to see it)
NAV = [("overview", "Overview", "layout-dashboard", "overview"), ("restaurants", "Restaurants & clients", "store", "restaurants_view"),
       ("plans", "Plans & pricing", "badge-indian-rupee", "plans"), ("payments", "Payments", "receipt-indian-rupee", "payments"),
       ("users", "Users", "users", "users"), ("team", "Team & roles", "shield-check", "team"),
       ("activity", "Activity log", "history", "activity"), ("settings", "Platform settings", "settings", "settings")]


def platform_required(perm):
    """Allow super admins and platform staff whose role grants ``perm``."""
    def deco(fn):
        @wraps(fn)
        def wrapper(request, *a, **kw):
            if not request.user.is_authenticated:
                return redirect(f"/superadmin/login/?next={request.path}")
            perms = platform_permissions(request.user)
            if not perms:
                raise Http404
            if perm not in perms:
                first = next((n for n in NAV if n[3] in perms), None)
                if perm == "overview" and first:
                    return redirect("superadmin:settings_home" if first[0] == "settings" else f"superadmin:{first[0]}")
                return render(request, "superadmin/forbidden.html", ctx(request, active=""), status=403)
            request.platform_perms = perms
            return fn(request, *a, **kw)
        return wrapper
    return deco


def ctx(request, **extra):
    perms = getattr(request, "platform_perms", None) or platform_permissions(request.user)
    return {"sa_nav": [n for n in NAV if n[3] in perms], "pperms": perms, "ps": get_settings(), **extra}


def page(request, template, active, **extra):
    return render(request, f"superadmin/{template}.html", ctx(request, active=active, **extra))


def audit(request, action, target="", detail=""):
    PlatformAuditLog.record(request, action, target, detail)


def _gen_password():
    import secrets

    return secrets.token_urlsafe(9)


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


@platform_required("overview")
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
        ("SEO title & description", bool(ps.seo_title and ps.seo_description), "seo"),
        ("Google Search Console verified", bool(ps.google_site_verification), "seo"),
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


@platform_required("restaurants_view")
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


@platform_required("restaurants_view")
def restaurant_detail(request, pk):
    r = get_object_or_404(Restaurant, pk=pk)
    sub = r.subscription
    if request.method == "POST":
        act = request.POST.get("action")
        needed = {"subscription": "restaurants_manage", "extend": "restaurants_manage", "suspend": "restaurants_suspend",
                  "activate": "restaurants_suspend", "email_owner": "restaurants_email", "add_user": "users_manage",
                  "reset_password": "users_manage"}.get(act)
        if not needed or needed not in request.platform_perms:
            messages.error(request, "Your role doesn't allow this action")
            return redirect("superadmin:restaurant", pk=r.pk)
        if act == "add_user":
            uf = AddRestaurantUserForm(r, request.POST)
            if uf.is_valid():
                pwd = _add_restaurant_user(r, uf.cleaned_data)
                audit(request, "restaurant.add_user", r.name, f"{uf.cleaned_data['phone']} as {uf.cleaned_data['role']}")
                messages.success(request, f"User {uf.cleaned_data['phone']} added." + (f" Temporary password: {pwd}" if pwd else " They log in with their existing password."))
            else:
                messages.error(request, "Could not add user: " + " ".join(e for errs in uf.errors.values() for e in errs))
            return redirect("superadmin:restaurant", pk=r.pk)
        if act == "reset_password":
            from apps.accounts.models import Membership

            m = get_object_or_404(Membership, restaurant=r, user_id=request.POST.get("user"))
            if m.user.is_superuser and not request.user.is_superuser:
                messages.error(request, "Only a super admin can reset another super admin's password")
                return redirect("superadmin:restaurant", pk=r.pk)
            pwd = _gen_password()
            m.user.set_password(pwd)
            m.user.save(update_fields=["password"])
            audit(request, "user.reset_password", m.user.username, r.name)
            messages.success(request, f"New password for {m.user.username}: {pwd} — share it securely; it won't be shown again.")
            return redirect("superadmin:restaurant", pk=r.pk)
        audit(request, f"restaurant.{act}", r.name, {k: v for k, v in request.POST.items() if k not in ("csrfmiddlewaretoken", "message")})
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
    return page(request, "restaurant_detail", "restaurants", r=r, sub=sub, adjust=adjust, add_user_form=AddRestaurantUserForm(r),
                staff=r.memberships.select_related("user", "role"),
                payments=r.saas_payments.select_related("plan")[:20],
                stats={"orders": orders.count(), "orders_week": orders.filter(created_at__gte=week).count(),
                       "sales_week": orders.filter(created_at__gte=week, status="completed").aggregate(s=Sum("total"))["s"] or 0,
                       "last_order": orders.order_by("-created_at").values_list("created_at", flat=True).first()})


@platform_required("plans")
def plans(request):
    return page(request, "plans", "plans", plans=Plan.objects.all(),
                counts={p["plan_id"]: p["n"] for p in Subscription.objects.values("plan_id").annotate(n=Count("id"))})


@platform_required("plans")
def plan_edit(request, pk=None):
    plan = get_object_or_404(Plan, pk=pk) if pk else None
    form = PlanForm(request.POST or None, instance=plan)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        audit(request, "plan.save", saved.name, f"₹{saved.price_monthly}/mo, ₹{saved.price_yearly}/yr, {len(saved.features)} features")
        messages.success(request, "Plan saved")
        return redirect("superadmin:plans")
    return page(request, "plan_form", "plans", form=form, plan=plan)


@platform_required("payments")
def payments(request):
    qs = SaasPayment.objects.select_related("restaurant", "plan")
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    return page(request, "payments", "payments", page_obj=Paginator(qs, 50).get_page(request.GET.get("page")), status=request.GET.get("status", ""))


@platform_required("users")
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
        elif act == "toggle_superuser" and not request.user.is_superuser:
            messages.error(request, "Only a super admin can grant or remove super admin access")
        elif "users_manage" not in request.platform_perms:
            messages.error(request, "Your role can view users but not change them")
        elif u.is_superuser and not request.user.is_superuser:
            messages.error(request, "Only a super admin can change another super admin")
        elif act == "reset_password":
            pwd = _gen_password()
            u.set_password(pwd)
            u.save(update_fields=["password"])
            audit(request, "user.reset_password", u.username)
            messages.success(request, f"New password for {u.username}: {pwd} — share it securely; it won't be shown again.")
        elif act == "toggle_active":
            u.is_active = not u.is_active
            u.save(update_fields=["is_active"])
            audit(request, "user.enable" if u.is_active else "user.disable", u.username)
            messages.success(request, f"{u} {'enabled' if u.is_active else 'disabled'}")
        elif act == "toggle_superuser":
            u.is_superuser = u.is_staff = not u.is_superuser
            u.save(update_fields=["is_superuser", "is_staff"])
            audit(request, "user.superuser_on" if u.is_superuser else "user.superuser_off", u.username)
            messages.success(request, f"{u} is {'now' if u.is_superuser else 'no longer'} a super admin")
        return redirect(request.get_full_path())
    return page(request, "users", "users", page_obj=Paginator(qs, 50).get_page(request.GET.get("page")), q=q)


@platform_required("settings")
def settings_view(request, section="general"):
    if section not in SECTIONS:
        raise Http404
    ps = get_settings(fresh=True)
    Form = settings_form(section)
    form = Form(request.POST or None, instance=ps)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            audit(request, "settings.save", SECTIONS[section][0], "changed: " + ", ".join(f for f in form.changed_data if not f.endswith("__clear")))
            messages.success(request, f"{SECTIONS[section][0]} saved")
            return redirect("superadmin:settings", section=section)
        messages.error(request, "Please fix the errors below")
    host = request.build_absolute_uri("/").rstrip("/")
    return page(request, "settings", "settings", form=form, section=section, sections=SECTIONS, title=SECTIONS[section][0],
                webhook_url=f"{host}/api/razorpay/webhook", aggregator_url=f"{host}/api/integrations/<restaurant-slug>/<swiggy|zomato|other>/order")


@platform_required("settings")
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
    back = request.POST.get("back", "")
    return redirect(back if back.startswith("/superadmin/") else "superadmin:settings_home")


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
            PlatformRole.ensure_defaults()
        login(request, user, backend="apps.accounts.backends.EmailOrPhoneBackend")
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


# ---------------------------------------------------------------------------
# Clients & users
# ---------------------------------------------------------------------------

def _add_restaurant_user(restaurant, d):
    """Create (or reuse) a user and attach them to ``restaurant``. Returns the
    generated password for new users, or "" when an existing account was reused."""
    from apps.accounts.models import Membership

    User = get_user_model()
    user = User.objects.filter(username=d["phone"]).first()
    pwd = ""
    if not user:
        pwd = d.get("password") or _gen_password()
        first, _, last = d["name"].partition(" ")
        user = User.objects.create_user(username=d["phone"], password=pwd, email=d.get("email", ""), first_name=first,
                                        last_name=last, phone=d["phone"])
        if d.get("password"):
            pwd = "(the password you entered)"
    Membership.objects.create(user=user, restaurant=restaurant, role=d["role"])
    if d.get("role") and d["role"].name == "Delivery Rider":
        from apps.delivery.models import Rider

        Rider.objects.get_or_create(restaurant=restaurant, user=user, defaults={"name": d["name"], "phone": d["phone"]})
    return pwd


@platform_required("restaurants_create")
def add_client(request):
    form = AddClientForm(request.POST or None, initial={"plan": Plan.objects.filter(code="growth").first(), "days": get_settings().trial_days})
    if request.method == "POST" and form.is_valid():
        from apps.accounts.api import create_account

        d = form.cleaned_data
        pwd = d["password"] or _gen_password()
        with transaction.atomic():
            user, r = create_account({"name": d["owner_name"], "phone": d["owner_phone"], "email": d["owner_email"] if d["send_email"] else "",
                                      "password": pwd, "restaurant_name": d["restaurant_name"], "business_type": d["business_type"],
                                      "city": d["city"]})
            if d["owner_email"] and not d["send_email"]:
                user.email = d["owner_email"]
                user.save(update_fields=["email"])
            r.gstin = d["gstin"]
            r.email = d["owner_email"]
            r.save(update_fields=["gstin", "email"])
            sub = r.subscription
            sub.plan, sub.status = d["plan"], d["status"]
            sub.current_period_start = timezone.now()
            sub.current_period_end = timezone.now() + timedelta(days=d["days"])
            sub.cycle = "yearly" if d["days"] >= 365 else "monthly"
            sub.save()
            audit(request, "client.create", r.name, f"owner {d['owner_phone']}, {d['plan'].name} {d['status']} {d['days']}d")
        if d["send_email"] and d["owner_email"]:
            messaging.send_email(d["owner_email"], f"Your {get_settings().site_name} account is ready", "client_invite",
                                 {"name": d["owner_name"], "restaurant": r, "phone": d["owner_phone"], "password": pwd,
                                  "plan": d["plan"].name, "valid_till": sub.current_period_end})
        messages.success(request, f"Client {r.name} created. Owner login: {d['owner_phone']} / {pwd} — share it securely; it won't be shown again.")
        return redirect("superadmin:restaurant", pk=r.pk)
    return page(request, "add_client", "restaurants", form=form)


# ---------------------------------------------------------------------------
# Platform team & roles
# ---------------------------------------------------------------------------

@platform_required("team")
def team(request):
    PlatformRole.ensure_defaults()
    User = get_user_model()
    mine = request.platform_perms
    form = TeamMemberForm()
    if request.method == "POST":
        act = request.POST.get("action")
        if act == "add":
            form = TeamMemberForm(request.POST)
            if form.is_valid():
                d = form.cleaned_data
                if not set(d["role"].permissions) <= mine:
                    messages.error(request, "You can't assign a role with more access than your own")
                else:
                    user = User.objects.filter(username=d["phone"]).first()
                    pwd = ""
                    if not user:
                        pwd = d["password"] or _gen_password()
                        first, _, last = d["name"].partition(" ")
                        user = User.objects.create_user(username=d["phone"], password=pwd, email=d["email"], first_name=first,
                                                        last_name=last, phone=d["phone"])
                    if user.is_superuser:
                        messages.error(request, f"{user} is already a super admin with full access")
                    else:
                        PlatformStaff.objects.update_or_create(user=user, defaults={"role": d["role"], "is_active": True, "added_by": request.user})
                        audit(request, "team.add", user.username, d["role"].name)
                        messages.success(request, f"{user} added as {d['role']}." + (f" Login: {user.username} / {pwd} — shown once." if pwd and not d["password"] else ""))
                        return redirect("superadmin:team")
        else:
            staff = get_object_or_404(PlatformStaff, pk=request.POST.get("staff"))
            if staff.user == request.user:
                messages.error(request, "You can't change your own access")
            elif not set(staff.role.permissions) <= mine:
                messages.error(request, "This member has more access than you")
            elif act == "role":
                role = get_object_or_404(PlatformRole, pk=request.POST.get("role"))
                if set(role.permissions) <= mine:
                    staff.role = role
                    staff.save(update_fields=["role"])
                    audit(request, "team.role", staff.user.username, role.name)
                    messages.success(request, f"{staff.user} is now {role}")
                else:
                    messages.error(request, "You can't assign a role with more access than your own")
            elif act == "toggle":
                staff.is_active = not staff.is_active
                staff.save(update_fields=["is_active"])
                audit(request, "team.enable" if staff.is_active else "team.disable", staff.user.username)
                messages.success(request, f"{staff.user} {'enabled' if staff.is_active else 'disabled'}")
            elif act == "remove":
                audit(request, "team.remove", staff.user.username, staff.role.name)
                staff.delete()
                messages.success(request, "Removed from the platform team")
            return redirect("superadmin:team")
    return page(request, "team", "team", form=form, staff=PlatformStaff.objects.select_related("user", "role"),
                admins=User.objects.filter(is_superuser=True), roles=PlatformRole.objects.annotate(n=Count("members")),
                catalog=PLATFORM_PERMISSIONS)


@platform_required("team")
def role_edit(request, pk=None):
    role = get_object_or_404(PlatformRole, pk=pk) if pk else None
    mine = request.platform_perms
    if role and not set(role.permissions) <= mine:
        messages.error(request, "This role has more access than yours")
        return redirect("superadmin:team")
    form = PlatformRoleForm(request.POST or None, instance=role, allowed=mine)
    if request.method == "POST":
        if request.POST.get("delete") and role:
            if role.members.exists():
                messages.error(request, "Move members to another role before deleting it")
            else:
                audit(request, "role.delete", role.name)
                role.delete()
                messages.success(request, "Role deleted")
                return redirect("superadmin:team")
        elif form.is_valid():
            saved = form.save()
            audit(request, "role.save", saved.name, ", ".join(saved.permissions))
            messages.success(request, "Role saved")
            return redirect("superadmin:team")
    return page(request, "role_form", "team", form=form, role=role)


@platform_required("activity")
def activity(request):
    qs = PlatformAuditLog.objects.select_related("user")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(action__icontains=q) | Q(target__icontains=q) | Q(user__username__icontains=q) | Q(detail__icontains=q))
    return page(request, "activity", "activity", page_obj=Paginator(qs, 50).get_page(request.GET.get("page")), q=q)
