import 'dart:convert';
import 'dart:io';
import '../clients/dart/vietocr_remote.dart';

Future<void> main() async {
  final config = jsonDecode(await utf8.decoder.bind(stdin).join()) as Map<String, dynamic>;
  final client = VietOcrRemote(config['origin'] as String, config['key'] as String);
  try {
    final text = await client.recognize(File(config['image'] as String), layout: 'line');
    stdout.write(jsonEncode({'text': text})); // Parent compares in memory, never logs document text.
  } finally { client.close(); }
}
