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

class PrintersScreen extends StatefulWidget {
  const PrintersScreen({super.key});

  @override
  State<PrintersScreen> createState() => _PrintersScreenState();
}

class _PrintersScreenState extends State<PrintersScreen> {
  List<PrintJob> _jobs = [];
  bool _loading = true;
  String? _error;
  late final TextEditingController _lan;

  @override
  void initState() {
    super.initState();
    _lan = TextEditingController(text: context.read<AppConfig>().fallbackLanPrinter);
    _load();
  }

  @override
  void dispose() {
    _lan.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final api = context.read<ApiClient>();
    setState(() => _loading = true);
    try {
      final rows = listOf(await api.get('/print-jobs'));
      if (mounted) {
        setState(() {
          _jobs = rows.map((e) => PrintJob.fromJson(asMap(e))).toList();
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = errorText(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _pickBluetooth() async {
    final config = context.read<AppConfig>();
    List<BluetoothInfo> devices;
    try {
      devices = await PrintBluetoothThermal.pairedBluetooths;
    } catch (e) {
      if (mounted) toast(context, 'Bluetooth unavailable: $e', error: true);
      return;
    }
    if (!mounted) return;
    final picked = await showSheet<BluetoothInfo>(
      context,
      (ctx) => SheetFrame(
        title: 'Paired printers',
        child: ListView(shrinkWrap: true, padding: const EdgeInsets.only(bottom: 16), children: [
          if (devices.isEmpty)
            const ListTile(
              leading: Icon(Icons.bluetooth_disabled),
              title: Text('No paired devices'),
              subtitle: Text('Pair the printer in Android Bluetooth settings first (PIN is often 0000 or 1234).'),
            ),
          for (final d in devices)
            ListTile(
              leading: const Icon(Icons.print),
              title: Text(d.name),
              subtitle: Text(d.macAdress),
              onTap: () => Navigator.pop(ctx, d),
            ),
        ]),
      ),
    );
    if (picked != null) await config.setBluetoothPrinter(picked.macAdress, picked.name);
  }

  Future<void> _test() async {
    final printer = context.read<PrintService>();
    await context.read<AppConfig>().setFallbackLanPrinter(_lan.text);
    try {
      await printer.testPrint();
      if (mounted) toast(context, 'Test page sent');
    } catch (e) {
      if (mounted) toast(context, 'Print failed: $e', error: true);
    }
  }

  Future<void> _printHere(PrintJob job) async {
    final printer = context.read<PrintService>();
    try {
      await printer.printAndAck(job);
      await _load();
      if (mounted) toast(context, printer.lastError ?? 'Printed');
    } catch (e) {
      if (mounted) toast(context, errorText(e), error: true);
    }
  }

  Future<void> _retry(PrintJob job) async {
    try {
      await context.read<ApiClient>().post('/print-jobs/${job.id}/retry', {});
      await _load();
    } catch (e) {
      if (mounted) toast(context, errorText(e), error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final config = context.watch<AppConfig>();
    final printer = context.watch<PrintService>();
    return Scaffold(
      appBar: AppBar(title: const Text('Printers'), actions: [IconButton(onPressed: _load, icon: const Icon(Icons.refresh))]),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(padding: const EdgeInsets.all(16), children: [
          Container(
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(18),
              border: Border.all(color: Brand.line),
            ),
            child: Column(children: [
              SwitchListTile.adaptive(
                value: config.printFromDevice,
                onChanged: config.setPrintFromDevice,
                title: const Text('Print from this device', style: TextStyle(fontWeight: FontWeight.w800)),
                subtitle: Text(printer.running
                    ? 'Polling every few seconds · ${printer.printedCount} printed'
                        '${printer.lastError != null ? '\nLast error: ${printer.lastError}' : ''}'
                    : 'Send KOTs and bills from Servora to LAN / Bluetooth printers via this phone or tablet.'),
              ),
              const Divider(height: 1),
              ListTile(
                leading: const Icon(Icons.bluetooth),
                title: const Text('Bluetooth printer'),
                subtitle: Text(config.btPrinterMac.isEmpty ? 'Not selected' : '${config.btPrinterName} (${config.btPrinterMac})'),
                trailing: config.btPrinterMac.isEmpty
                    ? const Icon(Icons.chevron_right)
                    : IconButton(
                        tooltip: 'Forget',
                        icon: const Icon(Icons.close),
                        onPressed: () => config.setBluetoothPrinter('', ''),
                      ),
                onTap: _pickBluetooth,
              ),
              const Divider(height: 1),
              Padding(
                padding: const EdgeInsets.all(16),
                child: TextField(
                  controller: _lan,
                  keyboardType: TextInputType.url,
                  onSubmitted: config.setFallbackLanPrinter,
                  decoration: const InputDecoration(
                    labelText: 'Default LAN printer (ip:port)',
                    hintText: '192.168.1.50:9100',
                    helperText: 'Used for jobs whose device has no address. Network devices use their own IP.',
                    prefixIcon: Icon(Icons.lan_outlined),
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                child: OutlinedButton.icon(onPressed: _test, icon: const Icon(Icons.print_outlined), label: const Text('Print test page')),
              ),
            ]),
          ),
          const SectionTitle('Recent print jobs'),
          if (_loading && _jobs.isEmpty) const Center(child: Padding(padding: EdgeInsets.all(24), child: CircularProgressIndicator())),
          if (_error != null) Text(_error!, style: const TextStyle(color: Brand.danger)),
          if (!_loading && _jobs.isEmpty && _error == null)
            const EmptyState(icon: Icons.print_disabled_outlined, title: 'No print jobs yet'),
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
                  j.deviceName ?? 'No printer routed',
                  if (j.connection != null) Fmt.titleCase(j.connection!),
                  Fmt.time(j.createdAt),
                  if (j.error.isNotEmpty) j.error,
                ].join(' · ')),
                trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                  Pill(
                    j.status.toUpperCase(),
                    color: switch (j.status) {
                      'done' => Brand.success,
                      'failed' => Brand.danger,
                      'sent' => Brand.info,
                      _ => Brand.warning,
                    },
                  ),
                  PopupMenuButton<String>(
                    onSelected: (v) => v == 'here' ? _printHere(j) : _retry(j),
                    itemBuilder: (_) => const [
                      PopupMenuItem(value: 'here', child: Text('Print on this device')),
                      PopupMenuItem(value: 'retry', child: Text('Re-queue')),
                    ],
                  ),
                ]),
                onTap: () => showDialog<void>(
                  context: context,
                  builder: (ctx) => AlertDialog(
                    title: Text(j.title.isEmpty ? 'Preview' : j.title),
                    content: SingleChildScrollView(
                      child: Text(j.text, style: const TextStyle(fontFamily: 'monospace', fontSize: 13)),
                    ),
                    actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Close'))],
                  ),
                ),
              ),
            ),
        ]),
      ),
    );
  }
}
