pub use vietocr_contracts::mjpeg::*;
#[cfg(test)]
pub fn jpeg_fixture() -> Vec<u8> {
    vec![
        0xff, 0xd8, 0xff, 0xe0, 0, 6, 0xff, 0xd9, 0, 0, 0xff, 0xc0, 0, 11, 8, 4, 56, 7, 128, 1, 1,
        0x11, 0, 0xff, 0xd9,
    ]
}
