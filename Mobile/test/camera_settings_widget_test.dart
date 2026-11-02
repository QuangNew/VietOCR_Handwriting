import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vietocr_mobile/services/ble_assistant.dart';
import 'package:vietocr_mobile/services/camera_settings.dart';
import 'package:vietocr_mobile/ui/camera_settings_sheet.dart';
import 'camera_settings_test.dart' as fixture;
import 'ble_connection_test.dart' show FakeRadio;

class SettingsAssistant extends BleAssistant {
  SettingsAssistant() : super(radioClient: FakeRadio()) {
    connected = true;
  }
  CameraConfig profile = CameraConfig.parse(fixture.response());
  bool fail = false;
  int writes = 0;
  @override
  Future<CameraConfig> readCameraConfig() async {
    if (fail) throw StateError('Cần firmware camera 3.0.0-ov5640');
    return profile;
  }

  @override
  Future<CameraConfig> configureCamera(
    Map<String, int> settings, {
    bool persist = true,
  }) async {
    ++writes;
    profile = CameraConfig.parse(
      fixture.response(settings: settings, saved: persist),
    );
    return profile;
  }
}

void main() {
  testWidgets(
    'camera presets and apply fit small dark screens with large text',
    (tester) async {
      tester.view.physicalSize = const Size(360, 760);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final ble = SettingsAssistant();
      addTearDown(ble.dispose);
      await tester.pumpWidget(
        MaterialApp(
          theme: ThemeData.dark(useMaterial3: true),
          builder: (context, child) => MediaQuery(
            data: MediaQuery.of(
              context,
            ).copyWith(textScaler: TextScaler.linear(1.6)),
            child: child!,
          ),
          home: Scaffold(body: CameraSettingsSheet(ble: ble)),
        ),
      );
      await tester.pumpAndSettle();
      final smooth = find.widgetWithText(ActionChip, 'Mượt');
      await tester.ensureVisible(smooth);
      await tester.tap(smooth);
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Áp dụng'));
      await tester.pumpAndSettle();
      expect(ble.writes, 1);
      expect(ble.profile.settings['preview_width'], 640);
      expect(ble.profile.settings['still_quality'], 8);
      expect(ble.profile.saved, isTrue);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets('unsupported firmware is visible and reload can recover', (
    tester,
  ) async {
    final ble = SettingsAssistant()..fail = true;
    addTearDown(ble.dispose);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: CameraSettingsSheet(ble: ble)),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.textContaining('3.0.0-ov5640'), findsOneWidget);
    expect(ble.writes, 0);
    ble.fail = false;
    await tester.tap(find.widgetWithText(OutlinedButton, 'Tải lại'));
    await tester.pumpAndSettle();
    expect(find.text('Đã đọc cấu hình lưu trên ESP32.'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
