import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
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

  void _fillDemo(String phone) {
    setState(() {
      _phone.text = phone;
      _password.text = AppConfig.demoPassword;
      _error = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    final h = MediaQuery.sizeOf(context).height;
    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: lightStatusBar,
      child: Scaffold(
        backgroundColor: Brand.ink,
        body: Stack(children: [
          // Ambient glow behind the logo
          Positioned(
            top: -h * 0.12,
            left: -80,
            right: -80,
            child: Container(
              height: h * 0.55,
              decoration: BoxDecoration(
                gradient: RadialGradient(colors: [Brand.orange.withOpacity(0.32), Brand.orange.withOpacity(0)]),
              ),
            ),
          ),
          SafeArea(
            bottom: false,
            child: SingleChildScrollView(
              child: ConstrainedBox(
                constraints: BoxConstraints(minHeight: h - MediaQuery.paddingOf(context).top),
                child: Column(children: [
                  const SizedBox(height: 28),
                  GestureDetector(
                    // Hidden: long-press the logo for server settings (support use only).
                    onLongPress: () => showServerSettings(context),
                    child: const AnimatedServoraLogo(size: 92, wordmarkColor: Colors.white),
                  ),
                  const SizedBox(height: 6),
                  const Text('Welcome back',
                      style: TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w800, letterSpacing: -0.3)),
                  const SizedBox(height: 4),
                  const Text('Sign in to run your restaurant', style: TextStyle(color: Color(0xFFCFCDEB), fontSize: 15)),
                  const SizedBox(height: 26),
                  Container(
                    width: double.infinity,
                    constraints: BoxConstraints(minHeight: h * 0.6),
                    decoration: const BoxDecoration(
                      color: Brand.background,
                      borderRadius: BorderRadius.vertical(top: Radius.circular(32)),
                    ),
                    padding: EdgeInsets.fromLTRB(22, 28, 22, 24 + MediaQuery.paddingOf(context).bottom),
                    child: Center(
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 440),
                        child: _form0(),
                      ),
                    ),
                  ),
                ]),
              ),
            ),
          ),
        ]),
      ),
    );
  }

  Widget _form0() {
    return Form(
      key: _form,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text('Sign in', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w900, color: Brand.ink, letterSpacing: -0.5)),
          const SizedBox(height: 4),
          const Text('Use your mobile number or email', style: TextStyle(color: Brand.muted, fontSize: 15)),
          const SizedBox(height: 22),
          TextFormField(
            controller: _phone,
            keyboardType: TextInputType.emailAddress,
            textInputAction: TextInputAction.next,
            autofillHints: const [AutofillHints.username, AutofillHints.email, AutofillHints.telephoneNumber],
            style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600, color: Brand.ink),
            decoration: const InputDecoration(labelText: 'Mobile number or email', prefixIcon: Icon(Icons.person_outline_rounded)),
            validator: (v) => (v ?? '').trim().length < 6 ? 'Enter your mobile number or email' : null,
          ),
          const SizedBox(height: 14),
          TextFormField(
            controller: _password,
            obscureText: _obscure,
            textInputAction: TextInputAction.done,
            onFieldSubmitted: (_) => _login(),
            autofillHints: const [AutofillHints.password],
            style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600, color: Brand.ink),
            decoration: InputDecoration(
              labelText: 'Password',
              prefixIcon: const Icon(Icons.lock_outline_rounded),
              suffixIcon: IconButton(
                icon: Icon(_obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined),
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
                color: const Color(0xFFFFE4EA),
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: Brand.danger.withOpacity(0.3)),
              ),
              child: Row(children: [
                const Icon(Icons.error_outline, color: Brand.danger),
                const SizedBox(width: 10),
                Expanded(child: Text(_error!, style: const TextStyle(color: Color(0xFF9F1239), fontWeight: FontWeight.w700))),
              ]),
            ),
          ],
          const SizedBox(height: 22),
          GradientButton(label: 'Sign in', icon: Icons.arrow_forward_rounded, busy: _busy, onPressed: _login),
          if (AppConfig.showDemoLogins) ...[const SizedBox(height: 26), _demoCard()],
          const SizedBox(height: 24),
          const Text.rich(
            TextSpan(children: [
              TextSpan(text: 'Designed & Developed by '),
              TextSpan(text: 'Tinos Software & Security Solutions LLP', style: TextStyle(fontWeight: FontWeight.w700, color: Brand.ink)),
            ]),
            textAlign: TextAlign.center,
            style: TextStyle(color: Brand.muted, fontSize: 12),
          ),
        ],
      ),
    );
  }

  /// Demo credentials as plain text (tap a row to fill the form).
  Widget _demoCard() {
    return Container(
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(20), boxShadow: Brand.shadow),
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          const IconBubble(Icons.key_rounded, size: 34),
          const SizedBox(width: 10),
          const Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Demo accounts', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: Brand.ink)),
              Text('Tap a row to fill the form', style: TextStyle(fontSize: 12.5, color: Brand.muted)),
            ]),
          ),
        ]),
        const SizedBox(height: 10),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(color: Brand.ink, borderRadius: BorderRadius.circular(12)),
          child: const Row(children: [
            Icon(Icons.lock_rounded, size: 18, color: Brand.steam),
            SizedBox(width: 8),
            Text('Password', style: TextStyle(color: Color(0xFFCFCDEB), fontWeight: FontWeight.w600)),
            Spacer(),
            SelectableText(AppConfig.demoPassword,
                style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 15)),
          ]),
        ),
        const SizedBox(height: 8),
        for (final u in AppConfig.demoUsers)
          InkWell(
            borderRadius: BorderRadius.circular(10),
            onTap: _busy ? null : () => _fillDemo(u[1]),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 9, horizontal: 2),
              child: Row(children: [
                Icon(_demoIcon(u[0]), size: 20, color: Brand.orangeDeep),
                const SizedBox(width: 10),
                Expanded(child: Text(u[0], style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15, color: Brand.ink))),
                Text(u[1],
                    style: const TextStyle(
                        fontWeight: FontWeight.w700, fontSize: 15, color: Brand.ink, fontFeatures: [FontFeature.tabularFigures()])),
              ]),
            ),
          ),
      ]),
    );
  }

  static IconData _demoIcon(String role) {
    switch (role) {
      case 'Owner':
        return Icons.workspace_premium_outlined;
      case 'Manager':
        return Icons.manage_accounts_outlined;
      case 'Captain':
        return Icons.room_service_outlined;
      case 'Cashier':
        return Icons.point_of_sale;
      case 'Kitchen':
        return Icons.soup_kitchen_outlined;
      case 'Rider':
        return Icons.delivery_dining_outlined;
      default:
        return Icons.inventory_2_outlined;
    }
  }
}
