import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/menu.dart';
import '../models/ops.dart';
import 'api_client.dart';
import 'format.dart';
import 'json.dart';

/// Bootstrap data (menu, tables, rooms, stations, payment methods) with an
/// offline cache in shared_preferences.
class PosData extends ChangeNotifier {
  PosData(this._prefs, this._api);

  final SharedPreferences _prefs;
  final ApiClient _api;

  bool loading = false;
  bool fromCache = false;
  String? error;
  DateTime? fetchedAt;

  Map<String, dynamic> restaurant = {};
  List<MenuCategory> categories = [];
  List<Area> areas = [];
  List<DiningTable> tables = [];
  List<Room> rooms = [];
  List<Station> stations = [];
  List<PaymentMethod> paymentMethods = [];
  List<String> features = [];
  List<String> permissions = [];

  bool get isLoaded => fetchedAt != null;
  String get restaurantName => asStr(restaurant['name'], 'Restaurant');
  bool get gstEnabled => restaurant['gst_enabled'] == true;
  bool hasFeature(String code) => features.contains(code);

  Iterable<MenuItem> get allItems sync* {
    for (final c in categories) {
      yield* c.items;
    }
  }

  String _cacheKey() => 'bootstrap.${_api.auth.restaurantId ?? 0}';

  Future<void> load({bool silent = false}) async {
    loading = true;
    error = null;
    if (!silent) notifyListeners();
    try {
      final data = asMap(await _api.get('/bootstrap'));
      _apply(data);
      fromCache = false;
      fetchedAt = DateTime.now();
      await _prefs.setString(_cacheKey(), jsonEncode({'at': fetchedAt!.toIso8601String(), 'data': data}));
    } catch (e) {
      final raw = _prefs.getString(_cacheKey());
      if (raw != null) {
        final cached = asMap(jsonDecode(raw));
        _apply(asMap(cached['data']));
        fromCache = true;
        fetchedAt = asDate(cached['at']) ?? DateTime.now();
      }
      error = errorText(e);
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  void _apply(Map<String, dynamic> d) {
    restaurant = asMap(d['restaurant']);
    Fmt.currency = asStr(restaurant['currency'], 'INR');
    categories = (d['menu'] is List ? d['menu'] as List : const []).map((e) => MenuCategory.fromJson(asMap(e))).toList();
    areas = listOf(d['areas']).map((e) => Area(asInt(e['id']), asStr(e['name']))).toList();
    tables = listOf(d['tables']).map((e) => DiningTable.fromJson(asMap(e))).toList();
    rooms = listOf(d['rooms']).map((e) => Room.fromJson(asMap(e))).toList();
    stations = listOf(d['stations']).map((e) => Station(asInt(e['id']), asStr(e['name']))).toList();
    paymentMethods = listOf(d['payment_methods']).map((e) => PaymentMethod(asStr(e['code']), asStr(e['name']))).toList();
    if (paymentMethods.isEmpty) {
      paymentMethods = [PaymentMethod('cash', 'Cash'), PaymentMethod('card', 'Card'), PaymentMethod('upi', 'UPI')];
    }
    features = asStringList(d['features']);
    permissions = asStringList(d['permissions']);
  }

  /// Lightweight refresh of the floor (GET /api/tables).
  Future<void> refreshTables() async {
    try {
      final rows = listOf(await _api.get('/tables'));
      tables = rows.map((e) => DiningTable.fromJson(asMap(e))).toList();
      if (hasFeature('room_service') || rooms.isNotEmpty) {
        final r = listOf(await _api.get('/rooms'));
        rooms = r.map((e) => Room.fromJson(asMap(e))).toList();
      }
      notifyListeners();
    } catch (_) {
      // keep showing cached floor
    }
  }

  MenuItem? findByCode(String code) {
    final c = code.trim();
    if (c.isEmpty) return null;
    for (final i in allItems) {
      if (i.barcode.isNotEmpty && i.barcode == c) return i;
    }
    for (final i in allItems) {
      if (i.shortCode.isNotEmpty && i.shortCode.toLowerCase() == c.toLowerCase()) return i;
    }
    return null;
  }

  void setItemAvailable(int id, bool available) {
    for (final i in allItems) {
      if (i.id == id) i.available = available;
    }
    notifyListeners();
  }

  void clear() {
    fetchedAt = null;
    categories = [];
    tables = [];
    rooms = [];
    areas = [];
    notifyListeners();
  }
}
