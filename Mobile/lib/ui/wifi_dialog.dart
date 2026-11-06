import 'package:flutter/material.dart';
import 'dart:async';
import '../services/ble_assistant.dart';
import '../services/wifi_camera.dart' show SavedWifiProfile;

class WifiDialog extends StatefulWidget {
  const WifiDialog({super.key, required this.assistant});
  final BleAssistant assistant;
  @override
  State<WifiDialog> createState() => _WifiDialogState();
}

class _WifiDialogState extends State<WifiDialog> {
  final ssid = TextEditingController(), password = TextEditingController();
  List<String> networks = [];
  bool busy = false;
  bool nameEdited = false;
  List<SavedWifiProfile>? saved;
  bool showPasswords = false;
  String message = 'Chọn Wi-Fi 2.4 GHz. Điện thoại và ESP32 cần cùng mạng LAN.';
  @override
  void initState() {
    super.initState();
    widget.assistant.addListener(_updated);
    _fillSavedName();
    unawaited(widget.assistant.refreshWifiState());
  }

  void _fillSavedName() {
    final state = widget.assistant.wifiState;
    if (!nameEdited && ssid.text.isEmpty && state != null) {
      ssid.text = state.ssid.isEmpty ? state.savedSsid : state.ssid;
    }
  }

  void _updated() {
    if (!mounted) return;
    setState(_fillSavedName);
  }

  Future<void> run(Future<String> Function() operation) async {
    if (busy) return;
    setState(() {
      busy = true;
      message = 'Đang xử lý…';
    });
    try {
      final value = await operation();
      if (mounted) setState(() => message = value);
    } catch (error) {
      if (mounted) setState(() => message = '$error');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  void dispose() {
    widget.assistant.removeListener(_updated);
    ssid.dispose();
    password.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Wi-Fi camera'),
    content: SingleChildScrollView(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            widget.assistant.wifiMessage,
            style: const TextStyle(fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 8),
          Text(
            widget.assistant.wifiState?.detail ??
                'Đang đọc mạng đã lưu trên ESP32…',
          ),
          const SizedBox(height: 8),
          const Text(
            'Trạng thái tự cập nhật mỗi 3 giây. Quét mạng chỉ khi cần đổi Wi-Fi.',
          ),
          const SizedBox(height: 12),
          Text(message),
          const SizedBox(height: 16),
          if (networks.isNotEmpty)
            DropdownButtonFormField<String>(
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Mạng tìm thấy'),
              items: networks
                  .map(
                    (name) => DropdownMenuItem(
                      value: name,
                      child: Text(name, overflow: TextOverflow.ellipsis),
                    ),
                  )
                  .toList(),
              onChanged: busy
                  ? null
                  : (name) {
                      if (name != null) {
                        nameEdited = true;
                        ssid.text = name;
                      }
                    },
            ),
          const SizedBox(height: 12),
          TextField(
            controller: ssid,
            onChanged: (_) => nameEdited = true,
            enabled: !busy,
            decoration: const InputDecoration(
              labelText: 'Tên Wi-Fi (có thể nhập mạng ẩn)',
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: password,
            enabled: !busy,
            obscureText: true,
            autocorrect: false,
            enableSuggestions: false,
            decoration: const InputDecoration(
              labelText: 'Mật khẩu',
              helperText: 'Được lưu trên ESP32; để trống với mạng mở.',
            ),
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: busy
                ? null
                : () => run(() async {
                    final profiles = await widget.assistant.readWifiProfiles();
                    if (mounted) setState(() => saved = profiles);
                    return 'Đã đọc ${profiles.length} mạng lưu trên flash ESP32.';
                  }),
            icon: const Icon(Icons.router_outlined),
            label: const Text('Mạng đã lưu trên ESP32'),
          ),
          if (saved != null) ...[
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Hiện mật khẩu'),
              value: showPasswords,
              onChanged: (v) => setState(() => showPasswords = v),
            ),
            for (final profile in saved!)
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: Text(profile.ssid),
                subtitle: SelectableText(
                  showPasswords
                      ? (profile.password.isEmpty
                            ? 'Mạng mở'
                            : profile.password)
                      : '••••••••',
                ),
                trailing: const Icon(Icons.arrow_outward),
                onTap: () {
                  ssid.text = profile.ssid;
                  password.text = profile.password;
                  nameEdited = true;
                },
              ),
          ],
          if (busy)
            const Padding(
              padding: EdgeInsets.only(top: 12),
              child: LinearProgressIndicator(),
            ),
        ],
      ),
    ),
    actions: [
      TextButton(
        onPressed: busy
            ? null
            : () => run(() async {
                final rows = await widget.assistant.scanWifi();
                if (mounted) setState(() => networks = rows);
                return 'Tìm thấy ${rows.length} mạng. Chọn hoặc nhập tên Wi-Fi.';
              }),
        child: const Text('Quét mạng'),
      ),
      FilledButton(
        onPressed: busy
            ? null
            : () => run(() async {
                final secret = password.text;
                password.clear();
                return widget.assistant.configureWifi(ssid.text, secret);
              }),
        child: const Text('Kết nối'),
      ),
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('Đóng'),
      ),
    ],
  );
}
