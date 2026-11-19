import 'package:flutter/material.dart';
import 'package:print_bluetooth_thermal/print_bluetooth_thermal.dart';
import 'package:provider/provider.dart';

import '../brand/theme.dart';
import '../core/api_client.dart';
import '../core/config.dart';
import '../core/format.dart';
import '../core/json.dart';
import '../core/print_service.dart';
import '../models/ops.dart';
import '../widgets/common.dart';

/// Printer setup for this phone: which printer prints bills and KOTs, paper width
/// and text size. Pressing KOT / Bill / Print then prints straight away.
class PrintersScreen extends StatefulWidget {
  const PrintersScreen({super.key});

  @override
  State<PrintersScreen> createState() => _PrintersScreenState();
}

class _PrintersScreenState extends State<PrintersScreen> {
  List<PrintJob> _jobs = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final api = context.read<ApiClient>();
    setState(() => _loading = true);
    try {
      final rows = listOf(await api.get('/print-jobs', query: {'since': '86400'}));
      if (mounted) {
        setState(() {
          _jobs = rows.map((e) => PrintJob.fromJson(asMap(e))).toList()..sort((a, b) => b.id.compareTo(a.id));
          _jobs = _jobs.take(30).toList();
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = errorText(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// Bottom sheet: Bluetooth printer from the paired list, Wi-Fi printer IP, or none.
  Future<void> _choose({required bool kot}) async {
    final config = context.read<AppConfig>();
    List<BluetoothInfo> paired = const [];
    String? btError;
    try {
      paired = await PrintBluetoothThermal.pairedBluetooths.timeout(const Duration(seconds: 6), onTimeout: () => const []);
    } catch (e) {
      btError = 'Bluetooth is off or not allowed';
    }
    if (!mounted) return;
    final lan = TextEditingController(text: kot ? config.kotLan : config.fallbackLanPrinter);
    final picked = await showSheet<String>(
      context,
      (ctx) => SheetFrame(
        title: kot ? 'Kitchen (KOT) printer' : 'Bill printer',
        child: ListView(shrinkWrap: true, padding: const EdgeInsets.only(bottom: 16), children: [
          if (kot)
            ListTile(
              leading: const Icon(Icons.link),
              title: const Text('Same printer as bills'),
              subtitle: const Text('One printer for everything'),
              onTap: () => Navigator.pop(ctx, 'same'),
            ),
          const Padding(
            padding: EdgeInsets.fromLTRB(16, 8, 16, 4),
            child: Text('Bluetooth printers paired with this phone', style: TextStyle(fontWeight: FontWeight.w800)),
          ),
          if (paired.isEmpty)
            ListTile(
              leading: const Icon(Icons.bluetooth_disabled),
              title: Text(btError ?? 'No paired printers'),
              subtitle: const Text('Turn the printer on, then pair it in the phone\'s Bluetooth settings (PIN is often 0000 or 1234).'),
            ),
          for (final d in paired)
            ListTile(
              leading: const Icon(Icons.print),
              title: Text(d.name),
              subtitle: Text(d.macAdress),
              onTap: () => Navigator.pop(ctx, 'bt:${d.macAdress}|${d.name}'),
            ),
          const Divider(),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
            child: TextField(
              controller: lan,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(
                labelText: 'Wi-Fi / LAN printer IP',
                hintText: '192.168.1.50:9100',
                prefixIcon: Icon(Icons.wifi),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: FilledButton(
              onPressed: () => Navigator.pop(ctx, lan.text.trim().isEmpty ? null : 'lan:${lan.text.trim()}'),
              child: const Text('Use this Wi-Fi printer'),
            ),
          ),
        ]),
      ),
    );
    Future.delayed(const Duration(milliseconds: 500), lan.dispose);
    if (picked == null) return;
    if (kot) {
      if (picked == 'same') {
        await config.setKotPrinter();
      } else if (picked.startsWith('bt:')) {
        final p = picked.substring(3).split('|');
        await config.setKotPrinter(mac: p.first, name: p.length > 1 ? p[1] : '');
      } else {
        await config.setKotPrinter(lan: picked.substring(4));
      }
    } else {
      if (picked.startsWith('bt:')) {
        final p = picked.substring(3).split('|');
        await config.setBluetoothPrinter(p.first, p.length > 1 ? p[1] : '');
        await config.setFallbackLanPrinter('');
      } else {
        await config.setBluetoothPrinter('', '');
        await config.setFallbackLanPrinter(picked.substring(4));
      }
    }
    if (mounted) context.read<PrintService>().refreshState();
  }

  Future<void> _test(String kind) async {
    final printer = context.read<PrintService>();
    try {
      await printer.testPrint(kind);
      if (mounted) toast(context, 'Test page sent');
    } catch (e) {
      if (mounted) toast(context, 'Print failed: ${e.toString().replaceFirst('Exception: ', '')}', error: true);
    }
  }

  Future<void> _printHere(PrintJob job) async {
    final printer = context.read<PrintService>();
    try {
      final r = await printer.printAgain(job);
      await _load();
      if (mounted) toast(context, r.error ?? (r.printed > 0 ? 'Printed' : 'No printer set up for this'), error: r.printed == 0);
    } catch (e) {
      if (mounted) toast(context, errorText(e), error: true);
    }
  }

  String _describe(AppConfig c, {required bool kot}) {
    if (kot && !c.hasKotPrinter) return c.hasMainPrinter ? 'Same printer as bills' : 'Not set';
    final mac = kot ? c.kotBtMac : c.btPrinterMac;
    final name = kot ? c.kotBtName : c.btPrinterName;
    final lan = kot ? c.kotLan : c.fallbackLanPrinter;
    if (mac.isNotEmpty) return 'Bluetooth · ${name.isEmpty ? mac : name}';
    if (lan.isNotEmpty) return 'Wi-Fi · $lan';
    return 'Not set - tap to choose';
  }

  Widget _card(List<Widget> children) => Container(
        margin: const EdgeInsets.only(bottom: 14),
        decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(18), border: Border.all(color: Brand.line)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children),
      );

  @override
  Widget build(BuildContext context) {
    final config = context.watch<AppConfig>();
    final printer = context.watch<PrintService>();
    return Scaffold(
      appBar: AppBar(title: const Text('Printers'), actions: [IconButton(onPressed: _load, icon: const Icon(Icons.refresh))]),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(padding: const EdgeInsets.all(16), children: [
          _card([
            ListTile(
              leading: const Icon(Icons.receipt_long),
              title: const Text('Bill printer', style: TextStyle(fontWeight: FontWeight.w800)),
              subtitle: Text(_describe(config, kot: false)),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => _choose(kot: false),
            ),
            const Divider(height: 1),
            ListTile(
              leading: const Icon(Icons.soup_kitchen_outlined),
              title: const Text('KOT (kitchen) printer', style: TextStyle(fontWeight: FontWeight.w800)),
              subtitle: Text(_describe(config, kot: true)),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => _choose(kot: true),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 14),
              child: Wrap(spacing: 8, runSpacing: 8, children: [
                OutlinedButton.icon(
                    onPressed: config.hasMainPrinter ? () => _test('bill') : null,
                    icon: const Icon(Icons.print_outlined),
                    label: const Text('Test bill printer')),
                OutlinedButton.icon(
                    onPressed: config.targetFor('kot') != null ? () => _test('kot') : null,
                    icon: const Icon(Icons.print_outlined),
                    label: const Text('Test KOT printer')),
              ]),
            ),
          ]),
          _card([
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 14, 16, 6),
              child: Text('Paper width', style: TextStyle(fontWeight: FontWeight.w800)),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: SegmentedButton<int>(
                segments: const [
                  ButtonSegment(value: 58, label: Text('58 mm (2 inch)')),
                  ButtonSegment(value: 80, label: Text('80 mm (3 inch)')),
                ],
                selected: {config.paperWidth},
                onSelectionChanged: (v) => config.setPrintOptions(paper: v.first),
              ),
            ),
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 16, 16, 6),
              child: Text('Text size on paper', style: TextStyle(fontWeight: FontWeight.w800)),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: SegmentedButton<String>(
                segments: const [
                  ButtonSegment(value: 'normal', label: Text('Normal')),
                  ButtonSegment(value: 'large', label: Text('Large')),
                  ButtonSegment(value: 'xlarge', label: Text('Extra large')),
                ],
                selected: {config.textSize},
                onSelectionChanged: (v) => config.setPrintOptions(size: v.first),
              ),
            ),
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 8, 16, 14),
              child: Text('Large makes letters twice as tall - easiest to read. Print a test page after changing.',
                  style: TextStyle(color: Brand.muted, fontSize: 13)),
            ),
          ]),
          _card([
            SwitchListTile.adaptive(
              value: config.autoPrint,
              onChanged: (v) => config.setPrintOptions(auto: v),
              title: const Text('Print straight away', style: TextStyle(fontWeight: FontWeight.w800)),
              subtitle: const Text('Pressing KOT, Bill or Print prints on the printers above - no extra steps.'),
            ),
            const Divider(height: 1),
            SwitchListTile.adaptive(
              value: config.printKotHere,
              onChanged: (v) => config.setPrintOptions(kot: v),
              title: const Text('Print KOTs from this phone'),
            ),
            SwitchListTile.adaptive(
              value: config.printBillHere,
              onChanged: (v) => config.setPrintOptions(bill: v),
              title: const Text('Print bills from this phone'),
            ),
            const Divider(height: 1),
            SwitchListTile.adaptive(
              value: config.printFromDevice,
              onChanged: config.setPrintFromDevice,
              title: const Text('Also print orders from other phones'),
              subtitle: Text(printer.running
                  ? 'On · ${printer.printedCount} printed'
                      '${printer.lastError != null ? '\nLast problem: ${printer.lastError}' : ''}'
                  : 'Turn on for the counter phone / tablet connected to the printer, so waiters\' KOTs print here too.'),
            ),
          ]),
          const SectionTitle('Recent print jobs'),
          if (_loading && _jobs.isEmpty) const Center(child: Padding(padding: EdgeInsets.all(24), child: CircularProgressIndicator())),
          if (_error != null) Text(_error!, style: const TextStyle(color: Brand.danger)),
          if (!_loading && _jobs.isEmpty && _error == null)
            const EmptyState(icon: Icons.print_disabled_outlined, title: 'No print jobs today'),
          for (final j in _jobs)
            Card(
              elevation: 0,
              color: Colors.white,
              margin: const EdgeInsets.only(bottom: 8),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14), side: const BorderSide(color: Brand.line)),
              child: ListTile(
                leading: Icon(
                  switch (j.kind) {
                    'kot' => Icons.soup_kitchen_outlined,
                    'bill' => Icons.receipt_long,
                    'drawer' => Icons.point_of_sale,
                    _ => Icons.print_outlined,
                  },
                ),
                title: Text(j.title.isEmpty ? Fmt.titleCase(j.kind) : j.title, style: const TextStyle(fontWeight: FontWeight.w700)),
                subtitle: Text([
                  if (j.createdAt != null) Fmt.time(j.createdAt!),
                  if (j.error.isNotEmpty) j.error,
                ].join(' · ')),
                trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                  Pill(
                    switch (j.status) { 'done' => 'PRINTED', 'failed' => 'FAILED', 'sent' => 'PRINTING', _ => 'WAITING' },
                    color: switch (j.status) {
                      'done' => Brand.success,
                      'failed' => Brand.danger,
                      'sent' => Brand.info,
                      _ => Brand.warning,
                    },
                  ),
                  IconButton(tooltip: 'Print here', icon: const Icon(Icons.print), onPressed: () => _printHere(j)),
                ]),
              ),
            ),
        ]),
      ),
    );
  }
}
