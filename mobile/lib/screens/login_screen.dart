import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../brand/logo.dart';
import '../brand/theme.dart';
import '../core/api_client.dart';
import '../core/auth_store.dart';
import '../core/config.dart';
import '../widgets/common.dart';
import '../widgets/settings_sheets.dart';
import 'home_screen.dart';
import 'restaurant_picker_screen.dart';
import 'splash_screen.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _phone = TextEditingController();
  final _password = TextEditingController();
  final _form = GlobalKey<FormState>();
  bool _busy = false;
  bool _obscure = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    final auth = context.read<AuthStore>();
    if (auth.phone.isNotEmpty) _phone.text = auth.phone;
    if (auth.sessionExpired) _error = 'Your session expired. Please sign in again.';
  }

  @override
  void dispose() {
    _phone.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _login() async {
    if (!_form.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final api = context.read<ApiClient>();
    final auth = context.read<AuthStore>();
    try {
      final data = await api.postPublic('/auth/login', {
        'phone': _phone.text.trim(),
        'password': _password.text,
      });
      final session = Map<String, dynamic>.from(data as Map);
      final user = session['user'];
      final ms = user is Map ? user['memberships'] : null;
      if (ms is! List || ms.isEmpty) {
        if (mounted) setState(() => _error = 'This account is not linked to any restaurant yet.');
        return;
      }
      await auth.setSession(session);
      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        fadeRoute(auth.hasRestaurant ? const HomeScreen() : const RestaurantPickerScreen()),
      );
    } catch (e) {
      if (mounted) setState(() => _error = errorText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final server = context.watch<AppConfig>().baseUrl;
    return Scaffold(
      body: SafeArea(
        child: Stack(children: [
          Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 420),
                child: Form(
                  key: _form,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const Center(child: AnimatedServoraLogo(size: 96)),
                      const SizedBox(height: 8),
                      const Text(
                        'Sign in to your restaurant',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: Brand.muted, fontSize: 16),
                      ),
                      const SizedBox(height: 28),
                      TextFormField(
                        controller: _phone,
                        keyboardType: TextInputType.emailAddress,
                        textInputAction: TextInputAction.next,
                        autofillHints: const [AutofillHints.username, AutofillHints.email, AutofillHints.telephoneNumber],
                        style: const TextStyle(fontSize: 18),
                        decoration: const InputDecoration(labelText: 'Mobile number or email', prefixIcon: Icon(Icons.person_outline)),
                        validator: (v) => (v ?? '').trim().length < 6 ? 'Enter your mobile number or email' : null,
                      ),
                      const SizedBox(height: 14),
                      TextFormField(
                        controller: _password,
                        obscureText: _obscure,
                        textInputAction: TextInputAction.done,
                        onFieldSubmitted: (_) => _login(),
                        autofillHints: const [AutofillHints.password],
                        style: const TextStyle(fontSize: 18),
                        decoration: InputDecoration(
                          labelText: 'Password',
                          prefixIcon: const Icon(Icons.lock_outline),
                          suffixIcon: IconButton(
                            icon: Icon(_obscure ? Icons.visibility : Icons.visibility_off),
                            onPressed: () => setState(() => _obscure = !_obscure),
                          ),
                        ),
                        validator: (v) => (v ?? '').isEmpty ? 'Enter your password' : null,
                      ),
                      if (_error != null) ...[
                        const SizedBox(height: 14),
                        Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: Brand.danger.withOpacity(0.08),
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: Text(_error!, style: const TextStyle(color: Brand.danger, fontWeight: FontWeight.w600)),
                        ),
                      ],
                      const SizedBox(height: 22),
                      GradientButton(label: 'Sign in', icon: Icons.arrow_forward, busy: _busy, onPressed: _login),
                      const SizedBox(height: 18),
                      Text(
                        server.replaceFirst(RegExp(r'^https?://'), ''),
                        textAlign: TextAlign.center,
                        style: const TextStyle(color: Brand.muted, fontSize: 12),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
          Positioned(
            right: 8,
            top: 8,
            child: IconButton(
              tooltip: 'Server settings',
              icon: const Icon(Icons.settings_outlined),
              onPressed: () => showServerSettings(context),
            ),
          ),
        ]),
      ),
    );
  }
}
