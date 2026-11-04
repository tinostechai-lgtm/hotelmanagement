<p align="center"><img src="brand/servora-animated.svg" width="360" alt="Servora"></p>

# Servora — Restaurant & Hotel F&B SaaS

Servora is a multi-tenant SaaS for restaurants, cafés, cloud kitchens, bars and hotel F&B. It covers POS billing, KOTs, table and room service, QR and online ordering, your own home-delivery fleet, inventory, loyalty and AI insights. Subscription packages are paid through Razorpay.

| Part | Tech | Folder |
|---|---|---|
| Backend + REST API | Python 3.12, Django 5, Django REST Framework, JWT | `backend/` |
| Web app, marketing site, online store | Django templates, HTML/CSS, vanilla JS (no build step) | `backend/templates`, `backend/static` |
| Mobile / tablet app | Flutter (Dart) — POS, captain, KDS, delivery ops, rider | `mobile/` |
| Hardware agent | Python (stdlib only) for Windows / Linux / Raspberry Pi | `hardware-agent/` |
| Brand | Logo SVG + animated logo (web CSS + Flutter `CustomPainter`) | `brand/` |
| Deployment | Vercel (Django service) + Postgres | `vercel.json` |

## Name & logo

**Servora** combines *serve* and *aura*: the feel of great hospitality. Alternatives worth a trademark/domain check: **Tablio**, **DineFlow**, **Orderly**, **KOTly**, **Hospitably**.

The logo is a serving **cloche** on a tray. Its rising steam forms an **"S"**.
- Static: `brand/servora-mark.svg`
- Animated (web): `brand/servora-animated.svg`, and the inline version in `backend/templates/partials/logo_svg.html`. The tray slides in, the dome pops up, the steam draws itself into the "S", then the wordmark appears. A looping "lift the lid" variant runs as the page loader.
- Animated (app): `mobile/lib/brand/logo.dart` (`AnimatedServoraLogo`, used on the splash and login screens).
- Colours: ink `#14123A`, saffron gradient `#FF8A3D → #F0502A`, steam `#FFD2B3`.

## Features

All 14 modules of the reference product, plus advanced features:

- **Fast billing & POS:** short codes, barcode scan, keyboard shortcuts (`/`, F2 KOT, F3 bill, F4 pay), variants and add-ons, weighed items, item notes.
- **Table & order management:** live floor plan by area, timers and running totals, move or merge tables, reservations, guest count.
- **Room service:** room QR ordering, posting to the room folio, check-in and check-out with an F&B folio, PMS reference.
- **Multiple payment methods:** cash with a change calculator, card, UPI, Razorpay, wallet, loyalty points, credit, room post. Several payment methods can be combined on one bill.
- **Split billing:** equal, by seat, or by item. Each split is its own GST invoice.
- **KOT:** automatic routing per kitchen station to KOT printers and the kitchen display, reprint, delay colours, sound on new tickets.
- **Online ordering:** commission-free store at `/s/<slug>/` with Razorpay checkout, coupons, live tracking at `/t/<token>/` and feedback.
- **QR code ordering:** per-table and per-room QR codes (printable sheet), call-waiter button, pay now or later.
- **Home delivery:** distance or pincode zones with fee, minimum order and ETA; cash on delivery; auto-assign to the nearest free rider; live map; delivery OTP; rider app; cash settlement and rider payouts.
- **Aggregator sync:** signed webhook `/api/integrations/<slug>/<swiggy|zomato|other>/order`. Connect it through UrbanPiper or any middleware.
- **Smart insights:** 7-day sales forecast plus tips on peak hours, best sellers, slow movers, channel mix and low stock.
- **Inventory:** ingredients, recipes with automatic deduction, purchase orders, suppliers, wastage, stock ledger, low-stock alerts.
- **Customer ordering app and storefront:** mobile-first web store that installs as an app (PWA).
- **CRM & loyalty:** customer profiles, tiers, points, coupons, birthdays, CSV export, feedback.
- **Staff & roles:** default roles plus custom roles with granular permissions, PIN switching, cash shifts with expected vs counted cash.
- **GST:** HSN/SAC codes, CGST/SGST split, GSTIN and FSSAI on bills, service charge, round-off, tax-inclusive pricing.
- **Offline billing (app):** orders queue on the device and sync later; `client_ref` keeps them duplicate-safe.
- **Notifications:** new orders, payments, table calls, low stock.

### SaaS packages (seeded by `python manage.py seed`)

| | Starter | Growth (popular) | Pro | Enterprise |
|---|---|---|---|---|
| Price | ₹999/mo · ₹9,990/yr | ₹2,499/mo · ₹24,990/yr | ₹4,999/mo · ₹49,990/yr | Custom |
| Staff / devices | 3 / 2 | 10 / unlimited | unlimited | unlimited |
| Highlights | POS, KOT, tables, offline, QR menu | + QR ordering, split bill, KDS, online store, delivery, CRM, inventory | + room service, aggregators, rider app, AI insights, multi-outlet, API | everything, custom SLAs |

- Every signup gets a 14-day Pro trial.
- Features are enforced in the API (`TenantViewSet.feature`) and the UI shows lock badges.
- 18% GST is added at checkout.

## Hardware: every common type, three easy ways

1. **Browser (no install):** in Chrome or Edge, USB (WebUSB), serial (WebSerial) or Bluetooth printers, cash drawers and weighing scales connect directly. Settings → Hardware → *This browser*.
2. **Servora Agent:** `hardware-agent/` connects LAN, USB, serial and Bluetooth printers, Windows and CUPS printers, cash drawers, pole displays and RS232 weighing scales from a counter PC or Raspberry Pi. Install it with `install_windows.bat` or `install_linux.sh` and paste the device key.
3. **Flutter app:** prints to LAN (port 9100) and Bluetooth thermal printers directly; the camera scans barcodes.

Barcode scanners work as a keyboard everywhere. Card and UPI terminals (Razorpay POS, Pine Labs, Paytm) connect through their vendor cloud SDKs. KOT routing per station, 58/80 mm paper, copies and automatic drawer kick are set per device.

## Run locally

```bash
python -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

```bash
cd backend
```

```bash
python manage.py migrate
```

```bash
python manage.py seed --demo
```

```bash
python manage.py runserver
```

Open http://127.0.0.1:8000.

- Demo owner login: **9999999999 / Demo@1234**
- Captain `8888888801`, cashier `…02`, kitchen `…03`, rider `…04` (same password)
- Demo store: `/s/spice-garden/`

Run the tests:

```bash
cd backend && python manage.py test tests
```

```bash
python -m unittest discover -s hardware-agent/tests
```

## Deploy to Vercel

1. Import this GitHub repo in Vercel. `vercel.json` defines a single Django service rooted at `backend/` (entrypoint `servora.wsgi.application`, dependencies from `backend/requirements.txt`) and routes every path — pages, `/static/` and `/api/` — to it. Keep the root directory as the repo root.
2. Add a Postgres database (Vercel Postgres, Neon or Supabase) and set the environment variables from `.env.example`. You need at least `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=false`, `DATABASE_URL`, `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` and `RAZORPAY_WEBHOOK_SECRET`.
3. Create the tables once from your machine, or let the GitHub Action do it (set the `DATABASE_URL` and `DJANGO_SECRET_KEY` repo secrets):
   ```bash
   cd backend && DATABASE_URL=postgres://... python manage.py migrate && python manage.py seed
   ```
4. In Razorpay Dashboard → Webhooks, add `https://<your-domain>/api/razorpay/webhook` with the events `payment.captured` and `order.paid`.
5. Point the mobile app and the hardware agent at your domain.

Without `DATABASE_URL`, the deployment boots a throw-away SQLite demo in `/tmp` so you can preview it immediately. Data in that demo is not kept. Without Razorpay keys, checkout runs in a clearly labelled demo mode.

Vercel functions can't hold websockets, so the dashboard, KDS and rider tracking poll lightweight endpoints every 5–10 s (`/api/orders/live`, `/api/kots`, `/api/delivery/live-map`).

## Go-live checklist

1. **Vercel env vars:** `DJANGO_SECRET_KEY` (long and random; the app refuses to start against a real database without it), `DJANGO_DEBUG=false`, `DATABASE_URL`, and `DJANGO_ALLOWED_HOSTS` / `DJANGO_CSRF_TRUSTED_ORIGINS` including your custom domain.
2. **Database:** run `python manage.py migrate && python manage.py seed` once against the production `DATABASE_URL`. Use `seed` without `--demo` so the demo restaurant isn't created.
3. **Platform admin:** `python manage.py createsuperuser`, then sign in at `/admin/` to manage tenants, plans and subscriptions.
4. **Razorpay:**
   - Switch to live keys.
   - Add the webhook `https://<domain>/api/razorpay/webhook` for `payment.captured` and `order.paid`, and set `RAZORPAY_WEBHOOK_SECRET`.
   - Edit plan prices in `/admin/` if needed.
5. **Legal:** have a lawyer review `/terms/` and `/privacy/` (`backend/templates/legal/page.html`). They are starting templates.
6. **Mobile:**
   - `flutter create .`, then `dart run flutter_launcher_icons`, then `flutter analyze`.
   - Set your domain as the default server in `lib/core/config.dart`, then build and sign the release APK / IPA.
7. **Hardware agent:** set `DEFAULT_SERVER` in `hardware-agent/servora_agent.py` to your domain before you hand it out.

Security already in place:
- HTTPS redirect and HSTS when `DEBUG` is off; secure cookies
- login, signup and PIN brute-force throttling (10/min) plus general API rate limits
- tenant isolation checks on every foreign key and many-to-many field
- Razorpay HMAC signature verification; HMAC-signed aggregator webhooks
- open-redirect protection on login
- unpaid online orders auto-cancel after 20 minutes (`UNPAID_ONLINE_ORDER_TTL_MINUTES`)

## Mobile app

See `mobile/README.md`:

```bash
cd mobile
```

```bash
flutter create . --platforms=android,ios
```

```bash
flutter pub get
```

```bash
flutter run
```

To build an APK: `flutter build apk --release`.

## API overview

All endpoints are under `/api/`. Authenticate with `POST /api/auth/login {phone, password}`, then send `Authorization: Bearer <token>` and optionally `X-Restaurant: <id>`.

- **Auth:** `auth/login`, `auth/signup`, `auth/refresh`, `auth/pin`, `me`
- **Setup:** `restaurant`, `bootstrap` (menu, tables and more in one call for offline caching)
- **Menu:** `categories`, `items` (+ `/toggle`), `addon-groups`, `hsn`, `stations`
- **Floor:** `areas`, `tables`, `rooms` (+ `checkin` / `checkout`), `reservations`
- **Orders:** `orders` (+ `items`, `kot`, `status`, `discount`, `bill`, `split`, `pay`, `move`, `print`, `live`), `kots`, `shifts`, `notifications`
- **Customers:** `customers`, `coupons`, `feedback`
- **Delivery:** `delivery/zones|riders|tasks|settlements`, `delivery/live-map`, `rider`
- **Inventory:** `inventory/ingredients|recipes|purchase-orders|suppliers|movements`
- **Hardware:** `devices`, `print-jobs`, `hardware/agent`
- **Reports:** `reports/summary`, `reports/insights`
- **Subscription:** `plans`, `subscription`, `subscription/checkout`, `subscription/verify`, `razorpay/webhook`
- **Public (no login):** `public/<slug>/store|quote|order|verify-payment|call-waiter`, `public/track/<token>`
