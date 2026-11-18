"""Check shipped icon pixels, including icons embedded in the actual Windows EXE."""
import argparse
import ctypes
from ctypes import wintypes
from io import BytesIO
import json
from pathlib import Path
import struct
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SIZES = {16, 24, 32, 48, 64, 128, 256}


def check(image):
    image = image.convert('RGBA')
    box = image.getchannel('A').point(lambda value: 255 if value >= 128 else 0).getbbox()
    assert box, 'Icon is empty'
    coverage = min((box[2] - box[0]) / image.width, (box[3] - box[1]) / image.height)
    assert coverage >= .9, f'Icon artwork too small: {image.size}, {box}'
    orange = sum(1 for r, g, b, a in image.get_flattened_data() if a > 128 and r > 170 and 65 < g < 200 and b < 110)
    assert orange >= image.width * image.height * .025, f'Missing visible SHAD mark: {image.size}'
    # At 16 px the rounded edge contributes a little antialiasing to the corner.
    assert image.getpixel((0, 0))[3] < 64 and image.getpixel((image.width - 1, image.height - 1))[3] < 64, 'Rounded corners must be transparent'
    for y in range(image.height):
        for x in range(image.width):
            if x < image.width * .1 or x >= image.width * .9 or y < image.height * .1 or y >= image.height * .9:
                r, g, b, a = image.getpixel((x, y))
                assert not (a > 32 and min(r, g, b) > 100), 'Screenshot white fringe remains around the edge'
    return {'size': image.width, 'artworkBounds': list(box)}


def embedded_icons(exe):
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    api.LoadLibraryExW.restype = wintypes.HMODULE
    api.FindResourceW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p]
    api.FindResourceW.restype = wintypes.HANDLE
    api.LoadResource.argtypes = [wintypes.HMODULE, wintypes.HANDLE]
    api.LoadResource.restype = wintypes.HANDLE
    api.SizeofResource.argtypes = [wintypes.HMODULE, wintypes.HANDLE]
    api.SizeofResource.restype = wintypes.DWORD
    api.LockResource.argtypes = [wintypes.HANDLE]
    api.LockResource.restype = ctypes.c_void_p
    api.FreeLibrary.argtypes = [wintypes.HMODULE]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ssize_t)
    api.EnumResourceNamesW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, callback_type, ctypes.c_ssize_t]
    module = api.LoadLibraryExW(str(exe.resolve()), None, 2)
    assert module, ctypes.WinError(ctypes.get_last_error())
    payloads = []

    @callback_type
    def collect(handle, kind, name, context):
        resource = api.FindResourceW(handle, name, kind)
        payloads.append(ctypes.string_at(api.LockResource(api.LoadResource(handle, resource)), api.SizeofResource(handle, resource)))
        return True

    try:
        assert api.EnumResourceNamesW(module, 3, collect, 0), ctypes.WinError(ctypes.get_last_error())
    finally:
        api.FreeLibrary(module)
    images = []
    for payload in payloads:
        if payload.startswith(b'\x89PNG'):
            image = Image.open(BytesIO(payload))
        else:
            _, width, doubled_height = struct.unpack_from('<Iii', payload)
            height = doubled_height // 2
            header = struct.pack('<HHHBBBBHHII', 0, 1, 1, width % 256, height % 256, 0, 0, 1, 32, len(payload), 22)
            image = Image.open(BytesIO(header + payload))
        images.append(image)
    return images


def window_icons(handle):
    """Read actual live HWND icons; do not capture or modify the user's desktop."""
    user = ctypes.WinDLL('user32', use_last_error=True)
    gdi = ctypes.WinDLL('gdi32', use_last_error=True)
    user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
    user.SendMessageW.restype = ctypes.c_ssize_t
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    gdi.CreateDIBSection.restype = wintypes.HBITMAP
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi.SelectObject.restype = wintypes.HANDLE
    gdi.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    user.DrawIconEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HICON, ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.HBRUSH, wintypes.UINT]
    frames = []
    for kind, size in [(0, 16), (1, 32)]:
        icon = user.SendMessageW(handle, 0x7f, kind, 0)  # WM_GETICON
        assert icon, f'Window icon is missing: kind {kind}'
        dc = gdi.CreateCompatibleDC(None)
        assert dc
        bitmap = previous = None
        try:
            info = ctypes.create_string_buffer(struct.pack('<IiiHHIIiiII', 40, size, -size, 1, 32, 0, size * size * 4, 0, 0, 0, 0))
            pixels = ctypes.c_void_p()
            bitmap = gdi.CreateDIBSection(dc, info, 0, ctypes.byref(pixels), None, 0)
            assert bitmap and pixels.value
            previous = gdi.SelectObject(dc, bitmap)
            assert user.DrawIconEx(dc, 0, 0, icon, size, size, 0, None, 3)
            frames.append(Image.frombytes('RGBA', (size, size), ctypes.string_at(pixels, size * size * 4), 'raw', 'BGRA'))
        finally:
            if previous:
                gdi.SelectObject(dc, previous)
            if bitmap:
                gdi.DeleteObject(bitmap)
            gdi.DeleteDC(dc)
    return frames


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=ROOT / 'verification/desktop-icon/icon-check.json')
    parser.add_argument('--window-handle', type=int)
    args = parser.parse_args()
    icon = Image.open(ROOT / 'desktop/icon.ico')
    assert {width for width, height in icon.ico.sizes() if width == height} == SIZES
    frames = [check(icon.ico.getimage((size, size))) for size in sorted(SIZES)]
    shipped = args.exe.parent / 'resources/shad-0.7.3.ico'
    assert shipped.read_bytes() == (ROOT / 'desktop/icon.ico').read_bytes()
    embedded = [check(image) for image in embedded_icons(args.exe)]
    assert {item['size'] for item in embedded} == SIZES
    args.out.parent.mkdir(parents=True, exist_ok=True)
    result = {'passed': True, 'ico': frames, 'embeddedExe': embedded}
    if args.window_handle:
        actual = window_icons(args.window_handle)
        result['liveWindowIcons'] = [check(image) for image in actual]
        for image in actual:
            image.save(args.out.parent / f'window-icon-{image.width}.png')
    args.out.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('Passed: all seven ICO and embedded EXE resolutions fill their canvas and retain the SHAD mark.')


if __name__ == '__main__':
    main()
