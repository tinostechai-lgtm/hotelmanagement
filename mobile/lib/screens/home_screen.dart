import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../brand/logo.dart';
import '../brand/theme.dart';
import '../core/auth_store.dart';
import '../core/offline_queue.dart';
import '../core/pos_data.dart';
import '../core/print_service.dart';
import '../widgets/common.dart';
import '../widgets/offline_banner.dart';
import '../widgets/settings_sheets.dart';
import 'delivery_ops_screen.dart';
import 'kds_screen.dart';
import 'printers_screen.dart';
import 'reports_screen.dart';
import 'restaurant_picker_screen.dart';
import 'rider_screen.dart';
import 'splash_screen.dart';
import 'tables_screen.dart';

class AppMode {
  const AppMode(this.perm, this.title, this.subtitle, this.icon, this.builder);

  final String perm;
  final String title;
  final String subtitle;
  final IconData icon;
  final WidgetBuilder builder;
}

final List<AppMode> appModes = [
  AppMode('pos', 'POS & Tables', 'Take orders, bill & settle', Icons.point_of_sale, (_) => const TablesScreen()),
  AppMode('kitchen', 'Kitchen Display', 'Live KOTs by station', Icons.soup_kitchen_outlined, (_) => const KdsScreen()),
  AppMode('delivery', 'Delivery Ops', 'Assign riders, track tasks', Icons.delivery_dining, (_) => const DeliveryOpsScreen()),
  AppMode('rider', 'Rider', 'My deliveries & navigation', Icons.two_wheeler, (_) => const RiderScreen()),
  AppMode('reports', 'Reports', "Today's sales at a glance", Icons.insights, (_) => const ReportsScreen()),
];

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<PosData>().load();
      context.read<PrintService>().refreshState();
      context.read<OfflineQueue>().sync();
    });
  }

  Future<void> _menu(String v) async {
    final auth = context.read<AuthStore>();
    switch (v) {
      case 'pin':
        final ok = await showPinSwitch(context);
        if (ok && mounted) {
          toast(context, 'Switched to ${auth.userName}');
          await context.read<PosData>().load(silent: true);
        }
      case 'outlet':
        Navigator.of(context).pushAndRemoveUntil(fadeRoute(const RestaurantPickerScreen()), (_) => false);
      case 'printers':
        Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const PrintersScreen()));
      case 'server':
        await showServerSettings(context);
      case 'logout':
        if (await confirm(context, 'Sign out?', 'Offline orders stay on this device and sync after you sign in again.',
            ok: 'Sign out')) {
          await auth.logout();
        }
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthStore>();
    final data = context.watch<PosData>();
    final modes = appModes.where((m) => auth.can(m.perm)).toList();
    final width = MediaQuery.sizeOf(context).width;
    final columns = width >= 1100 ? 3 : (width >= 640 ? 2 : 1);

    return Scaffold(
      appBar: AppBar(
        titleSpacing: 16,
        title: Row(children: [
          const ServoraLogo(size: 34),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(auth.membership?.restaurant ?? data.restaurantName,
                  overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
              Text('${auth.userName} · ${auth.membership?.role ?? ''}',
                  style: const TextStyle(fontSize: 13, color: Brand.muted, fontWeight: FontWeight.w500)),
            ]),
          ),
        ]),
        actions: [
          IconButton(
            tooltip: 'Switch user (PIN)',
            icon: const Icon(Icons.switch_account_outlined),
            onPressed: () => _menu('pin'),
          ),
          PopupMenuButton<String>(
            onSelected: _menu,
            itemBuilder: (_) => [
              if (auth.memberships.length > 1) const PopupMenuItem(value: 'outlet', child: Text('Change outlet')),
              const PopupMenuItem(value: 'printers', child: Text('Printers')),
              const PopupMenuItem(value: 'server', child: Text('Server settings')),
              const PopupMenuItem(value: 'logout', child: Text('Sign out')),
            ],
          ),
        ],
      ),
      body: Column(children: [
        const OfflineBanner(),
        if (data.fromCache)
          Container(
            width: double.infinity,
            color: Brand.steam.withOpacity(0.6),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: const Text('Using saved menu & tables (offline copy).', style: TextStyle(fontWeight: FontWeight.w600)),
          ),
        Expanded(
          child: RefreshIndicator(
            onRefresh: () => data.load(silent: true),
            child: modes.isEmpty
                ? ListView(children: const [
                    SizedBox(height: 80),
                    EmptyState(
                      icon: Icons.lock_outline,
                      title: 'No app modes for your role',
                      message: 'Ask your manager to give your role POS, Kitchen, Delivery, Rider or Reports access.',
                    ),
                  ])
                : GridView.builder(
                    padding: const EdgeInsets.all(16),
                    gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                      crossAxisCount: columns,
                      mainAxisSpacing: 14,
                      crossAxisSpacing: 14,
                      mainAxisExtent: 128,
                    ),
                    itemCount: modes.length,
                    itemBuilder: (context, i) => _ModeCard(mode: modes[i], primary: i == 0),
                  ),
          ),
        ),
        if (data.loading && !data.isLoaded) const LinearProgressIndicator(),
      ]),
    );
  }
}

class _ModeCard extends StatelessWidget {
  const _ModeCard({required this.mode, required this.primary});

  final AppMode mode;
  final bool primary;

  @override
  Widget build(BuildContext context) {
    final fg = primary ? Colors.white : Brand.ink;
    return Material(
      color: Colors.transparent,
      child: Ink(
        decoration: BoxDecoration(
          gradient: primary ? Brand.gradient : null,
          color: primary ? null : Colors.white,
          borderRadius: BorderRadius.circular(22),
          border: primary ? null : Border.all(color: Brand.line),
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(22),
          onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: mode.builder)),
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Row(children: [
              Container(
                width: 64,
                height: 64,
                decoration: BoxDecoration(
                  color: primary ? Colors.white.withOpacity(0.2) : Brand.orangeDeep.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(18),
                ),
                child: Icon(mode.icon, size: 34, color: primary ? Colors.white : Brand.orangeDeep),
              ),
              const SizedBox(width: 18),
              Expanded(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(mode.title, style: TextStyle(color: fg, fontSize: 20, fontWeight: FontWeight.w800)),
                    const SizedBox(height: 4),
                    Text(mode.subtitle, style: TextStyle(color: fg.withOpacity(0.75), fontSize: 14)),
                  ],
                ),
              ),
              Icon(Icons.arrow_forward_ios, size: 18, color: fg.withOpacity(0.7)),
            ]),
          ),
        ),
      ),
    );
  }
}
