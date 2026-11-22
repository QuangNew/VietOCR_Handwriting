import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../domain/app_controller.dart';
import 'document_page.dart';
import 'log_page.dart';

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key, required this.app});
  final AppController app;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  AppController get app => widget.app;
  bool loading = false;

  Future<void> _run(Future<void> Function() task) async {
    if (loading) return;
    setState(() => loading = true);
    try {
      await task();
    } catch (error) {
      if (mounted) showNotice(context, AppController.readableError(error));
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _account() async {
    final owner = app.cloud.userId;
    final remote = app.gateway();
    Map<String, dynamic> account;
    try {
      account = await remote.account();
    } finally {
      remote.close();
    }
    if (!mounted || owner != app.cloud.userId) return;
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text('Hạn mức', style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 14),
              Text(
                'Hôm nay · ${account['usedToday'] ?? 0}/${account['dailyLimit']} ảnh',
              ),
              Text(
                'Trong 60 giây · ${account['usedLastMinute'] ?? 0}/${account['ratePerMinute']} ảnh',
              ),
              const SizedBox(height: 12),
              const Text('Hạn mức ngày đặt lại lúc 00:00 giờ Việt Nam.'),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _connection() => showDialog<void>(
    context: context,
    builder: (_) => _ConnectionDialog(app: app),
  );

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: app,
    builder: (context, _) {
      final signedIn = app.accountEmail != null;
      return Scaffold(
        appBar: AppBar(title: const Text('Cài đặt')),
        body: SafeArea(
          top: false,
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Text('Tài khoản', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              Card(
                child: Column(
                  children: [
                    ListTile(
                      leading: const Icon(Icons.person_outline),
                      title: Text(app.accountEmail ?? 'Chưa đăng nhập'),
                      subtitle: const Text('Tài khoản Google'),
                    ),
                    if (signedIn) ...[
                      ListTile(
                        leading: const Icon(Icons.speed),
                        title: const Text('Hạn mức'),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: loading ? null : () => _run(_account),
                      ),
                      ListTile(
                        leading: const Icon(Icons.logout),
                        title: const Text('Đăng xuất'),
                        onTap: loading ? null : () => _run(app.cloud.logout),
                      ),
                    ] else
                      ListTile(
                        leading: const Icon(Icons.login),
                        title: const Text('Đăng nhập Google'),
                        onTap: loading ? null : () => _run(app.cloud.login),
                      ),
                  ],
                ),
              ),
              const SizedBox(height: 20),
              Text(
                'Kết nối và ứng dụng',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 8),
              Card(
                child: Column(
                  children: [
                    ListTile(
                      leading: const Icon(Icons.router_outlined),
                      title: const Text('Raspberry'),
                      subtitle: Text(
                        app.serverUrl,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: app.busy || app.importing || app.checkingConnection
                          ? null
                          : _connection,
                    ),
                    SwitchListTile.adaptive(
                      title: const Text('Giao diện tối'),
                      secondary: const Icon(Icons.dark_mode_outlined),
                      value: app.dark,
                      onChanged: (_) => app.toggleTheme(),
                    ),
                    ListTile(
                      leading: const Icon(Icons.history),
                      title: const Text('Lịch sử trên máy chủ'),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: !app.gatewayVerified
                          ? null
                          : () => Navigator.of(context).push<void>(
                              MaterialPageRoute(
                                builder: (_) => _HistoryPage(app: app),
                              ),
                            ),
                    ),
                    ListTile(
                      leading: const Icon(Icons.list_alt_outlined),
                      title: const Text('Nhật ký chẩn đoán'),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => Navigator.of(context).push<void>(
                        MaterialPageRoute(
                          builder: (_) => Scaffold(
                            appBar: AppBar(title: const Text('Nhật ký')),
                            body: const LogPage(),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              if (loading)
                const Padding(
                  padding: EdgeInsets.only(top: 12),
                  child: LinearProgressIndicator(),
                ),
            ],
          ),
        ),
      );
    },
  );
}

class _ConnectionDialog extends StatefulWidget {
  const _ConnectionDialog({required this.app});
  final AppController app;

  @override
  State<_ConnectionDialog> createState() => _ConnectionDialogState();
}

class _ConnectionDialogState extends State<_ConnectionDialog> {
  late final origin = TextEditingController(text: widget.app.serverUrl);
  late bool insecure = widget.app.serverInsecureLan;
  bool saving = false;
  String? error;

  @override
  void dispose() {
    origin.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    setState(() {
      saving = true;
      error = null;
    });
    try {
      await widget.app.configureServer(
        origin: origin.text.trim(),
        allowInsecureLan: insecure,
      );
      if (mounted) Navigator.pop(context);
    } catch (failure) {
      if (mounted) setState(() => error = AppController.readableError(failure));
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Kết nối Raspberry'),
    scrollable: true,
    content: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        TextField(
          controller: origin,
          enabled: !saving,
          keyboardType: TextInputType.url,
          autocorrect: false,
          onChanged: (_) => setState(() {}),
          decoration: const InputDecoration(
            labelText: 'Địa chỉ Raspberry',
            hintText: 'https://api.quangnew.tech',
          ),
        ),
        if (insecure || origin.text.startsWith('http://'))
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Cho phép HTTP trong mạng nội bộ'),
            value: insecure,
            onChanged: saving
                ? null
                : (value) => setState(() => insecure = value ?? false),
          ),
        if (error != null)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Text(
              error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ),
        if (saving)
          const Padding(
            padding: EdgeInsets.only(top: 12),
            child: LinearProgressIndicator(),
          ),
      ],
    ),
    actions: [
      TextButton(
        onPressed: saving ? null : () => Navigator.pop(context),
        child: const Text('Đóng'),
      ),
      FilledButton(
        onPressed: saving ? null : _save,
        child: const Text('Lưu và kết nối'),
      ),
    ],
  );
}

class _HistoryPage extends StatefulWidget {
  const _HistoryPage({required this.app});
  final AppController app;

  @override
  State<_HistoryPage> createState() => _HistoryPageState();
}

class _HistoryPageState extends State<_HistoryPage> {
  late final owner = widget.app.cloud.userId;
  late final remote = widget.app.gateway();
  late Future<List<Map<String, dynamic>>> history = remote.history();
  bool loading = false;

  @override
  void dispose() {
    remote.close();
    super.dispose();
  }

  Future<void> _open(String id) async {
    if (loading) return;
    setState(() => loading = true);
    try {
      final row = await remote.get(id);
      if (!mounted || owner != widget.app.cloud.userId) return;
      final text = row['text']?.toString() ?? '';
      await showDialog<void>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Kết quả nhận diện'),
          scrollable: true,
          content: SelectableText(
            text.isEmpty
                ? (row['error']?.toString() ?? _status(row['state']))
                : text,
          ),
          actions: [
            if (text.isNotEmpty)
              TextButton(
                onPressed: () => Clipboard.setData(ClipboardData(text: text)),
                child: const Text('Sao chép'),
              ),
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Đóng'),
            ),
          ],
        ),
      );
    } catch (error) {
      if (mounted) showNotice(context, AppController.readableError(error));
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  String _status(Object? value) => switch (value) {
    'succeeded' => 'Đã có văn bản',
    'failed' => 'Không đọc được ảnh',
    'cancelled' => 'Đã hủy',
    'running' => 'Đang đọc',
    'queued' => 'Đang chờ xử lý',
    _ => 'Chưa gửi xong',
  };

  String _date(Object? value) {
    final date = DateTime.tryParse(value?.toString() ?? '')?.toLocal();
    if (date == null) return 'Lượt nhận diện';
    return '${MaterialLocalizations.of(context).formatShortDate(date)} · ${MaterialLocalizations.of(context).formatTimeOfDay(TimeOfDay.fromDateTime(date))}';
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Lịch sử trên máy chủ')),
    body: ListenableBuilder(
      listenable: widget.app.cloud,
      builder: (context, _) => owner != widget.app.cloud.userId
          ? const Center(child: Text('Phiên tài khoản đã thay đổi.'))
          : FutureBuilder<List<Map<String, dynamic>>>(
              future: history,
              builder: (context, snapshot) {
                if (snapshot.connectionState != ConnectionState.done) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (snapshot.hasError) {
                  return Center(
                    child: TextButton(
                      onPressed: () =>
                          setState(() => history = remote.history()),
                      child: const Text('Tải lại lịch sử'),
                    ),
                  );
                }
                final rows = snapshot.data ?? [];
                if (rows.isEmpty) {
                  return const Center(child: Text('Chưa có lượt nhận diện.'));
                }
                return Column(
                  children: [
                    if (loading) const LinearProgressIndicator(),
                    Expanded(
                      child: ListView.builder(
                        itemCount: rows.length,
                        itemBuilder: (context, index) {
                          final row = rows[index];
                          return ListTile(
                            leading: const Icon(Icons.description_outlined),
                            title: Text(_status(row['state'])),
                            subtitle: Text(
                              _date(row['created_at'] ?? row['createdAt']),
                            ),
                            trailing: const Icon(Icons.chevron_right),
                            onTap: row['id'] is String && !loading
                                ? () => unawaited(_open(row['id'] as String))
                                : null,
                          );
                        },
                      ),
                    ),
                  ],
                );
              },
            ),
    ),
  );
}
