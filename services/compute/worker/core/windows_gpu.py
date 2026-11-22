"""DXGI adapter IDs and D3D12 UMA classification for the DirectML provider.

Keep native driver calls in the AI worker. Never guess adapter IDs from WMI
or assume every Intel adapter is integrated. Software adapters are excluded.
"""

import ctypes as c
import uuid


def directml_adapters():
    class GUID(c.Structure):
        _fields_ = [("data", c.c_ubyte * 16)]

    class LUID(c.Structure):
        _fields_ = [("low", c.c_uint32), ("high", c.c_int32)]

    class Desc(c.Structure):
        _fields_ = [("name", c.c_wchar * 128), ("vendor", c.c_uint32),
                    ("device", c.c_uint32), ("subsys", c.c_uint32), ("revision", c.c_uint32),
                    ("vram", c.c_size_t), ("system", c.c_size_t), ("shared", c.c_size_t),
                    ("luid", LUID), ("flags", c.c_uint32)]

    class Architecture(c.Structure):
        _fields_ = [("node", c.c_uint32), ("tile", c.c_int32),
                    ("uma", c.c_int32), ("coherent", c.c_int32)]

    def guid(value):
        return GUID.from_buffer_copy(uuid.UUID(value).bytes_le)

    def method(obj, slot, restype, *args):
        table = c.cast(obj, c.POINTER(c.POINTER(c.c_void_p))).contents
        return c.WINFUNCTYPE(restype, c.c_void_p, *args)(table[slot])

    def release(obj):
        if obj:
            method(obj, 2, c.c_uint32)(obj)

    dxgi = c.WinDLL("dxgi.dll")
    d3d = c.WinDLL("d3d12.dll")
    dxgi.CreateDXGIFactory1.argtypes = [c.POINTER(GUID), c.POINTER(c.c_void_p)]
    dxgi.CreateDXGIFactory1.restype = c.c_int32
    d3d.D3D12CreateDevice.argtypes = [c.c_void_p, c.c_uint32, c.POINTER(GUID), c.POINTER(c.c_void_p)]
    d3d.D3D12CreateDevice.restype = c.c_int32
    factory = c.c_void_p()
    factory_id = guid("770aae78-f26f-4dba-a829-253c83d1b387")
    device_id = guid("189819f1-1db6-4b57-be54-1821339b85f7")
    if dxgi.CreateDXGIFactory1(c.byref(factory_id), c.byref(factory)) < 0:
        raise RuntimeError("Không tạo được DXGI factory")
    result = []
    seen = set()
    try:
        for index in range(32):
            adapter, device = c.c_void_p(), c.c_void_p()
            hr = method(factory, 12, c.c_int32, c.c_uint32, c.POINTER(c.c_void_p))(
                factory, index, c.byref(adapter))
            if hr & 0xffffffff == 0x887a0002:  # DXGI_ERROR_NOT_FOUND
                break
            if hr < 0:
                raise RuntimeError(f"DXGI EnumAdapters1: 0x{hr & 0xffffffff:08x}")
            try:
                desc = Desc()
                if method(adapter, 10, c.c_int32, c.POINTER(Desc))(adapter, c.byref(desc)) < 0:
                    continue
                if desc.flags & 2:  # DXGI_ADAPTER_FLAG_SOFTWARE
                    continue
                luid = (desc.luid.high, desc.luid.low)
                if luid in seen:
                    continue
                if d3d.D3D12CreateDevice(adapter, 0xb000, c.byref(device_id), c.byref(device)) < 0:
                    continue
                architecture = Architecture()
                hr = method(device, 13, c.c_int32, c.c_uint32, c.c_void_p, c.c_uint32)(
                    device, 1, c.byref(architecture), c.sizeof(architecture))
                if hr < 0:
                    continue  # Do not misclassify an unknown/virtual adapter.
                seen.add(luid)
                result.append({"index": index, "name": desc.name, "integrated": bool(architecture.uma),
                               "luid": f"{desc.luid.high & 0xffffffff:08x}{desc.luid.low:08x}"})
            finally:
                release(device)
                release(adapter)
    finally:
        release(factory)
    return result


def resolve_adapter(luid, adapters=None):
    """DXGI indices may change after waking a discrete GPU or restarting a worker."""
    adapters = directml_adapters() if adapters is None else adapters
    for adapter in adapters:
        if adapter["luid"] == luid:
            return adapter
    raise RuntimeError("GPU DirectML đã chọn không còn khả dụng; cần tìm lại thiết bị.")
