import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../brand/logo.dart';
import '../brand/theme.dart';
import '../core/auth_store.dart';
import 'home_screen.dart';
import 'login_screen.dart';
import 'restaurant_picker_screen.dart';

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  bool _navigated = false;

  void _next() {
    if (_navigated || !mounted) return;
    _navigated = true;
    final auth = context.read<AuthStore>();
    final Widget target;
    if (!auth.isLoggedIn) {
      target = const LoginScreen();
    } else if (!auth.hasRestaurant) {
      target = const RestaurantPickerScreen();
    } else {
      target = const HomeScreen();
    }
    Navigator.of(context).pushReplacement(fadeRoute(target));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Brand.ink,
      body: Center(
        child: AnimatedServoraLogo(
          size: 150,
          wordmarkColor: Colors.white,
          onCompleted: () => Future<void>.delayed(const Duration(milliseconds: 450), _next),
        ),
      ),
    );
  }
}

Route<T> fadeRoute<T>(Widget page) => PageRouteBuilder<T>(
      transitionDuration: const Duration(milliseconds: 400),
      pageBuilder: (_, __, ___) => page,
      transitionsBuilder: (_, anim, __, child) => FadeTransition(opacity: anim, child: child),
    );
