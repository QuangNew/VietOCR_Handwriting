"""Bounded, pull-based JPEG transfer; shared contract with Android and firmware."""
import asyncio
import logging
import secrets
import struct
import time
import zlib
from dataclasses import dataclass

IMAGE_UUID = "6e400004-b5a3-f393-e0a9-e50e24dcca9e"
MAX_BYTES = 2 * 1024 * 1024
LOGGER = logging.getLogger("vietocr_desktop.camera")


@dataclass(frozen=True)
class CameraMetadata:
    id: int
    size: int
    crc: int
    width: int
    height: int

    @classmethod
    def parse(cls, line, expected_id):
        parts = line.split()
        if len(parts) != 6 or parts[0] != "CAM":
            raise ValueError("Sai metadata camera.")
        result = cls(int(parts[1]), int(parts[2]), int(parts[3], 16), int(parts[4]), int(parts[5]))
        if (result.id != expected_id or not 4 <= result.size <= MAX_BYTES or
                not 0 <= result.crc <= 0xffffffff or not 1 <= result.width <= 4096 or
                not 1 <= result.height <= 4096 or result.width * result.height > 8_000_000):
            raise ValueError("Metadata camera vượt giới hạn hoặc sai ID ảnh.")
        return result


def verify_jpeg(data, metadata):
    if len(data) != metadata.size or zlib.crc32(data) != metadata.crc:
        raise ValueError("Ảnh BLE thiếu dữ liệu hoặc sai CRC32; ảnh chưa được đưa vào OCR.")
    if not data.startswith(b'\xff\xd8') or not data.endswith(b'\xff\xd9'):
        raise ValueError("Camera không trả ảnh JPEG hoàn chỉnh.")


async def capture_image(protocol, on_progress=None):
    received = total = 0

    def progress(done, size):
        nonlocal received, total
        received, total = done, size
        if on_progress:
            on_progress(done, size)

    try:
        return await _capture_image(protocol, on_progress=progress)
    except TimeoutError:
        detail = f"Đã nhận {received:,}/{total:,} byte." if total else "Chưa nhận được metadata JPEG."
        raise TimeoutError(f"Camera/Bluetooth không phản hồi đúng hạn. {detail} Xem log MTU và tiến độ nhận ảnh.") from None


async def _capture_image(protocol, on_progress):
    from .bluetooth_transport import RobotCommandRejected
    frame_id = secrets.randbelow(0xffffffff) + 1
    cancelled = False
    async with asyncio.timeout(240):
        await protocol.request(f"CAM SHOT {frame_id}", timeout=5)
        try:
            deadline = time.monotonic() + 25
            while True:
                try:
                    line = await protocol.request(f"CAM META {frame_id}", expected_prefix=f"CAM {frame_id} ")
                    metadata = CameraMetadata.parse(line, frame_id)
                    break
                except RobotCommandRejected as error:
                    if error.code != 'CAMERA_BUSY' or time.monotonic() >= deadline:
                        raise
                    await asyncio.sleep(.15)
            mtu = getattr(protocol.client, 'mtu_size', 23)
            small_count = min(480, max(14, mtu - 9))
            # WinRT can assemble Read Blob responses. This avoids thousands of
            # selector writes when Windows remains at MTU 23. Fall back below
            # if a driver only returns the first ATT packet.
            count = 480 if getattr(protocol, 'supports_long_reads', False) else small_count
            LOGGER.info("JPEG transfer started: id=%s bytes=%s mtu=%s chunk=%s", frame_id, metadata.size, mtu, count)
            image = bytearray()
            heartbeat = time.monotonic()
            progress_at = heartbeat
            if on_progress:
                on_progress(0, metadata.size)
            while len(image) < metadata.size:
                offset = len(image)
                wanted = min(count, metadata.size - offset)
                for attempt in range(3):
                    await asyncio.wait_for(protocol.client.write_gatt_char(
                        IMAGE_UUID, struct.pack('<III', frame_id, offset, wanted), response=True), 8)
                    try:
                        packet = bytes(await asyncio.wait_for(protocol.client.read_gatt_char(IMAGE_UUID), 8))
                    except Exception:
                        if wanted <= small_count:
                            raise
                        LOGGER.warning("GATT long read failed; retrying MTU-sized chunks at offset=%s", offset, exc_info=True)
                        count = small_count
                        wanted = min(count, metadata.size - offset)
                        continue
                    if (wanted > small_count and len(packet) == small_count + 8 and
                            struct.unpack('<II', packet[:8]) == (frame_id, offset)):
                        LOGGER.warning("GATT long read truncated; falling back to MTU-sized chunks at offset=%s", offset)
                        count = small_count
                        wanted = min(count, metadata.size - offset)
                        continue
                    if (len(packet) == wanted + 8 and struct.unpack('<II', packet[:8]) == (frame_id, offset)):
                        image.extend(packet[8:])
                        break
                else:
                    raise ValueError(f"Ảnh BLE sai offset/độ dài sau 3 lần đọc tại byte {offset:,}/{metadata.size:,}. Hãy chụp lại.")
                if time.monotonic() - heartbeat >= 4:
                    await protocol.request('PING')
                    LOGGER.info("JPEG transfer progress: id=%s received=%s/%s", frame_id, len(image), metadata.size)
                    heartbeat = time.monotonic()
                if on_progress and (len(image) == metadata.size or time.monotonic() - progress_at >= .25):
                    on_progress(len(image), metadata.size)
                    progress_at = time.monotonic()
            verify_jpeg(image, metadata)
            LOGGER.info("JPEG received: bytes=%s, %sx%s, mtu=%s, CRC32 verified", len(image), metadata.width, metadata.height, mtu)
            return metadata, bytes(image)
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            # During process shutdown, go straight to GATT disconnect. Waiting
            # for another NUS ACK would consume the graceful shutdown window.
            if not cancelled:
                try:
                    await protocol.request(f'CAM RELEASE {frame_id}')
                except Exception:
                    LOGGER.warning("Could not release camera frame; disconnect/TTL will release it", exc_info=True)
