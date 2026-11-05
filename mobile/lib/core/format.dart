import 'package:intl/intl.dart';

class Fmt {
  Fmt._();

  static String currency = 'INR';
  static NumberFormat? _cache;
  static String? _cacheFor;

  static NumberFormat get _money {
    if (_cache == null || _cacheFor != currency) {
      _cacheFor = currency;
      _cache = currency == 'INR'
          ? NumberFormat.currency(locale: 'en_IN', symbol: '₹', decimalDigits: 2)
          : NumberFormat.simpleCurrency(name: currency);
    }
    return _cache!;
  }

  static String money(num v) {
    final s = _money.format(v);
    return s.endsWith('.00') ? s.substring(0, s.length - 3) : s;
  }

  static String qty(num v) => v == v.roundToDouble() ? v.toInt().toString() : v.toStringAsFixed(2);

  /// "5m", "1h 12m".
  static String elapsed(DateTime? since, [DateTime? now]) {
    if (since == null) return '';
    final d = (now ?? DateTime.now()).difference(since);
    if (d.isNegative || d.inMinutes < 1) return '${d.inSeconds.clamp(0, 59)}s';
    if (d.inHours < 1) return '${d.inMinutes}m';
    return '${d.inHours}h ${d.inMinutes % 60}m';
  }

  /// "04:37" style clock for KDS cards.
  static String clock(DateTime since, [DateTime? now]) {
    final d = (now ?? DateTime.now()).difference(since);
    if (d.inHours >= 1) return '${d.inHours}h ${(d.inMinutes % 60).toString().padLeft(2, '0')}m';
    final m = d.inMinutes.clamp(0, 59);
    final s = (d.inSeconds % 60).clamp(0, 59);
    return '${m.toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}';
  }

  static String time(DateTime? t) => t == null ? '' : DateFormat('h:mm a').format(t);
  static String isoDate(DateTime d) => DateFormat('yyyy-MM-dd').format(d);

  static String titleCase(String s) =>
      s.split('_').where((w) => w.isNotEmpty).map((w) => w[0].toUpperCase() + w.substring(1)).join(' ');
}
