import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// Servora brand palette.
class Brand {
  Brand._();

  static const Color ink = Color(0xFF14123A);
  static const Color inkSoft = Color(0xFF221F5C);
  static const Color orange = Color(0xFFFF8A3D);
  static const Color orangeDeep = Color(0xFFF0502A);
  static const Color steam = Color(0xFFFFD2B3);
  static const Color success = Color(0xFF10B981);
  static const Color background = Color(0xFFF4F4FA);
  static const Color danger = Color(0xFFE11D48);
  static const Color warning = Color(0xFFF59E0B);
  static const Color info = Color(0xFF3B82F6);
  static const Color violet = Color(0xFF7C3AED);
  static const Color teal = Color(0xFF0EA5A4);
  static const Color muted = Color(0xFF45445E);
  static const Color line = Color(0xFFE4E3EF);

  static const LinearGradient gradient = LinearGradient(
    colors: [orange, orangeDeep],
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
  );

  static const LinearGradient inkGradient = LinearGradient(
    colors: [Color(0xFF2A2670), ink],
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
  );

  /// Soft elevation used by cards across the app.
  static const List<BoxShadow> shadow = [
    BoxShadow(color: Color(0x1414123A), blurRadius: 24, offset: Offset(0, 10)),
    BoxShadow(color: Color(0x0A14123A), blurRadius: 4, offset: Offset(0, 1)),
  ];

  /// Per-module accent gradients (home tiles, headers).
  static LinearGradient accent(Color a, Color b) =>
      LinearGradient(colors: [a, b], begin: Alignment.topLeft, end: Alignment.bottomRight);
}

/// Light status-bar icons for the navy app bars.
const SystemUiOverlayStyle lightStatusBar = SystemUiOverlayStyle(
  statusBarColor: Colors.transparent,
  statusBarIconBrightness: Brightness.light,
  statusBarBrightness: Brightness.dark,
  systemNavigationBarColor: Colors.white,
  systemNavigationBarIconBrightness: Brightness.dark,
);

ThemeData buildServoraTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: Brand.orangeDeep,
    brightness: Brightness.light,
    primary: Brand.orangeDeep,
    onPrimary: Colors.white,
    secondary: Brand.ink,
    onSecondary: Colors.white,
    surface: Colors.white,
    onSurface: Brand.ink,
    onSurfaceVariant: Brand.muted,
    surfaceTint: Colors.transparent,
    error: Brand.danger,
    outline: Brand.line,
  );
  const radius = BorderRadius.all(Radius.circular(16));
  final base = ThemeData(useMaterial3: true, colorScheme: scheme, brightness: Brightness.light);
  final text = base.textTheme.apply(bodyColor: Brand.ink, displayColor: Brand.ink).copyWith(
        titleLarge: const TextStyle(fontSize: 21, fontWeight: FontWeight.w800, color: Brand.ink, letterSpacing: -0.3),
        titleMedium: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: Brand.ink),
        bodyLarge: const TextStyle(fontSize: 16, color: Brand.ink),
        bodyMedium: const TextStyle(fontSize: 14.5, color: Brand.ink),
        bodySmall: const TextStyle(fontSize: 13.5, color: Brand.muted),
      );
  return base.copyWith(
    scaffoldBackgroundColor: Brand.background,
    textTheme: text,
    splashFactory: InkSparkle.splashFactory,
    pageTransitionsTheme: const PageTransitionsTheme(builders: {
      TargetPlatform.android: ZoomPageTransitionsBuilder(allowEnterRouteSnapshotting: false),
      TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
    }),
    appBarTheme: const AppBarTheme(
      backgroundColor: Brand.ink,
      foregroundColor: Colors.white,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      systemOverlayStyle: lightStatusBar,
      iconTheme: IconThemeData(color: Colors.white),
      actionsIconTheme: IconThemeData(color: Colors.white),
      titleTextStyle: TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w800, letterSpacing: -0.2),
    ),
    tabBarTheme: const TabBarTheme(
      labelColor: Colors.white,
      unselectedLabelColor: Color(0xFFB9B7DA),
      indicatorColor: Brand.orange,
      indicatorSize: TabBarIndicatorSize.label,
      dividerColor: Colors.transparent,
      labelStyle: TextStyle(fontWeight: FontWeight.w800, fontSize: 15),
      unselectedLabelStyle: TextStyle(fontWeight: FontWeight.w600, fontSize: 15),
    ),
    cardTheme: const CardTheme(
      color: Colors.white,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(20)), side: BorderSide(color: Brand.line)),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: Brand.orangeDeep,
        foregroundColor: Colors.white,
        minimumSize: const Size(64, 52),
        shape: const RoundedRectangleBorder(borderRadius: radius),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: Colors.white,
        foregroundColor: Brand.ink,
        minimumSize: const Size(64, 50),
        shape: const RoundedRectangleBorder(borderRadius: radius),
        textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(64, 52),
        foregroundColor: Brand.ink,
        backgroundColor: Colors.white,
        shape: const RoundedRectangleBorder(borderRadius: radius),
        side: const BorderSide(color: Brand.line, width: 1.4),
        textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: Brand.orangeDeep,
        textStyle: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
      ),
    ),
    floatingActionButtonTheme: const FloatingActionButtonThemeData(
      backgroundColor: Brand.orangeDeep,
      foregroundColor: Colors.white,
      elevation: 6,
      shape: StadiumBorder(),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      labelStyle: const TextStyle(color: Brand.muted, fontWeight: FontWeight.w500),
      floatingLabelStyle: const TextStyle(color: Brand.orangeDeep, fontWeight: FontWeight.w700),
      hintStyle: TextStyle(color: Brand.muted.withOpacity(0.8)),
      prefixIconColor: Brand.muted,
      suffixIconColor: Brand.muted,
      border: const OutlineInputBorder(borderRadius: radius, borderSide: BorderSide(color: Brand.line)),
      enabledBorder: const OutlineInputBorder(borderRadius: radius, borderSide: BorderSide(color: Brand.line, width: 1.3)),
      focusedBorder: const OutlineInputBorder(borderRadius: radius, borderSide: BorderSide(color: Brand.orangeDeep, width: 2)),
    ),
    // Explicit chip colours so labels stay readable on light *and* navy backgrounds.
    chipTheme: ChipThemeData(
      shape: const StadiumBorder(side: BorderSide(color: Brand.line)),
      backgroundColor: Colors.white,
      selectedColor: Brand.orangeDeep,
      disabledColor: Brand.line,
      checkmarkColor: Colors.white,
      showCheckmark: false,
      surfaceTintColor: Colors.transparent,
      side: const BorderSide(color: Brand.line),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      labelStyle: WidgetStateTextStyle.resolveWith((s) => TextStyle(
            fontWeight: FontWeight.w700,
            fontSize: 14,
            color: s.contains(WidgetState.selected) ? Colors.white : Brand.ink,
          )),
      iconTheme: const IconThemeData(color: Brand.orangeDeep, size: 18),
    ),
    listTileTheme: const ListTileThemeData(
      iconColor: Brand.ink,
      textColor: Brand.ink,
      titleTextStyle: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: Brand.ink),
      subtitleTextStyle: TextStyle(fontSize: 13.5, color: Brand.muted),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(14))),
    ),
    dividerTheme: const DividerThemeData(color: Brand.line, thickness: 1, space: 1),
    dialogTheme: const DialogTheme(
      backgroundColor: Colors.white,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(24))),
      titleTextStyle: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: Brand.ink),
      contentTextStyle: TextStyle(fontSize: 15, color: Brand.muted, height: 1.4),
    ),
    bottomSheetTheme: const BottomSheetThemeData(
      backgroundColor: Colors.white,
      surfaceTintColor: Colors.transparent,
      modalBackgroundColor: Colors.white,
    ),
    popupMenuTheme: const PopupMenuThemeData(
      color: Colors.white,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(16))),
      textStyle: TextStyle(color: Brand.ink, fontSize: 15, fontWeight: FontWeight.w600),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? Colors.white : Brand.ink),
      trackColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? Brand.success : const Color(0xFFD9D8E8)),
      trackOutlineColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? Brand.success : Brand.ink),
    ),
    progressIndicatorTheme: const ProgressIndicatorThemeData(color: Brand.orangeDeep, linearTrackColor: Color(0x22F0502A)),
    snackBarTheme: const SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: Brand.ink,
      contentTextStyle: TextStyle(color: Colors.white, fontWeight: FontWeight.w600),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(14))),
    ),
  );
}
