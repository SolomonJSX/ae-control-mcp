"""Windows GUI automation: DPI-aware screenshots, mouse, keyboard, and windows."""

from __future__ import annotations

import ctypes
import io
import sys
import time
from dataclasses import dataclass
from typing import Literal

import mss
import pyautogui
import pygetwindow as gw
from PIL import Image


def enable_dpi_awareness() -> None:
    """Ensure screenshot and mouse coordinates match physical pixels on Windows."""
    if sys.platform != "win32":
        return
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


enable_dpi_awareness()

# Moving the cursor to any screen corner aborts PyAutoGUI actions immediately.
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05


@dataclass(frozen=True)
class ScreenshotResult:
    image_bytes: bytes
    mime_type: str
    width: int
    height: int
    original_width: int
    original_height: int
    offset_x: int
    offset_y: int
    scale_x: float = 1.0
    scale_y: float = 1.0


def get_screen_size() -> tuple[int, int]:
    """Return primary screen width and height in physical pixels."""
    size = pyautogui.size()
    return int(size.width), int(size.height)


def capture_screenshot(
    monitor_index: int = 1,
    window_title: str | None = None,
    image_format: Literal["png", "jpeg"] = "jpeg",
    max_dimension: int | None = None,
) -> ScreenshotResult:
    """Capture a monitor or a specific window and return encoded image bytes.

    If max_dimension is provided and the captured image exceeds it, the image is
    downscaled proportionally and scale_x / scale_y report the physical-to-image
    ratio (multiply image coords by scale_x / scale_y before adding offset_x / offset_y).
    """
    mss_cls = getattr(mss, "MSS", mss.mss)
    with mss_cls() as sct:
        if window_title:
            win = _find_window(window_title)
            if win is None:
                raise ValueError(f"Window matching '{window_title}' was not found.")
            if win.isMinimized:
                raise ValueError(
                    f"Window '{win.title}' is minimized. Call focus_window('{window_title}') first."
                )
            if int(win.width) <= 0 or int(win.height) <= 0:
                raise ValueError(f"Window '{win.title}' has invalid size ({win.width}x{win.height}).")
            region = {
                "left": int(win.left),
                "top": int(win.top),
                "width": int(win.width),
                "height": int(win.height),
            }
            raw = sct.grab(region)
            offset_x, offset_y = region["left"], region["top"]
        else:
            if monitor_index < 0 or monitor_index >= len(sct.monitors):
                raise ValueError(
                    f"monitor_index {monitor_index} out of range (0..{len(sct.monitors) - 1})."
                )
            mon = sct.monitors[monitor_index]
            raw = sct.grab(mon)
            offset_x, offset_y = int(mon["left"]), int(mon["top"])

        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        orig_w, orig_h = img.width, img.height
        scale_x, scale_y = 1.0, 1.0

        if max_dimension is not None and max_dimension > 0:
            longest = max(orig_w, orig_h)
            if longest > max_dimension:
                ratio = max_dimension / float(longest)
                new_w = max(1, int(round(orig_w * ratio)))
                new_h = max(1, int(round(orig_h * ratio)))
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                scale_x = orig_w / float(new_w)
                scale_y = orig_h / float(new_h)

        buf = io.BytesIO()
        if image_format == "png":
            img.save(buf, format="PNG", optimize=True)
            mime_type = "image/png"
        else:
            img.save(buf, format="JPEG", quality=85, optimize=True)
            mime_type = "image/jpeg"

        return ScreenshotResult(
            image_bytes=buf.getvalue(),
            mime_type=mime_type,
            width=img.width,
            height=img.height,
            original_width=orig_w,
            original_height=orig_h,
            offset_x=offset_x,
            offset_y=offset_y,
            scale_x=round(scale_x, 6),
            scale_y=round(scale_y, 6),
        )


def _find_window(title_query: str) -> gw.Win32Window | None:
    """Return the first window whose title contains title_query (case-insensitive)."""
    query = title_query.lower().strip()
    if not query:
        return None
    for win in gw.getAllWindows():
        if win.title and query in win.title.lower():
            return win
    return None


def _ensure_within_window(x: int, y: int, target_window: str) -> None:
    """Verify that screen coordinates (x, y) lie within the specified target window."""
    win = _find_window(target_window)
    if win is None:
        raise ValueError(f"Target window '{target_window}' was not found.")
    if win.isMinimized:
        raise ValueError(f"Target window '{win.title}' is minimized.")
    left, top = int(win.left), int(win.top)
    right, bottom = left + int(win.width), top + int(win.height)
    if not (left <= x <= right and top <= y <= bottom):
        raise ValueError(
            f"Coordinates ({x}, {y}) are outside target window '{win.title}' "
            f"bounds [{left}, {top}, {right}, {bottom}]."
        )


def list_open_windows() -> list[dict[str, int | str | bool]]:
    """Return metadata for all non-empty titled windows."""
    windows = []
    for win in gw.getAllWindows():
        if not win.title.strip():
            continue
        windows.append(
            {
                "title": win.title,
                "left": int(win.left),
                "top": int(win.top),
                "width": int(win.width),
                "height": int(win.height),
                "is_active": bool(win.isActive),
                "is_minimized": bool(win.isMinimized),
            }
        )
    return windows


def focus_window(title_query: str) -> dict[str, int | str]:
    """Restore if minimized and bring the matching window to the foreground."""
    win = _find_window(title_query)
    if win is None:
        raise ValueError(f"Window matching '{title_query}' was not found.")

    if win.isMinimized:
        win.restore()
        time.sleep(0.1)

    try:
        win.activate()
    except Exception:
        # Workaround for Windows SetForegroundWindow restriction in pygetwindow
        if sys.platform == "win32" and hasattr(win, "_hWnd"):
            hwnd = int(win._hWnd)
            user32 = ctypes.windll.user32
            SW_RESTORE = 9
            user32.ShowWindow(hwnd, SW_RESTORE)
            # Sending a brief Alt press/release allows SetForegroundWindow in Windows
            pyautogui.press("alt")
            user32.SetForegroundWindow(hwnd)
        else:
            raise

    time.sleep(0.05)
    return {
        "title": win.title,
        "left": int(win.left),
        "top": int(win.top),
        "width": int(win.width),
        "height": int(win.height),
    }


def move_mouse(
    x: int,
    y: int,
    duration: float = 0.15,
    target_window: str | None = None,
) -> tuple[int, int]:
    """Move mouse cursor to absolute screen coordinates."""
    if target_window:
        _ensure_within_window(x, y, target_window)
    pyautogui.moveTo(x, y, duration=max(0.0, duration))
    pos = pyautogui.position()
    return int(pos.x), int(pos.y)


def click_mouse(
    x: int | None = None,
    y: int | None = None,
    button: Literal["left", "right", "middle"] = "left",
    clicks: int = 1,
    interval: float = 0.1,
    target_window: str | None = None,
) -> tuple[int, int]:
    """Click at (x, y) or at the current cursor position if coordinates are omitted."""
    if target_window:
        check_x, check_y = (x, y) if (x is not None and y is not None) else pyautogui.position()
        _ensure_within_window(int(check_x), int(check_y), target_window)

    if x is not None and y is not None:
        pyautogui.click(x=x, y=y, clicks=clicks, interval=interval, button=button)
    else:
        pyautogui.click(clicks=clicks, interval=interval, button=button)
    pos = pyautogui.position()
    return int(pos.x), int(pos.y)


def drag_mouse(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    duration: float = 0.3,
    button: Literal["left", "right", "middle"] = "left",
    target_window: str | None = None,
) -> tuple[int, int]:
    """Drag from (start_x, start_y) to (end_x, end_y)."""
    if target_window:
        _ensure_within_window(start_x, start_y, target_window)
        _ensure_within_window(end_x, end_y, target_window)
    pyautogui.moveTo(start_x, start_y, duration=0.1)
    pyautogui.dragTo(end_x, end_y, duration=max(0.05, duration), button=button)
    pos = pyautogui.position()
    return int(pos.x), int(pos.y)


def scroll_mouse(clicks: int, x: int | None = None, y: int | None = None) -> None:
    """Scroll vertically (positive = up, negative = down)."""
    if x is not None and y is not None:
        pyautogui.scroll(clicks, x=x, y=y)
    else:
        pyautogui.scroll(clicks)


def _win32_get_clipboard_text() -> str | None:
    """Read current CF_UNICODETEXT from Windows clipboard, or None if unavailable."""
    if sys.platform != "win32":
        return None
    CF_UNICODETEXT = 13
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    if not user32.OpenClipboard(0):
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        kernel32.GlobalLock.restype = ctypes.c_void_p
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _win32_set_clipboard_text(text: str) -> bool:
    """Write UTF-16LE text to Windows clipboard."""
    if sys.platform != "win32":
        return False
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    data = text.encode("utf-16-le") + b"\x00\x00"
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.restype = ctypes.c_void_p

    if not user32.OpenClipboard(0):
        return False
    try:
        user32.EmptyClipboard()
        hmem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not hmem:
            return False
        ptr = kernel32.GlobalLock(hmem)
        if not ptr:
            kernel32.GlobalFree(hmem)
            return False
        try:
            ctypes.memmove(ptr, data, len(data))
        finally:
            kernel32.GlobalUnlock(hmem)
        if not user32.SetClipboardData(CF_UNICODETEXT, hmem):
            kernel32.GlobalFree(hmem)
            return False
        return True
    finally:
        user32.CloseClipboard()


def type_text(text: str, interval: float = 0.01) -> None:
    """Type text at the current focus, supporting both ASCII and Unicode (e.g. Cyrillic)."""
    if not text:
        return
    if text.isascii():
        pyautogui.write(text, interval=max(0.0, interval))
        return

    # PyAutoGUI's write() drops non-ASCII characters; use clipboard paste on Windows.
    if sys.platform == "win32":
        previous = _win32_get_clipboard_text()
        if _win32_set_clipboard_text(text):
            try:
                time.sleep(0.03)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.05)
            finally:
                if previous is not None:
                    _win32_set_clipboard_text(previous)
            return
    raise RuntimeError("Failed to type non-ASCII text via Windows clipboard.")


def press_hotkey(keys: list[str]) -> None:
    """Press a key combination, e.g. ['ctrl', 's'] or ['space']."""
    if not keys:
        raise ValueError("keys must be a non-empty list.")
    cleaned = [k.strip() for k in keys if k and k.strip()]
    if not cleaned:
        raise ValueError("keys must contain at least one non-empty key name.")
    if len(cleaned) == 1:
        pyautogui.press(cleaned[0])
    else:
        pyautogui.hotkey(*cleaned)
