import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../brand/theme.dart';
import '../core/api_client.dart';
import '../core/auth_store.dart';
import '../core/config.dart';
import 'common.dart';

/// Lets the user point the app at a self-hosted / staging server.
Future<void> showServerSettings(BuildContext context) {
  return showSheet<void>(context, (_) => const _ServerSheet());
}

class _ServerSheet extends StatefulWidget {
  const _ServerSheet();

  @override
  State<_ServerSheet> createState() => _ServerSheetState();
}

class _ServerSheetState extends State<_ServerSheet> {
  late final TextEditingController _url;
  String? _status;
  bool _testing = false;

  @override
  void initState() {
    super.initState();
    _url = TextEditingController(text: context.read<AppConfig>().baseUrl);
  }

  @override
  void dispose() {
    _url.dispose();
    super.dispose();
  }

  Future<void> _save({bool test = false}) async {
    final config = context.read<AppConfig>();
    final api = context.read<ApiClient>();
    await config.setBaseUrl(_url.text);
    _url.text = config.baseUrl;
    if (!test) {
      if (mounted) Navigator.pop(context);
      return;
    }
    setState(() {
      _testing = true;
      _status = null;
    });
    try {
      await api.get('/plans');
      _status = 'Connected to ${config.baseUrl}';
    } on ApiException catch (e) {
      _status = e.status == 401 || e.status == 403 ? 'Server reachable ✓' : 'Server replied: ${e.message}';
    } catch (e) {
      _status = errorText(e);
    } finally {
      if (mounted) setState(() => _testing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SheetFrame(
      title: 'Server',
      child: ListView(
        shrinkWrap: true,
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 20),
        children: [
          const Text('Servora server address. Leave the default unless your restaurant runs its own server.',
              style: TextStyle(color: Brand.muted)),
          const SizedBox(height: 12),
          TextField(
            controller: _url,
            keyboardType: TextInputType.url,
            autocorrect: false,
            decoration: const InputDecoration(labelText: 'Server URL', prefixIcon: Icon(Icons.dns_outlined)),
          ),
          if (_status != null) ...[const SizedBox(height: 8), Text(_status!)],
          const SizedBox(height: 16),
          Row(children: [
            Expanded(
              child: OutlinedButton(
                onPressed: _testing ? null : () => _save(test: true),
                child: _testing ? const CircularProgressIndicator() : const Text('Test'),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(child: FilledButton(onPressed: () => _save(), child: const Text('Save'))),
          ]),
          TextButton(
            onPressed: () => _url.text = AppConfig.defaultBaseUrl,
            child: const Text('Reset to default'),
          ),
        ],
      ),
    );
  }
}

/// Quick staff switch on a shared terminal: POST /api/auth/pin {pin}.
Future<bool> showPinSwitch(BuildContext context) async {
  final r = await showSheet<bool>(context, (_) => const _PinSheet());
  return r ?? false;
}

class _PinSheet extends StatefulWidget {
  const _PinSheet();

  @override
  State<_PinSheet> createState() => _PinSheetState();
}

class _PinSheetState extends State<_PinSheet> {
  String _pin = '';
  bool _busy = false;
  String? _error;

  Future<void> _submit() async {
    if (_pin.length < 4) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final api = context.read<ApiClient>();
    final auth = context.read<AuthStore>();
    try {
      final data = await api.post('/auth/pin', {'pin': _pin});
      await auth.setSession(Map<String, dynamic>.from(data as Map));
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = errorText(e);
          _pin = '';
        });
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _tap(String d) {
    if (_busy) return;
    setState(() {
      if (d == '<') {
        if (_pin.isNotEmpty) _pin = _pin.substring(0, _pin.length - 1);
      } else if (_pin.length < 6) {
        _pin += d;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    const keys = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '<', '0', 'OK'];
    return SheetFrame(
      title: 'Switch user',
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 20),
        child: Column(children: [
          const Text('Enter your staff PIN', style: TextStyle(color: Brand.muted)),
          const SizedBox(height: 16),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: List.generate(
              6,
              (i) => Container(
                margin: const EdgeInsets.symmetric(horizontal: 6),
                width: 16,
                height: 16,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: i < _pin.length ? Brand.orangeDeep : Brand.line,
                ),
              ),
            ),
          ),
          if (_error != null) ...[
            const SizedBox(height: 10),
            Text(_error!, style: const TextStyle(color: Brand.danger, fontWeight: FontWeight.w600)),
          ],
          const SizedBox(height: 16),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 320),
            child: GridView.count(
              crossAxisCount: 3,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              mainAxisSpacing: 10,
              crossAxisSpacing: 10,
              childAspectRatio: 1.5,
              children: [
                for (final k in keys)
                  k == 'OK'
                      ? FilledButton(
                          onPressed: _pin.length >= 4 && !_busy ? _submit : null,
                          child: _busy
                              ? const SizedBox(
                                  width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                              : const Text('OK'),
                        )
                      : OutlinedButton(
                          onPressed: () => _tap(k),
                          child: k == '<'
                              ? const Icon(Icons.backspace_outlined)
                              : Text(k, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700)),
                        ),
              ],
            ),
          ),
        ]),
      ),
    );
  }
}
