import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../brand/logo.dart';
import '../brand/theme.dart';
import '../core/auth_store.dart';
import '../core/format.dart';
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
  const AppMode(this.perm, this.title, this.subtitle, this.icon, this.builder, this.colors);

  final String perm;
  final String title;
  final String subtitle;
  final IconData icon;
  final WidgetBuilder builder;
  final List<Color> colors;
}

final List<AppMode> appModes = [
  AppMode('pos', 'POS & Tables', 'Take orders, bill & settle', Icons.point_of_sale_rounded, (_) => const TablesScreen(),
      [Color(0xFFEA580C), Color(0xFFB4290F)]),
  AppMode('kitchen', 'Kitchen', 'Live KOTs by station', Icons.soup_kitchen_rounded, (_) => const KdsScreen(),
      [Color(0xFF7C3AED), Color(0xFF4C1D95)]),
  AppMode('delivery', 'Delivery', 'Assign riders, track', Icons.delivery_dining_rounded, (_) => const DeliveryOpsScreen(),
      [Color(0xFF0F766E), Color(0xFF134E4A)]),
  AppMode('rider', 'Rider', 'My deliveries & maps', Icons.two_wheeler_rounded, (_) => const RiderScreen(),
      [Color(0xFF15803D), Color(0xFF14532D)]),
  AppMode('reports', 'Reports', 'Sales at a glance', Icons.insights_rounded, (_) => const ReportsScreen(),
      [Color(0xFF2563EB), Color(0xFF1E3A8A)]),
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
      case 'logout':
        if (await confirm(context, 'Sign out?', 'Offline orders stay on this device and sync after you sign in again.',
            ok: 'Sign out')) {
          await auth.logout();
        }
    }
  }

  String _greeting() {
    final h = DateTime.now().hour;
    if (h < 12) return 'Good morning';
    if (h < 17) return 'Good afternoon';
    return 'Good evening';
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthStore>();
    final data = context.watch<PosData>();
    final modes = appModes.where((m) => auth.can(m.perm)).toList();
    final width = MediaQuery.sizeOf(context).width;
    final columns = width >= 1000 ? 4 : (width >= 640 ? 3 : 2);
    final occupied = data.tables.where((t) => t.activeOrder != null).length;
    final free = data.tables.where((t) => t.effectiveStatus == 'free').length;
    final running = data.tables.fold<double>(0, (s, t) => s + (t.activeOrder?.total ?? 0));
    final firstName = auth.userName.split(' ').first;

    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: lightStatusBar,
      child: Scaffold(
        body: RefreshIndicator(
          onRefresh: () => data.load(silent: true),
          child: CustomScrollView(
            physics: const AlwaysScrollableScrollPhysics(),
            slivers: [
              SliverToBoxAdapter(
                child: Container(
                  decoration: const BoxDecoration(
                    gradient: Brand.inkGradient,
                    borderRadius: BorderRadius.vertical(bottom: Radius.circular(32)),
                  ),
                  child: Stack(children: [
                    SafeArea(
                      bottom: false,
                      child: Padding(
                        padding: const EdgeInsets.fromLTRB(18, 10, 8, 22),
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Row(children: [
                            const ServoraLogo(size: 40),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                                Text(auth.membership?.restaurant ?? data.restaurantName,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w800)),
                                const SizedBox(height: 2),
                                Container(
                                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                                  decoration: BoxDecoration(
                                    color: const Color(0xFF4A2C3A),
                                    borderRadius: BorderRadius.circular(99),
                                  ),
                                  child: Text(auth.membership?.role ?? '',
                                      style: const TextStyle(color: Brand.steam, fontSize: 13, fontWeight: FontWeight.w700)),
                                ),
                              ]),
                            ),
                            IconButton(
                              tooltip: 'Switch user (PIN)',
                              color: Colors.white,
                              icon: const Icon(Icons.switch_account_rounded),
                              onPressed: () => _menu('pin'),
                            ),
                            PopupMenuButton<String>(
                              iconColor: Colors.white,
                              onSelected: _menu,
                              itemBuilder: (_) => [
                                if (auth.memberships.length > 1)
                                  const PopupMenuItem(value: 'outlet', child: ListTile(leading: Icon(Icons.storefront_rounded), title: Text('Change outlet'))),
                                const PopupMenuItem(value: 'printers', child: ListTile(leading: Icon(Icons.print_rounded), title: Text('Printers'))),
                                const PopupMenuItem(value: 'logout', child: ListTile(leading: Icon(Icons.logout_rounded, color: Brand.danger), title: Text('Sign out'))),
                              ],
                            ),
                          ]),
                          const SizedBox(height: 22),
                          Text('${_greeting()},',
                              style: const TextStyle(color: Color(0xFFCFCDEB), fontSize: 16, fontWeight: FontWeight.w500)),
                          Text(firstName,
                              style: const TextStyle(color: Colors.white, fontSize: 30, fontWeight: FontWeight.w900, letterSpacing: -0.6)),
                          if (data.tables.isNotEmpty) ...[
                            const SizedBox(height: 18),
                            Padding(
                              padding: const EdgeInsets.only(right: 10),
                              child: Row(children: [
                                _HeaderStat(label: 'Occupied', value: '$occupied', icon: Icons.restaurant_rounded),
                                const SizedBox(width: 10),
                                _HeaderStat(label: 'Free tables', value: '$free', icon: Icons.event_seat_rounded),
                                const SizedBox(width: 10),
                                _HeaderStat(label: 'Running', value: Fmt.money(running), icon: Icons.payments_rounded),
                              ]),
                            ),
                          ],
                        ]),
                      ),
                    ),
                  ]),
                ),
              ),
              const SliverToBoxAdapter(child: OfflineBanner()),
              if (data.fromCache)
                SliverToBoxAdapter(
                  child: Container(
                    margin: const EdgeInsets.fromLTRB(16, 14, 16, 0),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(color: const Color(0xFFFFF1E6), borderRadius: BorderRadius.circular(14)),
                    child: const Row(children: [
                      Icon(Icons.cloud_off_rounded, color: Brand.orangeDeep),
                      SizedBox(width: 10),
                      Expanded(
                        child: Text('Showing your saved menu & tables (offline copy).',
                            style: TextStyle(fontWeight: FontWeight.w700, color: Color(0xFF7C2D12))),
                      ),
                    ]),
                  ),
                ),
              if (data.loading && !data.isLoaded) const SliverToBoxAdapter(child: LinearProgressIndicator()),
              const SliverToBoxAdapter(
                child: Padding(
                  padding: EdgeInsets.fromLTRB(20, 22, 20, 4),
                  child: Text('Your workspace', style: TextStyle(fontSize: 19, fontWeight: FontWeight.w900, letterSpacing: -0.3)),
                ),
              ),
              if (modes.isEmpty)
                const SliverToBoxAdapter(
                  child: EmptyState(
                    icon: Icons.lock_outline_rounded,
                    title: 'No app modes for your role',
                    message: 'Ask your manager to give your role POS, Kitchen, Delivery, Rider or Reports access.',
                  ),
                )
              else
                SliverPadding(
                  padding: const EdgeInsets.fromLTRB(16, 10, 16, 32),
                  sliver: SliverGrid(
                    gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                      crossAxisCount: columns,
                      mainAxisSpacing: 14,
                      crossAxisSpacing: 14,
                      childAspectRatio: 0.95,
                    ),
                    delegate: SliverChildBuilderDelegate(
                      (context, i) => _ModeCard(mode: modes[i], index: i),
                      childCount: modes.length,
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

class _HeaderStat extends StatelessWidget {
  const _HeaderStat({required this.label, required this.value, required this.icon});

  final String label;
  final String value;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 10, 10, 10),
        decoration: BoxDecoration(
          color: const Color(0xFF2E2A6E),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: const Color(0xFF3F3B85)),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(icon, size: 18, color: Brand.steam),
          const SizedBox(height: 6),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerLeft,
            child: Text(value, style: const TextStyle(color: Colors.white, fontSize: 19, fontWeight: FontWeight.w900)),
          ),
          Text(label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: Color(0xFFCFCDEB), fontSize: 13, fontWeight: FontWeight.w600)),
        ]),
      ),
    );
  }
}

class _ModeCard extends StatefulWidget {
  const _ModeCard({required this.mode, required this.index});

  final AppMode mode;
  final int index;

  @override
  State<_ModeCard> createState() => _ModeCardState();
}

class _ModeCardState extends State<_ModeCard> {
  bool _down = false;

  @override
  Widget build(BuildContext context) {
    final m = widget.mode;
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: Duration(milliseconds: 450 + widget.index * 90),
      curve: Curves.easeOutCubic,
      builder: (context, t, child) => Opacity(
        opacity: t,
        child: Transform.translate(offset: Offset(0, 24 * (1 - t)), child: child),
      ),
      child: AnimatedScale(
        scale: _down ? 0.96 : 1,
        duration: const Duration(milliseconds: 120),
        child: GestureDetector(
          onTapDown: (_) => setState(() => _down = true),
          onTapCancel: () => setState(() => _down = false),
          onTapUp: (_) => setState(() => _down = false),
          onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: m.builder)),
          child: Container(
            decoration: BoxDecoration(
              gradient: Brand.accent(m.colors[0], m.colors[1]),
              borderRadius: BorderRadius.circular(24),
              boxShadow: [BoxShadow(color: m.colors[1].withOpacity(0.35), blurRadius: 18, offset: const Offset(0, 10))],
            ),
            child: Stack(children: [
              Padding(
                padding: const EdgeInsets.all(16),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Container(
                    width: 48,
                    height: 48,
                    decoration: BoxDecoration(color: Colors.white.withOpacity(0.22), borderRadius: BorderRadius.circular(15)),
                    child: Icon(m.icon, color: Colors.white, size: 27),
                  ),
                  const Spacer(),
                  FittedBox(
                    fit: BoxFit.scaleDown,
                    alignment: Alignment.centerLeft,
                    child: Text(m.title,
                        maxLines: 1,
                        style: const TextStyle(color: Colors.white, fontSize: 19, fontWeight: FontWeight.w900, letterSpacing: -0.3)),
                  ),
                  const SizedBox(height: 2),
                  Text(m.subtitle,
                      maxLines: 2,
                      style: const TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w600, height: 1.3)),
                ]),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}
