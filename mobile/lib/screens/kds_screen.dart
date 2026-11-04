import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../brand/theme.dart';
import '../core/api_client.dart';
import '../core/config.dart';
import '../core/format.dart';
import '../core/json.dart';
import '../core/pos_data.dart';
import '../models/ops.dart';
import '../widgets/common.dart';
import '../widgets/offline_banner.dart';

const _nextKotStatus = <String, String>{
  'pending': 'preparing',
  'preparing': 'ready',
  'ready': 'served',
};

const _kotStatusColor = <String, Color>{
  'pending': Brand.orangeDeep,
  'preparing': Brand.warning,
  'ready': Brand.success,
};

const _kotActionLabel = <String, String>{
  'pending': 'Start preparing',
  'preparing': 'Mark ready',
  'ready': 'Picked up',
};

class KdsScreen extends StatefulWidget {
  const KdsScreen({super.key});

  @override
  State<KdsScreen> createState() => _KdsScreenState();
}

class _KdsScreenState extends State<KdsScreen> {
  Timer? _poll;
  Timer? _clock;
  List<Kot> _kots = [];
  final Set<int> _seen = {};
  bool _firstLoad = true;
  bool _loading = false;
  String? _error;
  int? _station;
  String _filter = 'all';

  @override
  void initState() {
    super.initState();
    _load();
    _poll = Timer.periodic(const Duration(seconds: 5), (_) => _load());
    _clock = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _poll?.cancel();
    _clock?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    if (_loading) return;
    _loading = true;
    final api = context.read<ApiClient>();
    final sound = context.read<AppConfig>().kdsSound;
    try {
      final rows = listOf(await api.get('/kots', query: {
        'status': 'pending,preparing,ready',
        if (_station != null) 'station': '$_station',
      }));
      final kots = rows.map((e) => Kot.fromJson(asMap(e))).toList();
      final fresh = kots.where((k) => k.status == 'pending' && !_seen.contains(k.id)).toList();
      _seen.addAll(kots.map((k) => k.id));
      if (fresh.isNotEmpty && !_firstLoad && sound) _alert();
      _firstLoad = false;
      if (mounted) {
        setState(() {
          _kots = kots;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = errorText(e));
    } finally {
      _loading = false;
    }
  }

  void _alert() {
    SystemSound.play(SystemSoundType.alert);
    HapticFeedback.heavyImpact();
    Future<void>.delayed(const Duration(milliseconds: 250), HapticFeedback.heavyImpact);
  }

  Future<void> _advance(Kot k) async {
    final next = _nextKotStatus[k.status];
    if (next == null) return;
    final api = context.read<ApiClient>();
    final previous = k.status;
    HapticFeedback.selectionClick();
    setState(() {
      k.status = next;
      if (next == 'served') _kots.remove(k);
    });
    try {
      await api.post('/kots/${k.id}/status', {'status': next});
    } catch (e) {
      if (!mounted) return;
      setState(() {
        k.status = previous;
        if (!_kots.contains(k)) _kots.add(k);
      });
      toast(context, errorText(e), error: true);
    }
  }

  Future<void> _kotMenu(Kot k) async {
    final api = context.read<ApiClient>();
    final action = await showSheet<String>(
      context,
      (ctx) => SheetFrame(
        title: 'KOT #${k.number} · ${k.orderLabel}',
        child: ListView(shrinkWrap: true, children: [
          if (k.status != 'pending')
            ListTile(
              leading: const Icon(Icons.undo),
              title: const Text('Move back to New'),
              onTap: () => Navigator.pop(ctx, 'pending'),
            ),
          ListTile(leading: const Icon(Icons.print_outlined), title: const Text('Reprint KOT'), onTap: () => Navigator.pop(ctx, 'reprint')),
          ListTile(
            leading: const Icon(Icons.cancel_outlined, color: Brand.danger),
            title: const Text('Cancel KOT'),
            onTap: () => Navigator.pop(ctx, 'cancelled'),
          ),
        ]),
      ),
    );
    if (action == null) return;
    try {
      if (action == 'reprint') {
        await api.post('/kots/${k.id}/reprint', {});
        if (mounted) toast(context, 'Sent to printer');
      } else {
        await api.post('/kots/${k.id}/status', {'status': action});
        await _load();
      }
    } catch (e) {
      if (mounted) toast(context, errorText(e), error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final stations = context.watch<PosData>().stations;
    final config = context.watch<AppConfig>();
    final visible = _kots.where((k) => _filter == 'all' || k.status == _filter).toList();
    int count(String s) => _kots.where((k) => k.status == s).length;

    return Scaffold(
      backgroundColor: const Color(0xFF0F0E2C),
      appBar: AppBar(
        backgroundColor: Brand.ink,
        foregroundColor: Colors.white,
        titleTextStyle: const TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w800),
        title: const Text('Kitchen Display'),
        actions: [
          if (stations.isNotEmpty)
            DropdownButtonHideUnderline(
              child: DropdownButton<int?>(
                value: _station,
                dropdownColor: Brand.ink,
                iconEnabledColor: Colors.white,
                style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 16),
                items: [
                  const DropdownMenuItem<int?>(value: null, child: Text('All stations')),
                  for (final s in stations) DropdownMenuItem<int?>(value: s.id, child: Text(s.name)),
                ],
                onChanged: (v) {
                  setState(() {
                    _station = v;
                    _kots = [];
                  });
                  _load();
                },
              ),
            ),
          IconButton(
            tooltip: config.kdsSound ? 'Mute' : 'Unmute',
            icon: Icon(config.kdsSound ? Icons.volume_up : Icons.volume_off),
            onPressed: () => config.setKdsSound(!config.kdsSound),
          ),
          IconButton(tooltip: 'Refresh', icon: const Icon(Icons.refresh), onPressed: _load),
        ],
      ),
      body: Column(children: [
        const OfflineBanner(),
        SizedBox(
          height: 56,
          child: ListView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            children: [
              for (final f in const ['all', 'pending', 'preparing', 'ready'])
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ChoiceChip(
                    label: Text(f == 'all'
                        ? 'All (${_kots.length})'
                        : '${f == 'pending' ? 'New' : Fmt.titleCase(f)} (${count(f)})'),
                    selected: _filter == f,
                    onSelected: (_) => setState(() => _filter = f),
                  ),
                ),
            ],
          ),
        ),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.all(8),
            child: Text(_error!, style: const TextStyle(color: Brand.steam)),
          ),
        Expanded(
          child: visible.isEmpty
              ? const Center(
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    Icon(Icons.check_circle_outline, color: Colors.white38, size: 72),
                    SizedBox(height: 12),
                    Text('All caught up', style: TextStyle(color: Colors.white70, fontSize: 20, fontWeight: FontWeight.w700)),
                  ]),
                )
              : GridView.builder(
                  padding: const EdgeInsets.fromLTRB(12, 4, 12, 24),
                  gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                    maxCrossAxisExtent: 340,
                    mainAxisSpacing: 12,
                    crossAxisSpacing: 12,
                    childAspectRatio: 0.78,
                  ),
                  itemCount: visible.length,
                  itemBuilder: (_, i) => _KotCard(
                    kot: visible[i],
                    onTap: () => _advance(visible[i]),
                    onLongPress: () => _kotMenu(visible[i]),
                  ),
                ),
        ),
      ]),
    );
  }
}

class _KotCard extends StatelessWidget {
  const _KotCard({required this.kot, required this.onTap, required this.onLongPress});

  final Kot kot;
  final VoidCallback onTap;
  final VoidCallback onLongPress;

  /// Escalates from status colour → amber (10m) → red (20m) while not ready.
  Color _ageColor(Duration age) {
    if (kot.status == 'ready') return Brand.success;
    if (age.inMinutes >= 20) return Brand.danger;
    if (age.inMinutes >= 10) return Brand.warning;
    return _kotStatusColor[kot.status] ?? Brand.info;
  }

  @override
  Widget build(BuildContext context) {
    final age = DateTime.now().difference(kot.createdAt);
    final color = _ageColor(age);
    final lines = kot.lines.where((l) => !l.isVoid).toList();
    return Material(
      color: Colors.white,
      borderRadius: BorderRadius.circular(18),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        onLongPress: onLongPress,
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Container(
            color: color,
            padding: const EdgeInsets.fromLTRB(14, 10, 14, 10),
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(kot.orderLabel,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w900)),
                  Text(
                    'KOT ${kot.number} · #${kot.orderNumber}${kot.stationName.isNotEmpty ? ' · ${kot.stationName}' : ''}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(color: Colors.white70, fontSize: 12, fontWeight: FontWeight.w600),
                  ),
                ]),
              ),
              Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                Text(Fmt.clock(kot.createdAt),
                    style: const TextStyle(
                        color: Colors.white, fontSize: 22, fontWeight: FontWeight.w900, fontFeatures: [FontFeature.tabularFigures()])),
                Text(kot.source.toUpperCase(), style: const TextStyle(color: Colors.white70, fontSize: 10, fontWeight: FontWeight.w800)),
              ]),
            ]),
          ),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.fromLTRB(14, 10, 14, 6),
              children: [
                for (final l in lines)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      SizedBox(
                        width: 38,
                        child: Text('${Fmt.qty(l.quantity)}×', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
                      ),
                      Expanded(
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text(l.displayName, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
                          if (l.notes.isNotEmpty || l.seat != null)
                            Text(
                              [if (l.seat != null) 'Seat ${l.seat}', if (l.notes.isNotEmpty) l.notes].join(' · '),
                              style: const TextStyle(color: Brand.orangeDeep, fontWeight: FontWeight.w700),
                            ),
                        ]),
                      ),
                    ]),
                  ),
                if (kot.orderNotes.isNotEmpty)
                  Container(
                    margin: const EdgeInsets.only(top: 6),
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(color: Brand.steam.withOpacity(0.5), borderRadius: BorderRadius.circular(8)),
                    child: Text('Note: ${kot.orderNotes}', style: const TextStyle(fontWeight: FontWeight.w700)),
                  ),
              ],
            ),
          ),
          Container(
            color: color.withOpacity(0.12),
            padding: const EdgeInsets.symmetric(vertical: 12),
            alignment: Alignment.center,
            child: Text(
              _kotActionLabel[kot.status] ?? Fmt.titleCase(kot.status),
              style: TextStyle(color: color, fontSize: 16, fontWeight: FontWeight.w900),
            ),
          ),
        ]),
      ),
    );
  }
}
