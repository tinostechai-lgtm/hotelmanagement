from functools import wraps

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import Membership
from apps.subscriptions.models import FEATURES, Plan
from apps.tenants.models import Restaurant

NAV = [
    ("Operate", [
        ("dashboard", "Dashboard", "layout-dashboard", None, None),
        ("pos", "POS & Tables", "monitor-smartphone", "pos", None),
        ("orders", "Orders", "receipt-text", "pos", None),
        ("kitchen", "Kitchen Display", "chef-hat", "kitchen", None),
        ("delivery", "Home Delivery", "bike", "delivery", "delivery"),
    ]),
    ("Manage", [
        ("menu", "Menu", "utensils-crossed", "menu", None),
        ("floor", "Tables & Rooms", "layout-grid", "tables", None),
        ("customers", "Customers & Loyalty", "users", "customers", None),
        ("inventory", "Inventory", "package", "inventory", "inventory"),
        ("reports", "Reports & Insights", "chart-column", "reports", None),
    ]),
    ("Setup", [
        ("staff", "Staff & Roles", "shield-check", "staff", None),
        ("hardware", "Hardware", "printer", "settings", None),
        ("settings", "Settings", "settings", "settings", None),
        ("billing", "Plan & Billing", "credit-card", "billing", None),
    ]),
]


def home(request):
    from django.contrib.auth import get_user_model

    if not get_user_model().objects.filter(is_superuser=True).exists():
        return redirect("setup")
    plans = Plan.objects.filter(is_public=True)
    showcase = (Restaurant.objects.filter(slug="spice-garden", is_active=True).first()
                or Restaurant.objects.filter(is_active=True, online_ordering_enabled=True).order_by("created_at").first())
    return render(request, "marketing/home.html", {"plans": plans, "features": FEATURES, "showcase": showcase})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("web:dashboard")
    if request.method == "POST":
        from django.core.cache import cache

        ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "")).split(",")[0].strip()
        key = f"login-fail:{ip}"
        if cache.get(key, 0) >= 10:
            messages.error(request, "Too many attempts. Please wait a few minutes and try again.")
            return render(request, "auth/login.html", status=429)
        user = authenticate(request, username=request.POST.get("phone", "").strip(), password=request.POST.get("password", ""))
        if user:
            login(request, user)
            cache.delete(key)
            nxt = request.GET.get("next", "")
            if nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            if user.is_superuser and not Membership.objects.filter(user=user, is_active=True).exists():
                return redirect("superadmin:overview")
            return redirect("web:dashboard")
        cache.set(key, cache.get(key, 0) + 1, 300)
        messages.error(request, "Incorrect mobile number or password.")
    return render(request, "auth/login.html")


def signup_view(request):
    from apps.accounts.api import SignupSerializer, create_account

    from apps.superadmin.models import get_settings

    plans = Plan.objects.filter(is_public=True).exclude(code="enterprise")
    if not get_settings().signup_enabled:
        return render(request, "auth/signup_closed.html")
    if request.method == "POST":
        s = SignupSerializer(data=request.POST)
        if s.is_valid():
            user, _ = create_account(s.validated_data)
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(request, "Welcome to Servora! Your 14-day free trial of Pro has started.")
            return redirect("web:dashboard")
        return render(request, "auth/signup.html", {"errors": s.errors, "data": request.POST, "plans": plans})
    return render(request, "auth/signup.html", {"plans": plans, "data": {"plan": request.GET.get("plan", "growth")}})


def logout_view(request):
    logout(request)
    return redirect("web:home")


@login_required
@require_POST
def switch_restaurant(request):
    m = get_object_or_404(Membership, user=request.user, restaurant_id=request.POST.get("restaurant"), is_active=True)
    request.session["restaurant_id"] = m.restaurant_id
    return redirect("web:dashboard")


def app_page(perm=None, feature=None):
    def deco(fn):
        @login_required
        @wraps(fn)
        def wrapper(request, *a, **kw):
            r = request.restaurant
            if not r:
                if request.user.is_superuser:
                    return redirect("superadmin:overview")
                suspended = Membership.objects.filter(user=request.user, restaurant__is_active=False).select_related("restaurant").first()
                return render(request, "app/no_restaurant.html", {"suspended": suspended})
            m = request.membership
            nav = []
            for section, items in NAV:
                visible = [dict(key=k, label=lbl, icon=ic, locked=bool(ft and not r.has_feature(ft)))
                           for k, lbl, ic, p, ft in items if not p or m.can(p)]
                if visible:
                    nav.append((section, visible))
            ctx = {"nav": nav, "page": fn.__name__.replace("_page", ""), "memberships": Membership.objects.filter(user=request.user, is_active=True).select_related("restaurant"),
                   "perms": m.role.permissions}
            if perm and not m.can(perm):
                return render(request, "app/forbidden.html", ctx, status=403)
            if feature and not r.has_feature(feature):
                ctx["feature_label"] = FEATURES.get(feature, feature)
                return render(request, "app/upgrade.html", ctx, status=402)
            extra = fn(request, *a, **kw) or {}
            ctx.update(extra)
            return render(request, f"app/{fn.__name__}.html", ctx)
        return wrapper
    return deco


@app_page()
def dashboard(request):
    pass


@app_page("pos")
def pos(request):
    pass


@app_page("pos")
def orders(request):
    pass


@app_page("kitchen")
def kitchen(request):
    pass


@app_page("delivery", "delivery")
def delivery(request):
    pass


@app_page("menu")
def menu(request):
    pass


@app_page("tables")
def floor(request):
    pass


@app_page("customers")
def customers(request):
    pass


@app_page("inventory", "inventory")
def inventory(request):
    pass


@app_page("reports")
def reports(request):
    pass


@app_page("staff")
def staff(request):
    from apps.accounts.models import PERMISSIONS

    return {"permission_catalog": PERMISSIONS}


@app_page("settings")
def hardware(request):
    pass


@app_page("settings")
def settings_page(request):
    pass


@app_page("billing")
def billing(request):
    return {"plans": Plan.objects.filter(is_public=True), "features": FEATURES}


@login_required
def qr_sheet(request):
    """Printable QR codes for every table and room."""
    r = request.restaurant
    if not r:
        raise Http404
    from apps.operations.models import Room, Table

    base = request.build_absolute_uri(f"/s/{r.slug}/")
    return render(request, "app/qr_sheet.html", {
        "tables": [(t, f"{base}?table={t.qr_token}") for t in Table.objects.filter(restaurant=r)],
        "rooms": [(rm, f"{base}?room={rm.qr_token}") for rm in Room.objects.filter(restaurant=r)],
        "store_url": base,
    })


def store(request, slug):
    r = get_object_or_404(Restaurant, slug=slug, is_active=True)
    return render(request, "store/store.html", {"r": r})


def track(request, token):
    return render(request, "store/track.html", {"token": token})


def legal(request, page):
    return render(request, "legal/page.html", {"page": page, "title": "Terms of Service" if page == "terms" else "Privacy Policy"})
