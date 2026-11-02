import 'package:flutter/material.dart';
import '../services/ble_assistant.dart';
import '../services/camera_settings.dart';

class CameraSettingsSheet extends StatefulWidget {
  const CameraSettingsSheet({super.key, required this.ble});
  final BleAssistant ble;
  @override
  State<CameraSettingsSheet> createState() => _CameraSettingsSheetState();
}

class _CameraSettingsSheetState extends State<CameraSettingsSheet> {
  Map<String, int>? values;
  Map<String, int> defaults = Map.of(cameraDefaults);
  bool busy = true, persist = true;
  String message = 'Đang đọc cấu hình trên ESP32…';
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => load());
  }

  Future<void> load() async {
    setState(() => busy = true);
    try {
      final config = await widget.ble.readCameraConfig();
      if (!mounted) return;
      setState(() {
        values = Map.of(config.settings);
        defaults = Map.of(config.defaults);
        message = config.saved
            ? 'Đã đọc cấu hình lưu trên ESP32.'
            : 'Đã đọc cấu hình đang dùng trên ESP32.';
      });
    } catch (error) {
      if (mounted) setState(() => message = error.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> apply() async {
    if (values == null || busy) return;
    setState(() {
      busy = true;
      message = 'Đang áp dụng trên camera…';
    });
    try {
      final config = await widget.ble.configureCamera(
        Map.of(values!),
        persist: persist,
      );
      if (!mounted) return;
      setState(() {
        values = Map.of(config.settings);
        message = config.saved
            ? 'Đã áp dụng và lưu trên ESP32.'
            : 'Đã áp dụng cho phiên hiện tại.';
      });
    } catch (error) {
      if (mounted) setState(() => message = error.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  bool enabled(String key) =>
      !busy &&
      values != null &&
      (key != 'aec_value' || values!['aec'] == 0) &&
      (key != 'ae_level' || values!['aec'] == 1) &&
      (key != 'agc_gain' || values!['agc'] == 0);
  Widget field(String key, CameraField field) {
    final value = values?[key] ?? field.initial, active = enabled(key);
    if (field.choices != null) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: DropdownButtonFormField<int>(
          key: ValueKey('$key-$value'),
          initialValue: value,
          isExpanded: true,
          decoration: InputDecoration(
            labelText: field.label,
            border: const OutlineInputBorder(),
          ),
          items: [
            for (final item in field.choices!.entries)
              DropdownMenuItem(
                value: item.key,
                child: Text(item.value, overflow: TextOverflow.ellipsis),
              ),
          ],
          onChanged: active ? (v) => setState(() => values![key] = v!) : null,
        ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '${field.label}: $value',
          style: TextStyle(
            color: active ? null : Theme.of(context).disabledColor,
          ),
        ),
        Slider(
          value: value.toDouble(),
          min: field.min.toDouble(),
          max: field.max.toDouble(),
          divisions: field.max - field.min,
          label: '$value',
          onChanged: active
              ? (v) => setState(() => values![key] = v.round())
              : null,
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) => SafeArea(
    child: SizedBox(
      height: MediaQuery.sizeOf(context).height * .93,
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 8, 0),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    'Cấu hình camera',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                ),
                IconButton(
                  onPressed: busy ? null : () => Navigator.pop(context),
                  icon: const Icon(Icons.close),
                  tooltip: 'Đóng',
                ),
              ],
            ),
          ),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Ảnh chụp luôn 5 MP. Preview nhẹ hơn giúp căn hình nhanh. QS thấp = nét hơn, ảnh nặng hơn.',
                  ),
                  ExpansionTile(
                    title: const Text('Xem camera'),
                    children: [
                      ListenableBuilder(
                        listenable: widget.ble,
                        builder: (context, _) {
                          final bytes = widget.ble.previewBytes;
                          return SizedBox(
                            height: 180,
                            child: bytes == null
                                ? const Center(
                                    child: Text('Mở preview để xem thay đổi.'),
                                  )
                                : Image.memory(
                                    bytes,
                                    fit: BoxFit.contain,
                                    gaplessPlayback: true,
                                    errorBuilder: (_, _, _) =>
                                        const Text('Không đọc được preview.'),
                                  ),
                          );
                        },
                      ),
                    ],
                  ),
                  Wrap(
                    spacing: 8,
                    runSpacing: 4,
                    children: [
                      for (final preset in cameraPresets.entries)
                        ActionChip(
                          label: Text(preset.key),
                          onPressed: values != null && !busy
                              ? () => setState(() {
                                  values!.addAll(preset.value);
                                  message =
                                      'Đã chọn ${preset.key}. Bấm Áp dụng.';
                                })
                              : null,
                        ),
                    ],
                  ),
                  for (final group
                      in cameraFields.values.map((f) => f.group).toSet())
                    ExpansionTile(
                      title: Text(group),
                      initiallyExpanded: group == 'Luồng ảnh',
                      children: [
                        for (final entry in cameraFields.entries.where(
                          (entry) => entry.value.group == group,
                        ))
                          field(entry.key, entry.value),
                      ],
                    ),
                  const SizedBox(height: 12),
                ],
              ),
            ),
          ),
          if (busy) const LinearProgressIndicator(),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
            child: Align(alignment: Alignment.centerLeft, child: Text(message)),
          ),
          SwitchListTile(
            title: const Text('Nhớ cấu hình trên ESP32'),
            subtitle: const Text('Giữ sau khi mất điện'),
            value: persist,
            onChanged: busy ? null : (value) => setState(() => persist = value),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
            child: Wrap(
              spacing: 8,
              runSpacing: 6,
              children: [
                OutlinedButton(
                  onPressed: busy ? null : load,
                  child: const Text('Tải lại'),
                ),
                OutlinedButton(
                  onPressed: busy || values == null
                      ? null
                      : () => setState(() {
                          values = Map.of(defaults);
                          message = 'Đã chọn mặc định. Bấm Áp dụng.';
                        }),
                  child: const Text('Mặc định'),
                ),
                FilledButton(
                  onPressed: busy || values == null ? null : apply,
                  child: const Text('Áp dụng'),
                ),
              ],
            ),
          ),
        ],
      ),
    ),
  );
}
