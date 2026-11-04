import 'package:flutter/material.dart';

/// Servora brand palette.
class Brand {
  Brand._();

  static const Color ink = Color(0xFF14123A);
  static const Color orange = Color(0xFFFF8A3D);
  static const Color orangeDeep = Color(0xFFF0502A);
  static const Color steam = Color(0xFFFFD2B3);
  static const Color success = Color(0xFF10B981);
  static const Color background = Color(0xFFF7F7FB);
  static const Color danger = Color(0xFFE11D48);
  static const Color warning = Color(0xFFF59E0B);
  static const Color info = Color(0xFF3B82F6);
  static const Color muted = Color(0xFF6B6A85);
  static const Color line = Color(0xFFE6E5F0);

  static const LinearGradient gradient = LinearGradient(
    colors: [orange, orangeDeep],
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
  );

  static const LinearGradient inkGradient = LinearGradient(
    colors: [Color(0xFF221F5C), ink],
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
  );
}

ThemeData buildServoraTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: Brand.orangeDeep,
    primary: Brand.orangeDeep,
    onPrimary: Colors.white,
    secondary: Brand.ink,
    onSecondary: Colors.white,
    surface: Colors.white,
    error: Brand.danger,
  );
  const radius = BorderRadius.all(Radius.circular(14));
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: Brand.background,
    appBarTheme: const AppBarTheme(
      backgroundColor: Brand.background,
      foregroundColor: Brand.ink,
      elevation: 0,
      scrolledUnderElevation: 1,
      centerTitle: false,
      titleTextStyle: TextStyle(color: Brand.ink, fontSize: 20, fontWeight: FontWeight.w700),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(64, 52),
        shape: const RoundedRectangleBorder(borderRadius: radius),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(64, 52),
        foregroundColor: Brand.ink,
        shape: const RoundedRectangleBorder(borderRadius: radius),
        side: const BorderSide(color: Brand.line, width: 1.4),
        textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
      ),
    ),
    inputDecorationTheme: const InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      border: OutlineInputBorder(borderRadius: radius, borderSide: BorderSide(color: Brand.line)),
      enabledBorder: OutlineInputBorder(borderRadius: radius, borderSide: BorderSide(color: Brand.line)),
      focusedBorder: OutlineInputBorder(borderRadius: radius, borderSide: BorderSide(color: Brand.orangeDeep, width: 2)),
    ),
    chipTheme: const ChipThemeData(
      shape: StadiumBorder(),
      labelStyle: TextStyle(fontWeight: FontWeight.w600),
    ),
    snackBarTheme: const SnackBarThemeData(behavior: SnackBarBehavior.floating),
  );
}
