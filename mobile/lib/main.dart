import 'dart:ui' show PlatformDispatcher;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'brand/theme.dart';
import 'core/api_client.dart';
import 'core/auth_store.dart';
import 'core/config.dart';
import 'core/offline_queue.dart';
import 'core/pos_data.dart';
import 'core/print_service.dart';
import 'core/rider_service.dart';
import 'screens/login_screen.dart';
import 'screens/splash_screen.dart';

final GlobalKey<NavigatorState> rootNavigator = GlobalKey<NavigatorState>();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // Never let a stray error take the app down: log it and keep running.
  FlutterError.onError = (details) => FlutterError.presentError(details);
  PlatformDispatcher.instance.onError = (error, stack) {
    debugPrint('Uncaught error: $error\n$stack');
    return true;
  };
  ErrorWidget.builder = (details) => const _FriendlyError();
  SystemChrome.setSystemUIOverlayStyle(lightStatusBar);
  final prefs = await SharedPreferences.getInstance();

  final config = AppConfig(prefs);
  final auth = AuthStore(prefs);
  final api = ApiClient(config, auth);
  final data = PosData(prefs, api);
  final queue = OfflineQueue(prefs, api)..start();
  final printer = PrintService(config, api)..refreshState();
  final rider = RiderService(api);

  runApp(MultiProvider(
    providers: [
      ChangeNotifierProvider<AppConfig>.value(value: config),
      ChangeNotifierProvider<AuthStore>.value(value: auth),
      Provider<ApiClient>.value(value: api),
      ChangeNotifierProvider<PosData>.value(value: data),
      ChangeNotifierProvider<OfflineQueue>.value(value: queue),
      ChangeNotifierProvider<PrintService>.value(value: printer),
      ChangeNotifierProvider<RiderService>.value(value: rider),
    ],
    child: const ServoraApp(),
  ));
}

class ServoraApp extends StatefulWidget {
  const ServoraApp({super.key});

  @override
  State<ServoraApp> createState() => _ServoraAppState();
}

class _ServoraAppState extends State<ServoraApp> {
  late final AuthStore _auth;
  bool _wasLoggedIn = false;

  @override
  void initState() {
    super.initState();
    _auth = context.read<AuthStore>();
    _wasLoggedIn = _auth.isLoggedIn;
    _auth.addListener(_onAuth);
  }

  @override
  void dispose() {
    _auth.removeListener(_onAuth);
    super.dispose();
  }

  /// Bounce to login when the session expires anywhere in the app.
  void _onAuth() {
    final now = _auth.isLoggedIn;
    if (_wasLoggedIn && !now) {
      context.read<RiderService>().stop();
      context.read<PosData>().clear();
      rootNavigator.currentState?.pushAndRemoveUntil(
        MaterialPageRoute<void>(builder: (_) => const LoginScreen()),
        (_) => false,
      );
    }
    _wasLoggedIn = now;
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Servora',
      debugShowCheckedModeBanner: false,
      navigatorKey: rootNavigator,
      theme: buildServoraTheme(),
      themeMode: ThemeMode.light, // one carefully tuned light theme, even when the phone is in dark mode
      // Respect the phone's font size, but cap it so very large settings can't break layouts or clip text.
      builder: (context, child) {
        final mq = MediaQuery.of(context);
        return MediaQuery(
          data: mq.copyWith(textScaler: mq.textScaler.clamp(minScaleFactor: 1.0, maxScaleFactor: 1.15)),
          // Tap anywhere outside a field to close the keyboard (iOS number pads have no Done key).
          child: GestureDetector(
            behavior: HitTestBehavior.translucent,
            onTap: () => FocusManager.instance.primaryFocus?.unfocus(),
            child: child!,
          ),
        );
      },
      home: const SplashScreen(),
    );
  }
}


/// Shown in place of a screen that failed to build (instead of a grey screen).
class _FriendlyError extends StatelessWidget {
  const _FriendlyError();

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Brand.background,
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.refresh_rounded, size: 48, color: Brand.orangeDeep),
            const SizedBox(height: 12),
            const Text('Something went wrong on this screen',
                textAlign: TextAlign.center, style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: Brand.ink)),
            const SizedBox(height: 6),
            const Text('Go back and open it again. Your orders are safe.',
                textAlign: TextAlign.center, style: TextStyle(color: Brand.muted)),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: () => rootNavigator.currentState?.maybePop(),
              child: const Text('Go back'),
            ),
          ]),
        ),
      ),
    );
  }
}
