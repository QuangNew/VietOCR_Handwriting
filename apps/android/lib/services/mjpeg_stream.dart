import 'dart:convert';
import 'dart:typed_data';

/// Parses fragmented multipart data without collecting a whole HTTP response.
/// Both header and frame sizes are bounded, including malformed streams.
class MjpegParser {
  MjpegParser(String contentType) {
    final match = RegExp(
      r'boundary=(?:"([^"\r\n]+)"|([^;\s]+))',
      caseSensitive: false,
    ).firstMatch(contentType);
    if (!contentType.toLowerCase().startsWith('multipart/x-mixed-replace') ||
        match == null) {
      throw const FormatException('Stream camera không đúng định dạng MJPEG.');
    }
    final value = match.group(1) ?? match.group(2)!;
    if (value.isEmpty || value.length > 70) {
      throw const FormatException('MJPEG boundary không hợp lệ.');
    }
    _boundary = '--$value';
  }

  static const maxFrame = 8 * 1024 * 1024, maxHeader = 2048;
  late final String _boundary;
  final List<int> _buffer = [];
  int? _wanted;

  Iterable<Uint8List> add(List<int> data) sync* {
    for (var at = 0; at < data.length; at += 8192) {
      _buffer.addAll(data.sublist(at, (at + 8192).clamp(0, data.length)));
      yield* _drain();
    }
  }

  bool _hasEnd(Uint8List frame) {
    for (var i = frame.length - 2; i >= 2; i--) {
      if (frame[i] == 255 && frame[i + 1] == 217) {
        return frame.skip(i + 2).every((b) => b == 0 || b == 255);
      }
      if (frame.length - i > 65538) return false;
    }
    return false;
  }

  Iterable<Uint8List> _drain() sync* {
    while (true) {
      if (_wanted == null) {
        while (_buffer.length >= 2 && _buffer[0] == 13 && _buffer[1] == 10) {
          _buffer.removeRange(0, 2);
        }
        var end = -1;
        for (var i = 0; i + 3 < _buffer.length; ++i) {
          if (_buffer[i] == 13 &&
              _buffer[i + 1] == 10 &&
              _buffer[i + 2] == 13 &&
              _buffer[i + 3] == 10) {
            end = i;
            break;
          }
        }
        if (end < 0) {
          if (_buffer.length > maxHeader) {
            throw const FormatException('MJPEG header quá dài.');
          }
          return;
        }
        if (end > maxHeader) {
          throw const FormatException('MJPEG header quá dài.');
        }
        final lines = ascii
            .decode(_buffer.sublist(0, end))
            .trimLeft()
            .split('\r\n');
        _buffer.removeRange(0, end + 4);
        if (lines.first != _boundary) {
          throw const FormatException('MJPEG boundary bị lỗi.');
        }
        final headers = <String, String>{};
        for (final line in lines.skip(1)) {
          final colon = line.indexOf(':');
          if (colon < 1) throw const FormatException('MJPEG header bị lỗi.');
          final name = line.substring(0, colon).trim().toLowerCase();
          if (headers.containsKey(name)) {
            throw const FormatException('MJPEG header bị trùng.');
          }
          headers[name] = line.substring(colon + 1).trim().toLowerCase();
        }
        final length = headers['content-length'] ?? '';
        if (!RegExp(r'^\d{1,9}$').hasMatch(length) ||
            headers['content-type'] != 'image/jpeg') {
          throw const FormatException('MJPEG thiếu kích thước JPEG hợp lệ.');
        }
        _wanted = int.parse(length);
        if (_wanted! < 4 || _wanted! > maxFrame) {
          throw const FormatException('Khung hình xem trước quá lớn.');
        }
      }
      final size = _wanted!;
      if (_buffer.length < size) return;
      final frame = Uint8List.fromList(_buffer.sublist(0, size));
      _buffer.removeRange(0, size);
      _wanted = null;
      if (frame[0] != 255 || frame[1] != 216 || !_hasEnd(frame)) {
        throw const FormatException('Khung hình xem trước sai JPEG.');
      }
      yield frame;
    }
  }
}
