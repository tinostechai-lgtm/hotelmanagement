# Servora mobile (Flutter)

One Android / iOS app for phones and tablets that covers the POS, kitchen display,
delivery desk, rider app, reports and device printing for Servora restaurants and
hotel F&B outlets. It talks to the Django API in `../backend` (`/api/...`).

## First-time setup

Only the Dart sources, `pubspec.yaml` and the Android manifest are committed. Generate
the rest of the platform scaffolding once:

```bash
cd mobile
flutter create . --platforms=android,ios --org com.servora --project-name servora
# flutter create keeps existing files, so lib/ and AndroidManifest.xml are not overwritten.
# If it did replace android/app/src/main/AndroidManifest.xml, restore it with: git checkout android/app/src/main/AndroidManifest.xml
flutter pub get
dart run flutter_launcher_icons   # Servora app icons for Android & iOS
flutter analyze                   # should report no errors before you build
flutter run
```

Requirements: Flutter 3.24 or newer (Dart 3.4+), Android SDK 34, Xcode 15 for iOS.

`mobile_scanner` and `geolocator` need `minSdkVersion 21` or higher. Set it in
`android/app/build.gradle` (`minSdk = 21`) if `flutter create` generated a lower value.

## Build a release APK

```bash
flutter build apk --release            # build/app/outputs/flutter-apk/app-release.apk
flutter build appbundle --release      # for the Play Store
```

Configure signing in `android/key.properties` + `android/app/build.gradle` as described
in the Flutter docs before publishing.

## iOS (iPhone / iPad)

The iOS project is committed in `ios/` and is ready to build: bundle id `com.servora.servora`,
iOS 15.5+, Servora icons and navy launch screen, and every permission prompt already in
`Info.plist` (camera for scanning, location for riders, Bluetooth and local-network printers,
`tel:`/Maps links, `ITSAppUsesNonExemptEncryption = NO`).

**Automatic builds:** `.github/workflows/ios.yml` runs on a macOS runner for every change to `mobile/`:

1. Always builds the app and uploads an *unsigned* `.ipa` artifact (proves the iOS build is healthy).
2. When these repository secrets exist, it also signs the app and uploads it to App Store Connect →
   TestFlight:

| Secret | Where to get it |
| --- | --- |
| `APPLE_TEAM_ID` | developer.apple.com → Membership → Team ID |
| `ASC_KEY_ID`, `ASC_ISSUER_ID` | App Store Connect → Users and Access → Integrations → App Store Connect API (create a key with **Admin** access) |
| `ASC_KEY_P8` | Paste the full contents of the downloaded `AuthKey_XXXX.p8` file |

Before the first upload, create the app once in App Store Connect (My Apps → + → New App,
bundle ID `com.servora.servora`, name "Servora"). Signing certificates and profiles are created
automatically (cloud-managed) by the API key.

Then in TestFlight add testers (or turn on a **public link**) and paste that link — or the App
Store link once the app is live — into **Super admin → General → iPhone app link**. The website's
download page then shows an App Store / TestFlight button and iPhone QR scans go straight to it.

Local build on a Mac: `flutter build ipa` (open `ios/Runner.xcworkspace` in Xcode once to pick
your team). Bluetooth printing on iOS works with BLE printers that `print_bluetooth_thermal` supports.

## Server

The default server is `https://servora.vercel.app`. Tap the gear icon on the login screen
(or Home → menu → Server settings) to use a different server, such as `http://192.168.1.10:8000`
for local development. Cleartext HTTP is allowed in the Android manifest for LAN servers.

Every request sends `Authorization: Bearer <access>` and `X-Restaurant: <restaurant_id>`.
On a 401 response, the app calls `POST /api/auth/refresh` once and retries. If the
refresh also fails, the app returns to the login screen.

## Roles → app modes

After login the user chooses an outlet if they belong to more than one. The home screen
then shows only the modes that the role's permissions allow. These are the `permissions`
of the membership returned by `/api/auth/login`.

| Permission | Mode | What it does |
| --- | --- | --- |
| `pos` | POS & Tables | Floor plan by area, takeaway / delivery / room-service orders, KOT, bill, payments, discounts, split bills |
| `kitchen` | Kitchen Display | Live KOT grid that polls every 5 s, with an age timer, station filter, tap to advance and a sound + vibration on new tickets |
| `delivery` | Delivery Ops | Active delivery tasks, assign or auto-assign riders, mark picked up |
| `rider` | Rider | Online/offline switch, location ping every 20 s, call the customer, Google Maps navigation, pickup, delivery with OTP and COD amount |
| `reports` | Reports | Sales, orders, average order value, payment-mode split, order types, top items and sales by hour |

Default backend roles: Owner and Manager get every mode. Cashier gets POS. Captain gets
POS. Kitchen gets KDS. Delivery Rider gets Rider. Store Keeper gets no mobile modes.

The **Switch user** button (PIN pad) calls `POST /api/auth/pin`. Staff can swap users
on a shared tablet without typing a password.

## Offline billing

- `GET /api/bootstrap` (menu, tables, rooms, stations, payment methods, features) is
  cached per outlet in `shared_preferences`, so the POS opens without a network.
- If creating an order fails because of the network, the order is stored on the device
  with a UUID `client_ref`. This applies to Send KOT, Bill and Pay. When paying offline,
  the payment is stored too, without an amount, so the server charges the exact balance
  it calculates.
- A banner shows "Offline – N pending". The queue retries every 20 s and also as soon as
  any request succeeds again. The backend de-duplicates on `client_ref`, and the queue
  records how far each order got (created / paid), so retries never double-charge.

## Printing from the device

Home → menu → **Printers**:

- **Print from this device** polls `GET /api/print-jobs?status=queued` every 4 s. Each job
  is printed and acknowledged with `POST /api/print-jobs/{id}/ack {ok, error}`.
  - `connection = network`: the raw ESC/POS bytes (`escpos_b64`) go over TCP to the device
    `address` (`ip:port`, default port 9100).
  - `connection = bluetooth`: the bytes go to that MAC address, or to the paired printer
    chosen on this screen.
  - `connection = browser` or no device: the job goes to the chosen Bluetooth printer, or
    else to the default LAN printer.
  - USB, serial and cloud jobs are left for the desktop Servora Hardware Agent.
- Turn this on for **one** device per outlet only. Do not turn it on if the Hardware Agent
  already serves the same network printers, or jobs may print twice.

## Project layout

```
lib/
  main.dart                 providers + MaterialApp
  brand/                    theme colours, CustomPainter logo + animated intro
  core/                     api_client, auth_store, config, offline_queue, pos_data,
                            print_service, rider_service, json/format helpers
  models/                   menu, order, ops (tables/KOT/delivery/print), cart, membership
  screens/                  splash, login, outlet picker, home, tables, order (+controller),
                            payment sheet, KDS, delivery ops, rider, reports, printers
  widgets/                  shared UI, offline banner, item options, scanner, PIN/server sheets
assets/brand/servora-mark.svg
```
