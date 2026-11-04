import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'theme.dart';

/// Paints the Servora mark (see assets/brand/servora-mark.svg) on a 120x120
/// design grid. Each part has its own progress value so it can be animated.
class ServoraMarkPainter extends CustomPainter {
  ServoraMarkPainter({
    this.background = 1,
    this.tray = 1,
    this.dome = 1,
    this.steam = 1,
    this.shine = 1,
  });

  /// 0..1 fade of the navy rounded square.
  final double background;

  /// 0..1 slide-in of the white tray bar.
  final double tray;

  /// Scale of the dome (may overshoot above 1 for a "pop").
  final double dome;

  /// 0..1 portion of the steam "S" that is drawn.
  final double steam;

  /// 0..1 opacity of the highlight on the dome.
  final double shine;

  static Path steamPath() => Path()
    ..moveTo(69, 15)
    ..cubicTo(62, 10, 51, 13, 53, 20)
    ..cubicTo(55, 26, 67, 25, 67, 31)
    ..cubicTo(67, 37, 57, 39, 51, 35);

  @override
  void paint(Canvas canvas, Size size) {
    final s = size.shortestSide / 120.0;
    canvas.save();
    canvas.translate((size.width - 120 * s) / 2, (size.height - 120 * s) / 2);
    canvas.scale(s);

    const box = Rect.fromLTWH(0, 0, 120, 120);
    if (background > 0) {
      canvas.drawRRect(
        RRect.fromRectAndRadius(box, const Radius.circular(30)),
        Paint()..color = Brand.ink.withOpacity(background.clamp(0.0, 1.0)),
      );
    }

    final gradientPaint = Paint()..shader = Brand.gradient.createShader(box);

    // Tray slides in from the left.
    if (tray > 0) {
      final t = tray.clamp(0.0, 1.0);
      final dx = (1 - t) * -70;
      canvas.drawRRect(
        RRect.fromRectAndRadius(Rect.fromLTWH(18 + dx, 86, 84, 8), const Radius.circular(4)),
        Paint()..color = Colors.white.withOpacity(t),
      );
    }

    // Dome + knob scale up from the tray centre.
    if (dome > 0) {
      canvas.save();
      canvas.translate(60, 86);
      canvas.scale(dome);
      canvas.translate(-60, -86);
      final domePath = Path()
        ..moveTo(26, 82)
        ..arcTo(Rect.fromCircle(center: const Offset(60, 82), radius: 34), math.pi, math.pi, false)
        ..close();
      canvas.drawPath(domePath, gradientPaint);
      canvas.drawCircle(const Offset(60, 46), 4.5, gradientPaint);
      if (shine > 0) {
        final shinePath = Path()
          ..moveTo(40, 74)
          ..arcToPoint(const Offset(52, 57), radius: const Radius.circular(22), clockwise: true);
        canvas.drawPath(
          shinePath,
          Paint()
            ..color = Colors.white.withOpacity(0.45 * shine.clamp(0.0, 1.0))
            ..style = PaintingStyle.stroke
            ..strokeWidth = 4
            ..strokeCap = StrokeCap.round,
        );
      }
      canvas.restore();
    }

    // Steam "S" draws itself.
    if (steam > 0) {
      final full = steamPath();
      final partial = Path();
      final t = steam.clamp(0.0, 1.0);
      for (final metric in full.computeMetrics()) {
        partial.addPath(metric.extractPath(0, metric.length * t), Offset.zero);
      }
      canvas.drawPath(
        partial,
        Paint()
          ..color = Brand.steam
          ..style = PaintingStyle.stroke
          ..strokeWidth = 5
          ..strokeCap = StrokeCap.round
          ..strokeJoin = StrokeJoin.round,
      );
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant ServoraMarkPainter oldDelegate) =>
      oldDelegate.background != background ||
      oldDelegate.tray != tray ||
      oldDelegate.dome != dome ||
      oldDelegate.steam != steam ||
      oldDelegate.shine != shine;
}

/// Static logo mark, optionally with the wordmark beside it.
class ServoraLogo extends StatelessWidget {
  const ServoraLogo({super.key, this.size = 36, this.showWordmark = false, this.wordmarkColor = Brand.ink});

  final double size;
  final bool showWordmark;
  final Color wordmarkColor;

  @override
  Widget build(BuildContext context) {
    final mark = SizedBox(width: size, height: size, child: CustomPaint(painter: ServoraMarkPainter()));
    if (!showWordmark) return mark;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        mark,
        SizedBox(width: size * 0.3),
        Text(
          'Servora',
          style: TextStyle(
            fontSize: size * 0.62,
            fontWeight: FontWeight.w800,
            color: wordmarkColor,
            letterSpacing: -0.5,
          ),
        ),
      ],
    );
  }
}

/// Animated intro: tray slides in, dome pops with overshoot, steam "S" draws
/// itself, then the wordmark fades/slides in.
class AnimatedServoraLogo extends StatefulWidget {
  const AnimatedServoraLogo({
    super.key,
    this.size = 140,
    this.showWordmark = true,
    this.wordmarkColor = Brand.ink,
    this.onCompleted,
    this.duration = const Duration(milliseconds: 1800),
  });

  final double size;
  final bool showWordmark;
  final Color wordmarkColor;
  final VoidCallback? onCompleted;
  final Duration duration;

  @override
  State<AnimatedServoraLogo> createState() => _AnimatedServoraLogoState();
}

class _AnimatedServoraLogoState extends State<AnimatedServoraLogo> with SingleTickerProviderStateMixin {
  late final AnimationController _c;
  late final Animation<double> _bg;
  late final Animation<double> _tray;
  late final Animation<double> _dome;
  late final Animation<double> _steam;
  late final Animation<double> _shine;
  late final Animation<double> _word;

  @override
  void initState() {
    super.initState();
    _c = AnimationController(vsync: this, duration: widget.duration);
    _bg = CurvedAnimation(parent: _c, curve: const Interval(0.0, 0.15, curve: Curves.easeOut));
    _tray = CurvedAnimation(parent: _c, curve: const Interval(0.05, 0.35, curve: Curves.easeOutCubic));
    _dome = CurvedAnimation(parent: _c, curve: const Interval(0.25, 0.6, curve: Curves.easeOutBack));
    _shine = CurvedAnimation(parent: _c, curve: const Interval(0.55, 0.7, curve: Curves.easeIn));
    _steam = CurvedAnimation(parent: _c, curve: const Interval(0.55, 0.85, curve: Curves.easeInOut));
    _word = CurvedAnimation(parent: _c, curve: const Interval(0.72, 1.0, curve: Curves.easeOutCubic));
    _c.addStatusListener((status) {
      if (status == AnimationStatus.completed) widget.onCompleted?.call();
    });
    _c.forward();
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _c,
      builder: (context, _) {
        return Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: widget.size,
              height: widget.size,
              child: CustomPaint(
                painter: ServoraMarkPainter(
                  background: _bg.value,
                  tray: _tray.value,
                  dome: _dome.value,
                  steam: _steam.value,
                  shine: _shine.value,
                ),
              ),
            ),
            if (widget.showWordmark) ...[
              SizedBox(height: widget.size * 0.14),
              Opacity(
                opacity: _word.value.clamp(0.0, 1.0),
                child: Transform.translate(
                  offset: Offset(0, (1 - _word.value) * 18),
                  child: Text(
                    'Servora',
                    style: TextStyle(
                      fontSize: widget.size * 0.3,
                      fontWeight: FontWeight.w800,
                      letterSpacing: -0.5,
                      color: widget.wordmarkColor,
                    ),
                  ),
                ),
              ),
            ],
          ],
        );
      },
    );
  }
}
