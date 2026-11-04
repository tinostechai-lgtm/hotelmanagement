import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/membership.dart';
import 'json.dart';

/// Holds JWT tokens, the user payload and the selected restaurant.
class AuthStore extends ChangeNotifier {
  AuthStore(this._prefs) {
    access = _prefs.getString(_kAccess);
    refresh = _prefs.getString(_kRefresh);
    restaurantId = _prefs.getInt(_kRestaurant);
    final raw = _prefs.getString(_kUser);
    if (raw != null) {
      try {
        _setUser(asMap(jsonDecode(raw)));
      } catch (_) {
        user = null;
      }
    }
  }

  static const _kAccess = 'auth.access';
  static const _kRefresh = 'auth.refresh';
  static const _kUser = 'auth.user';
  static const _kRestaurant = 'auth.restaurant';

  final SharedPreferences _prefs;

  String? access;
  String? refresh;
  Map<String, dynamic>? user;
  int? restaurantId;
  List<Membership> memberships = const [];

  /// Set when the session ended because the refresh token expired.
  bool sessionExpired = false;

  bool get isLoggedIn => access != null && user != null;
  bool get hasRestaurant => membership != null;

  String get userName => asStr(user?['name'], 'Staff');
  String get phone => asStr(user?['phone']);

  Membership? get membership {
    for (final m in memberships) {
      if (m.restaurantId == restaurantId) return m;
    }
    return null;
  }

  Set<String> get permissions => (membership?.permissions ?? const <String>[]).toSet();
  bool can(String perm) => permissions.contains(perm) || asBool(user?['is_superuser']);
  bool hasFeature(String code) => membership?.features.contains(code) ?? false;

  void _setUser(Map<String, dynamic> u) {
    user = u;
    memberships = (u['memberships'] is List ? u['memberships'] as List : const [])
        .map((e) => Membership.fromJson(asMap(e)))
        .toList();
  }

  /// Stores the result of /auth/login, /auth/signup or /auth/pin.
  Future<void> setSession(Map<String, dynamic> data) async {
    access = asStr(data['access']);
    refresh = asStr(data['refresh']);
    _setUser(asMap(data['user']));
    sessionExpired = false;
    final stillMember = memberships.any((m) => m.restaurantId == restaurantId);
    if (!stillMember) {
      restaurantId = memberships.length == 1 ? memberships.first.restaurantId : null;
    }
    await _persist();
    notifyListeners();
  }

  Future<void> updateTokens(String newAccess, String? newRefresh) async {
    access = newAccess;
    if (newRefresh != null && newRefresh.isNotEmpty) refresh = newRefresh;
    await _prefs.setString(_kAccess, access!);
    if (refresh != null) await _prefs.setString(_kRefresh, refresh!);
  }

  Future<void> selectRestaurant(int id) async {
    restaurantId = id;
    await _prefs.setInt(_kRestaurant, id);
    notifyListeners();
  }

  Future<void> logout({bool expired = false}) async {
    access = null;
    refresh = null;
    user = null;
    memberships = const [];
    sessionExpired = expired;
    await _prefs.remove(_kAccess);
    await _prefs.remove(_kRefresh);
    await _prefs.remove(_kUser);
    notifyListeners();
  }

  Future<void> _persist() async {
    if (access != null) await _prefs.setString(_kAccess, access!);
    if (refresh != null) await _prefs.setString(_kRefresh, refresh!);
    if (user != null) await _prefs.setString(_kUser, jsonEncode(user));
    if (restaurantId != null) {
      await _prefs.setInt(_kRestaurant, restaurantId!);
    } else {
      await _prefs.remove(_kRestaurant);
    }
  }
}
