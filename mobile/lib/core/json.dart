import 'dart:math';

/// Tolerant JSON helpers: DRF sends decimals as strings, ints sometimes as
/// strings, and list endpoints are paginated ({count, results}).

double asDouble(dynamic v, [double fallback = 0]) {
  if (v == null) return fallback;
  if (v is num) return v.toDouble();
  return double.tryParse(v.toString()) ?? fallback;
}

double? asDoubleOrNull(dynamic v) {
  if (v == null) return null;
  if (v is num) return v.toDouble();
  return double.tryParse(v.toString());
}

int asInt(dynamic v, [int fallback = 0]) {
  if (v == null) return fallback;
  if (v is int) return v;
  if (v is num) return v.toInt();
  return int.tryParse(v.toString()) ?? double.tryParse(v.toString())?.toInt() ?? fallback;
}

int? asIntOrNull(dynamic v) {
  if (v == null) return null;
  if (v is int) return v;
  if (v is num) return v.toInt();
  return int.tryParse(v.toString());
}

String asStr(dynamic v, [String fallback = '']) => v == null ? fallback : v.toString();

bool asBool(dynamic v, [bool fallback = false]) {
  if (v == null) return fallback;
  if (v is bool) return v;
  final s = v.toString().toLowerCase();
  return s == 'true' || s == '1';
}

DateTime? asDate(dynamic v) => v == null ? null : DateTime.tryParse(v.toString())?.toLocal();

Map<String, dynamic> asMap(dynamic v) {
  if (v is Map<String, dynamic>) return v;
  if (v is Map) return v.map((k, val) => MapEntry(k.toString(), val));
  return <String, dynamic>{};
}

/// Returns the list from either a plain JSON array or a paginated response.
List<dynamic> listOf(dynamic v) {
  if (v is List) return v;
  if (v is Map && v['results'] is List) return v['results'] as List;
  return const [];
}

List<String> asStringList(dynamic v) => v is List ? v.map((e) => e.toString()).toList() : <String>[];

/// RFC 4122 v4 uuid, used as the offline idempotency key (`client_ref`).
String uuid4() {
  final r = Random.secure();
  final b = List<int>.generate(16, (_) => r.nextInt(256));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  final h = b.map((x) => x.toRadixString(16).padLeft(2, '0')).join();
  return '${h.substring(0, 8)}-${h.substring(8, 12)}-${h.substring(12, 16)}-${h.substring(16, 20)}-${h.substring(20)}';
}
