import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../brand/theme.dart';
import '../core/api_client.dart';
import '../core/offline_queue.dart';

/// "Offline – N pending" strip shown at the top of working screens.
class OfflineBanner extends StatelessWidget {
  const OfflineBanner({super.key});

  @override
  Widget build(BuildContext context) {
    final api = Provider.of<ApiClient>(context, listen: false);
    final queue = context.watch<OfflineQueue>();
    return ValueListenableBuilder<bool>(
      valueListenable: api.online,
      builder: (context, online, _) {
        if (online && queue.pending == 0) return const SizedBox.shrink();
        final color = online ? Brand.warning : Brand.danger;
        final text = online
            ? '${queue.pending} offline order${queue.pending == 1 ? '' : 's'} waiting to sync'
            : 'Offline${queue.pending > 0 ? ' – ${queue.pending} pending' : ''} · orders are saved on this device';
        return Material(
          color: color,
          child: SafeArea(
            bottom: false,
            top: false,
            child: InkWell(
              onTap: () => _showQueue(context),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                child: Row(children: [
                  Icon(online ? Icons.cloud_upload_outlined : Icons.cloud_off, color: Colors.white, size: 20),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(text, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700)),
                  ),
                  if (queue.syncing)
                    const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                  else
                    TextButton(
                      onPressed: queue.sync,
                      style: TextButton.styleFrom(foregroundColor: Colors.white),
                      child: const Text('SYNC NOW'),
                    ),
                ]),
              ),
            ),
          ),
        );
      },
    );
  }

  void _showQueue(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      builder: (ctx) => Consumer<OfflineQueue>(
        builder: (ctx, q, _) => SafeArea(
          child: ListView(
            shrinkWrap: true,
            padding: const EdgeInsets.all(16),
            children: [
              const Text('Offline orders', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
              const SizedBox(height: 8),
              if (q.items.isEmpty) const Text('All orders are synced.'),
              for (final p in q.items)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(p.error == null ? Icons.schedule : Icons.error_outline,
                      color: p.error == null ? Brand.warning : Brand.danger),
                  title: Text(p.label),
                  subtitle: Text(p.error ?? 'Saved ${TimeOfDay.fromDateTime(p.createdAt).format(ctx)} · waiting'),
                  trailing: p.error == null
                      ? null
                      : IconButton(
                          tooltip: 'Discard',
                          icon: const Icon(Icons.delete_outline),
                          onPressed: () => q.discard(p),
                        ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
