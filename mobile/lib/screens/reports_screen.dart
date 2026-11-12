import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../brand/theme.dart';
import '../core/api_client.dart';
import '../core/format.dart';
import '../core/json.dart';
import '../core/pos_data.dart';
import '../widgets/common.dart';
import '../widgets/offline_banner.dart';

class ReportsScreen extends StatefulWidget {
  const ReportsScreen({super.key});

  @override
  State<ReportsScreen> createState() => _ReportsScreenState();
}

class _ReportsScreenState extends State<ReportsScreen> {
  static const _ranges = {'today': 'Today', 'yesterday': 'Yesterday', '7d': '7 days', '30d': '30 days'};
  String _range = 'today';
  Map<String, dynamic>? _data;
  Map<String, dynamic>? _items;
  String? _error;
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final api = context.read<ApiClient>();
    final today = DateTime.now();
    final day = DateTime(today.year, today.month, today.day);
    final (DateTime start, DateTime end) = switch (_range) {
      'yesterday' => (day.subtract(const Duration(days: 1)), day.subtract(const Duration(days: 1))),
      '7d' => (day.subtract(const Duration(days: 6)), day),
      '30d' => (day.subtract(const Duration(days: 29)), day),
      _ => (day, day),
    };
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final q = {'start': Fmt.isoDate(start), 'end': Fmt.isoDate(end)};
      final res = await Future.wait([api.get('/reports/summary', query: q), api.get('/reports/items', query: q)]);
      if (mounted) {
        setState(() {
          _data = asMap(res[0]);
          _items = asMap(res[1]);
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = errorText(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = _data;
    final width = MediaQuery.sizeOf(context).width;
    final cols = width >= 900 ? 4 : 2;
    return Scaffold(
      appBar: AppBar(title: const Text('Reports'), actions: [IconButton(onPressed: _load, icon: const Icon(Icons.refresh))]),
      body: Column(children: [
        const OfflineBanner(),
        SizedBox(
          height: 56,
          child: ListView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            children: [
              for (final e in _ranges.entries)
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ChoiceChip(
                    label: Text(e.value),
                    selected: _range == e.key,
                    onSelected: (_) {
                      setState(() => _range = e.key);
                      _load();
                    },
                  ),
                ),
            ],
          ),
        ),
        if (_loading) const LinearProgressIndicator(),
        Expanded(
          child: d == null
              ? (_error != null
                  ? EmptyState(icon: Icons.insights, title: 'Could not load reports', message: _error)
                  : const SizedBox.shrink())
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 32), children: [
                    GridView.count(
                      crossAxisCount: cols,
                      shrinkWrap: true,
                      physics: const NeverScrollableScrollPhysics(),
                      mainAxisSpacing: 12,
                      crossAxisSpacing: 12,
                      childAspectRatio: 1.55,
                      children: [
                        StatCard(label: 'Sales', value: Fmt.money(asDouble(d['sales'])), icon: Icons.currency_rupee, highlight: true),
                        StatCard(label: 'Orders', value: '${asInt(d['orders'])}', icon: Icons.receipt_long_rounded, color: Brand.info),
                        StatCard(label: 'Avg order', value: Fmt.money(asDouble(d['avg_order_value'])), icon: Icons.trending_up_rounded, color: Brand.success),
                        StatCard(label: 'Guests', value: '${asInt(d['guests'])}', icon: Icons.groups_rounded, color: Brand.violet),
                        if (context.read<PosData>().gstEnabled)
                          StatCard(label: 'GST', value: Fmt.money(asDouble(d['tax'])), icon: Icons.account_balance_rounded, color: Brand.teal),
                        StatCard(label: 'Discounts', value: Fmt.money(asDouble(d['discount'])), icon: Icons.local_offer_rounded, color: Brand.warning),
                        StatCard(label: 'Open orders', value: '${asInt(d['open_orders'])}', icon: Icons.pending_actions_rounded, color: Brand.orangeDeep),
                        StatCard(label: 'Cancelled', value: '${asInt(d['cancelled'])}', icon: Icons.cancel_rounded, color: Brand.danger),
                      ],
                    ),
                    _BreakdownCard(
                      title: 'Payment modes',
                      rows: listOf(d['by_payment'])
                          .map((e) => (Fmt.titleCase(asStr(e['method'])), asDouble(e['amount']), asInt(e['n'])))
                          .toList(),
                    ),
                    _BreakdownCard(
                      title: 'Order types',
                      rows: listOf(d['by_type'])
                          .map((e) => (Fmt.titleCase(asStr(e['order_type'])), asDouble(e['amount']), asInt(e['n'])))
                          .toList(),
                    ),
                    if (_items != null) _ItemSales(data: _items!),
                    _Hourly(rows: listOf(d['hourly'])),
                  ]),
                ),
        ),
      ]),
    );
  }
}

class _Panel extends StatelessWidget {
  const _Panel({required this.title, required this.child});

  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(top: 16),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(22),
        boxShadow: Brand.shadow,
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text(title, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w900, letterSpacing: -0.2)),
        const SizedBox(height: 12),
        child,
      ]),
    );
  }
}

class _BreakdownCard extends StatelessWidget {
  const _BreakdownCard({required this.title, required this.rows});

  final String title;
  final List<(String, double, int)> rows;

  @override
  Widget build(BuildContext context) {
    final total = rows.fold<double>(0, (s, r) => s + r.$2);
    return _Panel(
      title: title,
      child: rows.isEmpty
          ? const Text('No data yet', style: TextStyle(color: Brand.muted))
          : Column(children: [
              for (final r in rows)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Row(children: [
                      Expanded(child: Text(r.$1, style: const TextStyle(fontWeight: FontWeight.w700))),
                      Text('${r.$3} · ', style: const TextStyle(color: Brand.muted)),
                      Text(Fmt.money(r.$2), style: const TextStyle(fontWeight: FontWeight.w800)),
                    ]),
                    const SizedBox(height: 6),
                    ClipRRect(
                      borderRadius: BorderRadius.circular(8),
                      child: LinearProgressIndicator(
                        value: total > 0 ? r.$2 / total : 0,
                        minHeight: 10,
                        backgroundColor: const Color(0xFFF0EFF7),
                        color: Brand.orangeDeep,
                      ),
                    ),
                  ]),
                ),
            ]),
    );
  }
}

class _TopItems extends StatelessWidget {
  const _TopItems({required this.rows});

  final List<dynamic> rows;

  @override
  Widget build(BuildContext context) {
    return _Panel(
      title: 'Top items',
      child: rows.isEmpty
          ? const Text('No sales yet', style: TextStyle(color: Brand.muted))
          : Column(children: [
              for (var i = 0; i < rows.length; i++)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  dense: true,
                  leading: CircleAvatar(
                    radius: 15,
                    backgroundColor: i < 3 ? Brand.orangeDeep : Brand.line,
                    child: Text('${i + 1}',
                        style: TextStyle(color: i < 3 ? Colors.white : Brand.ink, fontWeight: FontWeight.w800, fontSize: 13)),
                  ),
                  title: Text(asStr(rows[i]['name']), style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
                  subtitle: Text('${Fmt.qty(asDouble(rows[i]['qty']))} sold'),
                  trailing: Text(Fmt.money(asDouble(rows[i]['amount'])), style: const TextStyle(fontWeight: FontWeight.w800)),
                ),
            ]),
    );
  }
}

class _Hourly extends StatelessWidget {
  const _Hourly({required this.rows});

  final List<dynamic> rows;

  @override
  Widget build(BuildContext context) {
    if (rows.isEmpty) return const SizedBox.shrink();
    final values = {for (final r in rows) asInt(r['hour']): asDouble(r['sales'])};
    final maxV = values.values.fold<double>(0, (m, v) => v > m ? v : m);
    final hours = values.keys.toList()..sort();
    final from = hours.first;
    final to = hours.last;
    return _Panel(
      title: 'Sales by hour',
      child: SizedBox(
        height: 140,
        child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          for (var h = from; h <= to; h++)
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 2),
                child: Column(mainAxisAlignment: MainAxisAlignment.end, children: [
                  Flexible(
                    child: FractionallySizedBox(
                      heightFactor: maxV > 0 ? ((values[h] ?? 0) / maxV).clamp(0.02, 1.0) : 0.02,
                      child: Container(
                        decoration: BoxDecoration(gradient: Brand.gradient, borderRadius: BorderRadius.circular(4)),
                      ),
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text('$h', style: const TextStyle(fontSize: 13, color: Brand.muted)),
                ]),
              ),
            ),
        ]),
      ),
    );
  }
}


/// Every item sold in the period: quantity and amount, with totals.
class _ItemSales extends StatelessWidget {
  const _ItemSales({required this.data});

  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) {
    final rows = listOf(data['items']).map(asMap).toList();
    TextStyle h = const TextStyle(fontWeight: FontWeight.w800, fontSize: 13, color: Brand.muted);
    Widget line(String a, String b, String c, {bool bold = false, Color? color}) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 7),
          child: Row(children: [
            Expanded(child: Text(a, style: TextStyle(fontWeight: bold ? FontWeight.w900 : FontWeight.w700, fontSize: 15, color: color))),
            SizedBox(width: 56, child: Text(b, textAlign: TextAlign.right, style: TextStyle(fontWeight: FontWeight.w900, fontSize: 15, color: color))),
            SizedBox(width: 96, child: Text(c, textAlign: TextAlign.right, style: TextStyle(fontWeight: bold ? FontWeight.w900 : FontWeight.w700, fontSize: 15, color: color))),
          ]),
        );
    return _Panel(
      title: 'Item-wise sales',
      child: rows.isEmpty
          ? const Text('No completed orders in this period', style: TextStyle(color: Brand.muted))
          : Column(children: [
              Row(children: [
                Expanded(child: Text('ITEM', style: h)),
                SizedBox(width: 56, child: Text('QTY', textAlign: TextAlign.right, style: h)),
                SizedBox(width: 96, child: Text('AMOUNT', textAlign: TextAlign.right, style: h)),
              ]),
              const Divider(height: 14),
              for (final r in rows) line(asStr(r['name']), Fmt.qty(asDouble(r['qty'])), Fmt.money(asDouble(r['amount']))),
              const Divider(height: 14, thickness: 2),
              line('Total (${data['item_count']} items)', Fmt.qty(asDouble(data['total_qty'])), Fmt.money(asDouble(data['total_amount'])), bold: true),
              if (asDouble(data['discount']) > 0)
                line('Less discounts', '', '-${Fmt.money(asDouble(data['discount']))}', color: Brand.success),
              line('Net sales (${data['orders']} orders)', '', Fmt.money(asDouble(data['net_sales'])), bold: true, color: Brand.orangeDeep),
            ]),
    );
  }
}
