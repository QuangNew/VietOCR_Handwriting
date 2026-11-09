import 'dart:typed_data';
import 'package:image/image.dart' as img;
import 'image_processing.dart';

/// Explicit optional derivative. Original profile is the default; no resize.
({Uint8List bytes, String extension, bool lossless})? optimizeTransfer(
  (Uint8List, int) job,
) {
  var image = decodePhoto(job.$1);
  if (image.iccProfile != null) {
    return null; // Keep the colour-managed source intact.
  }
  if (job.$2 % 4 != 0) image = img.copyRotate(image, angle: (job.$2 % 4) * 90);
  if (image.hasAlpha) {
    final white = img.Image(
      width: image.width,
      height: image.height,
      numChannels: 3,
    )..clear(img.ColorRgb8(255, 255, 255));
    image = img.compositeImage(white, image);
  }
  image.exif = img.ExifData();
  image.iccProfile = null;
  image.textData?.clear();
  final png = img.encodePng(image, level: 6),
      jpeg = img.encodeJpg(image, quality: 95, chroma: img.JpegChroma.yuv444);
  final lossless = png.length <= jpeg.length;
  final bytes = lossless ? png : jpeg;
  if (bytes.length + 1024 >= job.$1.length) return null;
  return (
    bytes: Uint8List.fromList(bytes),
    extension: lossless ? 'png' : 'jpg',
    lossless: lossless,
  );
}
