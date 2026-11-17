import 'package:flutter/services.dart';

class ServerCredentials {
  static const _channel = MethodChannel('vietocr/credentials');
  static Future<String> read() async =>
      await _channel.invokeMethod<String>('readServerKey') ?? '';
  static Future<void> write(String value) =>
      _channel.invokeMethod<void>('writeServerKey', {'key': value});
}
