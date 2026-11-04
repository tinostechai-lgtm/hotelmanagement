import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'auth_store.dart';
import 'config.dart';
import 'json.dart';

/// Server answered with a non-2xx status.
class ApiException implements Exception {
  ApiException(this.status, this.message, [this.body]);

  final int status;
  final String message;
  final dynamic body;

  @override
  String toString() => message;
}

/// The request never reached the server (offline, DNS, TLS, timeout).
class NetworkException implements Exception {
  NetworkException(this.message);

  final String message;

  @override
  String toString() => 'No connection to server ($message)';
}

/// Human-friendly message for any error thrown by [ApiClient].
String errorText(Object e) {
  if (e is ApiException) return e.message;
  if (e is NetworkException) return 'You are offline or the server is unreachable.';
  return e.toString();
}

/// Thin JSON client for the Servora Django API.
///
/// Every request carries `Authorization: Bearer <access>` and
/// `X-Restaurant: <id>`. A 401 triggers one token refresh + retry.
class ApiClient {
  ApiClient(this.config, this.auth);

  final AppConfig config;
  final AuthStore auth;
  final http.Client _http = http.Client();

  /// False after a request failed for network reasons; true again after the
  /// next successful round-trip. The offline queue listens to this.
  final ValueNotifier<bool> online = ValueNotifier<bool>(true);

  static const Duration _timeout = Duration(seconds: 15);
  Future<bool>? _refreshing;

  Future<dynamic> get(String path, {Map<String, String>? query}) => _send('GET', path, query: query);

  Future<dynamic> post(String path, [Object? body]) => _send('POST', path, body: body ?? const <String, dynamic>{});

  Future<dynamic> patch(String path, Object body) => _send('PATCH', path, body: body);

  /// Unauthenticated POST (login / signup).
  Future<dynamic> postPublic(String path, Object body) => _send('POST', path, body: body, authed: false);

  Uri _uri(String path, Map<String, String>? query) {
    var base = config.baseUrl.trim();
    while (base.endsWith('/')) {
      base = base.substring(0, base.length - 1);
    }
    final p = path.startsWith('/') ? path : '/$path';
    final uri = Uri.parse('$base/api$p');
    if (query == null || query.isEmpty) return uri;
    return uri.replace(queryParameters: {...uri.queryParameters, ...query});
  }

  Future<dynamic> _send(
    String method,
    String path, {
    Object? body,
    Map<String, String>? query,
    bool authed = true,
    bool retry = true,
  }) async {
    final req = http.Request(method, _uri(path, query));
    req.headers['Accept'] = 'application/json';
    req.headers['Content-Type'] = 'application/json; charset=utf-8';
    if (authed) {
      final token = auth.access;
      if (token != null && token.isNotEmpty) req.headers['Authorization'] = 'Bearer $token';
      final rid = auth.restaurantId;
      if (rid != null) req.headers['X-Restaurant'] = '$rid';
    }
    if (body != null && method != 'GET') req.body = jsonEncode(body);

    http.Response res;
    try {
      final streamed = await _http.send(req).timeout(_timeout);
      res = await http.Response.fromStream(streamed).timeout(_timeout);
    } on TimeoutException {
      _setOnline(false);
      throw NetworkException('timed out');
    } on IOException catch (e) {
      _setOnline(false);
      throw NetworkException(e.toString());
    } on http.ClientException catch (e) {
      _setOnline(false);
      throw NetworkException(e.message);
    }
    _setOnline(true);

    if (res.statusCode == 401 && authed && retry && (auth.refresh ?? '').isNotEmpty) {
      if (await _refreshToken()) {
        return _send(method, path, body: body, query: query, authed: authed, retry: false);
      }
      await auth.logout(expired: true);
    }

    final text = utf8.decode(res.bodyBytes, allowMalformed: true);
    dynamic data;
    if (text.isNotEmpty) {
      try {
        data = jsonDecode(text);
      } catch (_) {
        data = text;
      }
    }
    if (res.statusCode >= 200 && res.statusCode < 300) return data;
    throw ApiException(res.statusCode, _messageFrom(data, res.statusCode), data);
  }

  void _setOnline(bool v) {
    if (online.value != v) online.value = v;
  }

  Future<bool> _refreshToken() {
    return _refreshing ??= _doRefresh().whenComplete(() {
      _refreshing = null;
    });
  }

  Future<bool> _doRefresh() async {
    try {
      final data = asMap(await _send('POST', '/auth/refresh', body: {'refresh': auth.refresh}, authed: false, retry: false));
      final access = asStr(data['access']);
      if (access.isEmpty) return false;
      await auth.updateTokens(access, data['refresh']?.toString());
      return true;
    } on ApiException {
      return false;
    }
  }

  static String _messageFrom(dynamic data, int status) {
    if (data is Map) {
      if (data['detail'] != null) return data['detail'].toString();
      final parts = <String>[];
      data.forEach((k, v) {
        final msg = v is List ? v.join(' ') : v.toString();
        parts.add(k == 'non_field_errors' ? msg : '$k: $msg');
      });
      if (parts.isNotEmpty) return parts.join('\n');
    }
    if (data is List && data.isNotEmpty) return data.join('\n');
    switch (status) {
      case 403:
        return 'You do not have permission to do that.';
      case 404:
        return 'Not found.';
      case 500:
      case 502:
      case 503:
        return 'Server error ($status). Please try again.';
    }
    return 'Request failed ($status)';
  }
}
