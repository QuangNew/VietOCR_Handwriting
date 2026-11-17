use std::{fs::File, io::Write, path::Path};
/// One desktop writer per app-data directory. The OS releases the lock on exit,
/// including a crash; a stale PID file can never permanently block the app.
pub fn workspace_lock(root: &Path) -> std::io::Result<Option<File>> {
    std::fs::create_dir_all(root)?;
    let file = File::options()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(root.join("workspace.lock"))?;
    match file.try_lock() {
        Ok(()) => Ok(Some(file)),
        Err(std::fs::TryLockError::WouldBlock) => Ok(None),
        Err(std::fs::TryLockError::Error(error)) => Err(error),
    }
}
pub fn atomic(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let temp = path.with_extension("tmp");
    let mut file = File::create(&temp).map_err(|_| "Không tạo được file tạm")?;
    file.write_all(bytes)
        .and_then(|_| file.sync_all())
        .map_err(|_| "Không ghi được dữ liệu")?;
    drop(file);
    #[cfg(windows)]
    {
        use std::os::windows::ffi::OsStrExt;
        #[link(name = "kernel32")]
        unsafe extern "system" {
            fn MoveFileExW(from: *const u16, to: *const u16, flags: u32) -> i32;
        }
        let a = temp
            .as_os_str()
            .encode_wide()
            .chain(Some(0))
            .collect::<Vec<_>>();
        let b = path
            .as_os_str()
            .encode_wide()
            .chain(Some(0))
            .collect::<Vec<_>>();
        // SAFETY: both UTF-16 buffers are NUL-terminated and live for the call.
        if unsafe { MoveFileExW(a.as_ptr(), b.as_ptr(), 1 | 8) } == 0 {
            return Err("Không thay thế được file".into());
        }
    }
    #[cfg(not(windows))]
    std::fs::rename(temp, path).map_err(|_| "Không thay thế được file")?;
    Ok(())
}
#[cfg(windows)]
pub fn protect(bytes: &[u8], decrypt: bool) -> Result<Vec<u8>, String> {
    use std::{ffi::c_void, ptr};
    #[repr(C)]
    struct Blob {
        len: u32,
        data: *mut u8,
    }
    #[link(name = "crypt32")]
    unsafe extern "system" {
        fn CryptProtectData(
            input: *const Blob,
            description: *const u16,
            entropy: *const Blob,
            reserved: *mut c_void,
            prompt: *mut c_void,
            flags: u32,
            output: *mut Blob,
        ) -> i32;
        fn CryptUnprotectData(
            input: *const Blob,
            description: *mut *mut u16,
            entropy: *const Blob,
            reserved: *mut c_void,
            prompt: *mut c_void,
            flags: u32,
            output: *mut Blob,
        ) -> i32;
    }
    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn LocalFree(ptr: *mut c_void) -> *mut c_void;
    }
    let input = Blob {
        len: u32::try_from(bytes.len()).map_err(|_| "Session quá lớn")?,
        data: bytes.as_ptr() as *mut u8,
    };
    let mut output = Blob {
        len: 0,
        data: ptr::null_mut(),
    };
    // SAFETY: input is a borrowed buffer. DPAPI allocates output; we copy it
    // before releasing with LocalFree. UI-forbidden, current Windows user only.
    unsafe {
        let ok = if decrypt {
            CryptUnprotectData(
                &input,
                ptr::null_mut(),
                ptr::null(),
                ptr::null_mut(),
                ptr::null_mut(),
                1,
                &mut output,
            )
        } else {
            CryptProtectData(
                &input,
                ptr::null(),
                ptr::null(),
                ptr::null_mut(),
                ptr::null_mut(),
                1,
                &mut output,
            )
        };
        if ok == 0 {
            return Err("Không mở/lưu được phiên Windows DPAPI".into());
        }
        let result = std::slice::from_raw_parts(output.data, output.len as usize).to_vec();
        LocalFree(output.data as *mut c_void);
        Ok(result)
    }
}
#[cfg(not(windows))]
pub fn protect(_: &[u8], _: bool) -> Result<Vec<u8>, String> {
    Err("Desktop credentials require Windows DPAPI".into())
}
