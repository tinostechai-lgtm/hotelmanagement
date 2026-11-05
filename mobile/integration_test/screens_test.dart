// Drives the real app (live server, Owner demo account) and screenshots the main screens.
// Run: flutter drive --driver=test_driver/integration_test.dart --target=integration_test/screens_test.dart -d <device>
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:servora/main.dart' as app;
import 'package:servora/widgets/common.dart';

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  // The app has looping animations and polling timers, so never pumpAndSettle: pump in steps instead.
  Future<void> pumpFor(WidgetTester t, int ms) async {
    for (var i = 0; i < ms ~/ 100; i++) {
      await t.pump(const Duration(milliseconds: 100));
    }
  }

  Future<void> waitFor(WidgetTester t, Finder f, {int seconds = 30}) async {
    for (var i = 0; i < seconds * 10; i++) {
      await t.pump(const Duration(milliseconds: 100));
      if (f.evaluate().isNotEmpty) return;
    }
    throw TestFailure('Timed out waiting for $f');
  }

  Future<void> shot(String name) async {
    await binding.takeScreenshot(name);
  }

  Future<void> home(WidgetTester t) async {
    app.rootNavigator.currentState!.popUntil((r) => r.isFirst);
    await waitFor(t, find.text('Your workspace'));
    await pumpFor(t, 800);
  }

  Future<void> open(WidgetTester t, String tile, Finder ready, String name) async {
    await home(t);
    await t.tap(find.text(tile));
    await waitFor(t, ready);
    await pumpFor(t, 3000);
    await shot(name);
  }

  testWidgets('tour of the main screens', (t) async {
    app.main();
    await waitFor(t, find.text('Demo accounts'), seconds: 40);
    await pumpFor(t, 1500);
    await shot('01-login');

    await t.tap(find.text('9000000501'));
    await pumpFor(t, 400);
    await t.tap(find.widgetWithText(GradientButton, 'Sign in'));
    await waitFor(t, find.text('Your workspace'), seconds: 40);
    await pumpFor(t, 4000);
    await shot('02-home');

    await open(t, 'POS & Tables', find.text('Takeaway'), '03-tables');
    // Open a table that has a running order (its tile shows "… · N items"), else any table.
    final busy = find.textContaining(' items');
    await t.tap(busy.evaluate().isNotEmpty ? busy.first : find.text('T2').first);
    await waitFor(t, find.text('Search name or short code'));
    await pumpFor(t, 3000);
    await shot('04-order');
    final cart = find.textContaining('View order');
    if (cart.evaluate().isNotEmpty) {
      await t.tap(cart.first);
      await pumpFor(t, 2500);
      await shot('05-cart');
    }

    await open(t, 'Kitchen', find.text('All stations'), '06-kitchen');
    await open(t, 'Delivery', find.text('Riders'), '07-delivery');
    await open(t, 'Rider', find.text('My deliveries'), '08-rider');
    await open(t, 'Reports', find.text('Today'), '09-reports');
  });
}
