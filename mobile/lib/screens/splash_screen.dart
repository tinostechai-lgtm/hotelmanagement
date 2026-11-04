import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../brand/logo.dart';
import '../brand/theme.dart';
import '../core/auth_store.dart';
import 'home_screen.dart';
import 'login_screen.dart';
import 'restaurant_picker_screen.dart';

/// Branded launch intro: glow + rising steam, animated logo, tagline, credit.
class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> with TickerProviderStateMixin {
  late final AnimationController _ambient; // glow pulse + steam particles (loops)
  late final AnimationController _intro; // tagline / credit sequence after the logo
  late final List<_Particle> _particles;
  bool _navigated = false;

  @override
  void initState() {
    super.initState();
    final rnd = math.Random(7);
    _particles = List.generate(
      22,
      (_) => _Particle(
        x: rnd.nextDouble(),
        size: 2 + rnd.nextDouble() * 5,
        speed: 0.35 + rnd.nextDouble() * 0.65,
        phase: rnd.nextDouble(),
        drift: (rnd.nextDouble() - 0.5) * 0.08,
      ),
    );
    _ambient = AnimationController(vsync: this, duration: const Duration(seconds: 4))..repeat();
    _intro = AnimationController(vsync: this, duration: const Duration(milliseconds: 1100));
  }

  @override
  void dispose() {
    _ambient.dispose();
    _intro.dispose();
    super.dispose();
  }

  Future<void> _onLogoDone() async {
    await _intro.forward();
    await Future<void>.delayed(const Duration(milliseconds: 650));
    _next();
  }

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
    final tagline = CurvedAnimation(parent: _intro, curve: const Interval(0.0, 0.55, curve: Curves.easeOutCubic));
    final chips = CurvedAnimation(parent: _intro, curve: const Interval(0.3, 0.85, curve: Curves.easeOutCubic));
    final credit = CurvedAnimation(parent: _intro, curve: const Interval(0.55, 1.0, curve: Curves.easeOut));
    return Scaffold(
      backgroundColor: Brand.ink,
      body: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: _next, // tap to skip
        child: AnimatedBuilder(
          animation: _ambient,
          builder: (context, _) {
            final pulse = 0.5 + 0.5 * math.sin(_ambient.value * 2 * math.pi);
            return Stack(
              fit: StackFit.expand,
              children: [
                // Soft orange glow behind the logo
                Center(
                  child: Container(
                    width: 360 + 60 * pulse,
                    height: 360 + 60 * pulse,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      gradient: RadialGradient(colors: [
                        Brand.orange.withOpacity(0.28 + 0.12 * pulse),
                        Brand.orange.withOpacity(0.0),
                      ]),
                    ),
                  ),
                ),
                // Rising steam particles
                CustomPaint(painter: _SteamPainter(_particles, _ambient.value)),
                SafeArea(
                  child: Column(
                    children: [
                      const Spacer(flex: 3),
                      AnimatedServoraLogo(size: 150, wordmarkColor: Colors.white, onCompleted: _onLogoDone),
                      const SizedBox(height: 22),
                      FadeTransition(
                        opacity: tagline,
                        child: SlideTransition(
                          position: Tween(begin: const Offset(0, 0.4), end: Offset.zero).animate(tagline),
                          child: const Text(
                            'Run your restaurant smarter',
                            textAlign: TextAlign.center,
                            style: TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w700, letterSpacing: -0.2),
                          ),
                        ),
                      ),
                      const SizedBox(height: 12),
                      FadeTransition(
                        opacity: chips,
                        child: SlideTransition(
                          position: Tween(begin: const Offset(0, 0.5), end: Offset.zero).animate(chips),
                          child: Wrap(
                            alignment: WrapAlignment.center,
                            spacing: 8,
                            runSpacing: 8,
                            children: const ['POS', 'QR Ordering', 'Delivery', 'Hotels'].map(_chip).toList(),
                          ),
                        ),
                      ),
                      const Spacer(flex: 4),
                      FadeTransition(
                        opacity: credit,
                        child: const Padding(
                          padding: EdgeInsets.fromLTRB(24, 0, 24, 18),
                          child: Text.rich(
                            TextSpan(children: [
                              TextSpan(text: 'Designed & Developed by\n'),
                              TextSpan(text: 'Tinos Software & Security Solutions LLP', style: TextStyle(color: Brand.steam, fontWeight: FontWeight.w700)),
                            ]),
                            textAlign: TextAlign.center,
                            style: TextStyle(color: Color(0xFFA3A2C2), fontSize: 12, height: 1.5),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }

  static Widget _chip(String label) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: Colors.white.withOpacity(0.08),
          borderRadius: BorderRadius.circular(99),
          border: Border.all(color: Colors.white.withOpacity(0.16)),
        ),
        child: Text(label, style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w600)),
      );
}

class _Particle {
  _Particle({required this.x, required this.size, required this.speed, required this.phase, required this.drift});
  final double x, size, speed, phase, drift;
}

class _SteamPainter extends CustomPainter {
  _SteamPainter(this.particles, this.t);
  final List<_Particle> particles;
  final double t;

  @override
  void paint(Canvas canvas, Size size) {
    for (final p in particles) {
      final progress = (t * p.speed + p.phase) % 1.0;
      final y = size.height * (1.05 - progress * 1.1);
      final x = size.width * (p.x + p.drift * progress) + math.sin((progress + p.phase) * 6) * 8;
      final fade = progress < 0.15 ? progress / 0.15 : (1 - progress);
      final paint = Paint()
        ..color = Brand.steam.withOpacity(0.55 * fade.clamp(0.0, 1.0))
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 1.5);
      canvas.drawCircle(Offset(x, y), p.size * (0.7 + progress * 0.6), paint);
    }
  }

  @override
  bool shouldRepaint(covariant _SteamPainter old) => old.t != t;
}

Route<T> fadeRoute<T>(Widget page) => PageRouteBuilder<T>(
      transitionDuration: const Duration(milliseconds: 450),
      pageBuilder: (_, __, ___) => page,
      transitionsBuilder: (_, anim, __, child) => FadeTransition(opacity: anim, child: child),
    );
