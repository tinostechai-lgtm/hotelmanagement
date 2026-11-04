import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../brand/logo.dart';
import '../brand/theme.dart';
import '../core/auth_store.dart';
import 'home_screen.dart';
import 'splash_screen.dart';

class RestaurantPickerScreen extends StatelessWidget {
  const RestaurantPickerScreen({super.key});

  Color _parse(String? hex) {
    if (hex == null || !hex.startsWith('#') || hex.length != 7) return Brand.orangeDeep;
    return Color(int.tryParse('FF${hex.substring(1)}', radix: 16) ?? 0xFFF0502A);
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthStore>();
    return Scaffold(
      appBar: AppBar(
        title: const ServoraLogo(size: 30, showWordmark: true),
        actions: [
          TextButton(onPressed: () => auth.logout(), child: const Text('Sign out')),
        ],
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              Text('Hi ${auth.userName}', style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w800)),
              const SizedBox(height: 4),
              const Text('Choose an outlet to work in', style: TextStyle(color: Brand.muted, fontSize: 16)),
              const SizedBox(height: 20),
              for (final m in auth.memberships)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Material(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(18),
                    child: InkWell(
                      borderRadius: BorderRadius.circular(18),
                      onTap: () async {
                        await auth.selectRestaurant(m.restaurantId);
                        if (context.mounted) {
                          Navigator.of(context).pushAndRemoveUntil(fadeRoute(const HomeScreen()), (_) => false);
                        }
                      },
                      child: Padding(
                        padding: const EdgeInsets.all(18),
                        child: Row(children: [
                          CircleAvatar(
                            radius: 26,
                            backgroundColor: _parse(m.brandColor),
                            child: Text(
                              m.restaurant.isEmpty ? '?' : m.restaurant[0].toUpperCase(),
                              style: const TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w800),
                            ),
                          ),
                          const SizedBox(width: 16),
                          Expanded(
                            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              Text(m.restaurant, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
                              Text('${m.role}${m.plan != null ? ' · ${m.plan}' : ''}',
                                  style: const TextStyle(color: Brand.muted)),
                            ]),
                          ),
                          const Icon(Icons.chevron_right),
                        ]),
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
