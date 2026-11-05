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
        ("marketing", "Marketing & SEO", "megaphone", "marketing", "crm"),
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
    return render(request, "marketing/home.html", {"plans": plans, "features": FEATURES, "showcase": showcase,
                                                    "jsonld": _jsonld_software(request, plans)})


def _json_script_safe(data):
    import json

    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _jsonld_software(request, plans):
    from apps.superadmin.models import get_settings

    ps = get_settings()
    base = request.build_absolute_uri("/").rstrip("/")
    return _json_script_safe({
        "@context": "https://schema.org", "@type": "SoftwareApplication", "name": ps.site_name,
        "applicationCategory": "BusinessApplication", "operatingSystem": "Web, Android, iOS",
        "description": ps.seo_description or "Restaurant & hotel POS with QR ordering, home delivery and inventory.",
        "url": base, "image": ps.og_image_url or f"{base}/static/brand/icon-512.png",
        "offers": [{"@type": "Offer", "name": p.name, "price": str(p.price_monthly), "priceCurrency": "INR"} for p in plans if p.price_monthly],
        "publisher": {"@type": "Organization", "name": ps.company_name or ps.site_name, "url": base,
                      **({"email": ps.support_email} if ps.support_email else {}), **({"telephone": ps.support_phone} if ps.support_phone else {})},
    })


def login_view(request, admin=False):
    if request.user.is_authenticated:
        from apps.superadmin.models import platform_permissions

        if admin and platform_permissions(request.user):
            return redirect("superadmin:overview")
        return redirect("web:dashboard")
    if request.method == "POST":
        from django.core.cache import cache

        ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "")).split(",")[0].strip()
        key = f"login-fail:{ip}"
        if cache.get(key, 0) >= 10:
            messages.error(request, "Too many attempts. Please wait a few minutes and try again.")
            return render(request, "auth/login.html", status=429)
        identifier = (request.POST.get("login") or request.POST.get("phone") or "").strip()
        user = authenticate(request, username=identifier, password=request.POST.get("password", ""))
        if user:
            login(request, user, backend="apps.accounts.backends.EmailOrPhoneBackend")
            cache.delete(key)
            nxt = request.GET.get("next", "")
            if nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            from apps.superadmin.models import platform_permissions

            if platform_permissions(user) and (admin or not Membership.objects.filter(user=user, is_active=True).exists()):
                return redirect("superadmin:overview")
            return redirect("web:dashboard")
        cache.set(key, cache.get(key, 0) + 1, 300)
        messages.error(request, "Incorrect mobile number / email or password.")
    return render(request, "auth/login.html", {"admin_login": admin})


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
            login(request, user, backend="apps.accounts.backends.EmailOrPhoneBackend")
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
                from apps.superadmin.models import platform_permissions

                if platform_permissions(request.user):
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


@app_page("marketing", "crm")
def marketing(request):
    from apps.crm.models import Campaign
    from apps.superadmin.models import get_settings

    ps = get_settings()
    return {"segments": Campaign.SEGMENTS, "channels_ready": {"whatsapp": bool(ps.whatsapp_enabled and ps.whatsapp_token),
                                                              "sms": ps.sms_provider != "none", "email": bool(ps.email_enabled and ps.email_host)}}


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

    import re

    root = request.build_absolute_uri("/").rstrip("/")
    natural = lambda t: [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", t.name)]
    return render(request, "app/qr_sheet.html", {
        "tables": [(t, f"{root}/q/{t.qr_token}/") for t in sorted(Table.objects.filter(restaurant=r), key=natural)],
        "rooms": [(rm, f"{root}/q/{rm.qr_token}/") for rm in Room.objects.filter(restaurant=r)],
        "store_url": f"{root}/s/{r.slug}/",
    })


def qr_entry(request, token):
    """Short QR link printed on tables & room cards: /q/<token>/."""
    from apps.operations.models import Room, Table

    t = Table.objects.filter(qr_token=token).select_related("restaurant").first()
    if t:
        return store(request, t.restaurant.slug, qr={"table": token})
    rm = Room.objects.filter(qr_token=token).select_related("restaurant").first()
    if rm:
        return store(request, rm.restaurant.slug, qr={"room": token})
    return render(request, "store/qr_invalid.html", status=404)


def store(request, slug, qr=None):
    r = get_object_or_404(Restaurant, slug=slug, is_active=True)
    base = request.build_absolute_uri("/").rstrip("/")
    data = {"@context": "https://schema.org", "@type": "Restaurant", "name": r.name, "url": f"{base}/s/{r.slug}/",
            "hasMenu": f"{base}/s/{r.slug}/", "acceptsReservations": "False",
            "address": {"@type": "PostalAddress", "streetAddress": r.address, "addressLocality": r.city, "addressRegion": r.state,
                        "postalCode": r.pincode, "addressCountry": "IN"}}
    for k, v in {"telephone": r.phone, "servesCuisine": r.cuisine, "image": r.cover_image_url or r.logo_url, "description": r.seo_description or r.tagline}.items():
        if v:
            data[k] = v
    if r.latitude and r.longitude:
        data["geo"] = {"@type": "GeoCoordinates", "latitude": float(r.latitude), "longitude": float(r.longitude)}
    same = [u for u in [r.instagram_url, r.facebook_url] if u]
    if same:
        data["sameAs"] = same
    return render(request, "store/store.html", {"r": r, "jsonld": _json_script_safe(data), "qr": qr or {}})


def robots_txt(request):
    from django.http import HttpResponse

    from apps.superadmin.models import get_settings

    base = request.build_absolute_uri("/").rstrip("/")
    if not get_settings().allow_indexing:
        body = "User-agent: *\nDisallow: /\n"
    else:
        body = ("User-agent: *\nAllow: /\nDisallow: /app/\nDisallow: /superadmin/\nDisallow: /admin/\nDisallow: /api/\n"
                "Disallow: /t/\nDisallow: /setup/\nDisallow: /password-reset/\nDisallow: /unsubscribe/\n"
                f"\nSitemap: {base}/sitemap.xml\n")
    return HttpResponse(body, content_type="text/plain")


def sitemap_xml(request):
    from django.http import HttpResponse
    from django.utils.html import escape

    base = request.build_absolute_uri("/").rstrip("/")
    urls = [(f"{base}/", "1.0"), (f"{base}/download/", "0.8"), (f"{base}/signup/", "0.8"), (f"{base}/login/", "0.5"), (f"{base}/terms/", "0.2"), (f"{base}/privacy/", "0.2")]
    for slug, updated in Restaurant.objects.filter(is_active=True, online_ordering_enabled=True).values_list("slug", "created_at"):
        urls.append((f"{base}/s/{slug}/", "0.7"))
    body = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "".join(
        f"  <url><loc>{escape(u)}</loc><priority>{p}</priority></url>\n" for u, p in urls) + "</urlset>\n"
    return HttpResponse(body, content_type="application/xml")


def track(request, token):
    return render(request, "store/track.html", {"token": token})


def legal(request, page):
    return render(request, "legal/page.html", {"page": page, "title": "Terms of Service" if page == "terms" else "Privacy Policy"})


def unsubscribe(request, token):
    from django.core import signing

    from apps.crm.models import Customer

    try:
        cid = signing.loads(token, salt="servora-unsub", max_age=60 * 60 * 24 * 365)["c"]
    except signing.BadSignature:
        raise Http404
    c = get_object_or_404(Customer, pk=cid)
    if request.method == "POST":
        c.marketing_opt_in = False
        c.save(update_fields=["marketing_opt_in"])
        return render(request, "store/unsubscribed.html", {"r": c.restaurant, "done": True})
    return render(request, "store/unsubscribed.html", {"r": c.restaurant, "done": False})


def android_app_url():
    from django.conf import settings

    from apps.superadmin.models import get_settings

    return get_settings().android_app_url or settings.ANDROID_APK_URL


def download_android(request):
    """Permanent link that always points at the newest Android app (direct download from this domain)."""
    return redirect(android_app_url())

DOWNLOADABLE = {"servora.apk": "application/vnd.android.package-archive", "android.json": "application/json"}


def download_file(request, name):
    """Serve the APK (and its version file) directly from this domain, streamed in chunks."""
    from django.conf import settings
    from django.http import FileResponse

    if name not in DOWNLOADABLE:
        raise Http404
    path = settings.BASE_DIR / "downloads" / name
    if not path.exists():
        raise Http404
    resp = FileResponse(open(path, "rb"), content_type=DOWNLOADABLE[name], as_attachment=name.endswith(".apk"),
                        filename="Servora.apk" if name.endswith(".apk") else None)
    resp["Cache-Control"] = "public, max-age=300"
    return resp


def ios_app_url():
    from django.conf import settings

    from apps.superadmin.models import get_settings

    return get_settings().ios_app_url or settings.IOS_APP_URL


def _is_iphone(request):
    ua = request.META.get("HTTP_USER_AGENT", "")
    return any(k in ua for k in ("iPhone", "iPad", "iPod"))


def get_app(request):
    """Landing page for the QR / phone buttons: shows install steps and starts the download in the background.
    iPhones go to the App Store / TestFlight link when one is set."""
    if _is_iphone(request) and ios_app_url():
        return redirect(ios_app_url())
    url = android_app_url()
    if "play.google.com" in url:
        return redirect(url)
    return render(request, "marketing/get_app.html", {"apk_url": url, "meta_url": "/downloads/android.json"})


def download_page(request):
    return render(request, "marketing/download.html", {
        "apk_url": request.build_absolute_uri("/get/"),
        "is_play_store": "play.google.com" in android_app_url(),
        "ios_url": ios_app_url(),
        "is_testflight": "testflight.apple.com" in ios_app_url(),
    })
