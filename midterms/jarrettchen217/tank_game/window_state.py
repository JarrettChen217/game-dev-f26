"""Read-only native focus/viewport observation; never consumes Pyxel events."""
import ctypes as C
import os
import platform
import sys
from dataclasses import dataclass

from tank_game.window_contract import WindowSnapshot


@dataclass(frozen=True)
class RawWindow:
    focused: bool
    size: tuple[float, float]
    position: tuple[float, float]
    identity: tuple


class NativeWindowObserver:
    def __init__(self, reader=None):
        self.reader = reader or (CocoaWindow() if sys.platform == 'darwin' else
                                 Win32Window() if sys.platform == 'win32' else SDLWindow())

    def sample(self, pyxel):
        raw = self.reader()
        width, height = raw.size
        logical = (getattr(pyxel, 'width', 920), getattr(pyxel, 'height', 464))
        scale = max(1, min(width/logical[0], height/logical[1]))
        left, top = (width-logical[0]*scale)/2, (height-logical[1]*scale)/2
        x, y = raw.position
        inside = left <= x < left+logical[0]*scale and top <= y < top+logical[1]*scale
        return WindowSnapshot(raw.focused, (*raw.identity, width, height), inside)

    def close(self):
        close = getattr(self.reader, 'close', None)
        if close:
            close()


class Point(C.Structure):
    _fields_ = [('x', C.c_double), ('y', C.c_double)]


class Size(C.Structure):
    _fields_ = [('width', C.c_double), ('height', C.c_double)]


class Rect(C.Structure):
    _fields_ = [('origin', Point), ('size', Size)]


class CocoaWindow:
    """Cocoa notifications retain cancellation epochs even while Pyxel is paused."""
    def __init__(self):
        self.objc = C.CDLL('/usr/lib/libobjc.A.dylib')
        self.objc.objc_getClass.restype = C.c_void_p
        self.objc.objc_getClass.argtypes = [C.c_char_p]
        self.objc.sel_registerName.restype = C.c_void_p
        self.objc.sel_registerName.argtypes = [C.c_char_p]
        self.app = self.send(self.objc.objc_getClass(b'NSApplication'), 'sharedApplication')
        self.window = None
        self.epoch = 0
        self.observer = None
        self.center = self.send(self.objc.objc_getClass(b'NSNotificationCenter'), 'defaultCenter')

    def send(self, obj, selector, result=C.c_void_p, args=(), values=()):
        fn = C.CFUNCTYPE(result, C.c_void_p, C.c_void_p, *args)(
            C.cast(self.objc.objc_msgSend, C.c_void_p).value)
        return fn(obj, self.objc.sel_registerName(selector.encode()), *values)

    def rect(self, obj, selector):
        # Intel Objective-C uses the explicit stret entry for a 32-byte NSRect.
        if platform.machine() == 'x86_64':
            value = Rect()
            fn = C.CFUNCTYPE(None, C.POINTER(Rect), C.c_void_p, C.c_void_p)(
                C.cast(self.objc.objc_msgSend_stret, C.c_void_p).value)
            fn(C.byref(value), obj, self.objc.sel_registerName(selector.encode()))
            return value
        return self.send(obj, selector, Rect)

    def _watch(self):
        callback_type = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, C.c_void_p)
        self.callback = callback_type(lambda *_: setattr(self, 'epoch', self.epoch+1))
        self.objc.objc_allocateClassPair.argtypes = [C.c_void_p, C.c_char_p, C.c_size_t]
        self.objc.objc_allocateClassPair.restype = C.c_void_p
        cls = self.objc.objc_allocateClassPair(self.objc.objc_getClass(b'NSObject'),
                                              f'TankMenuObserver_{id(self):x}'.encode(), 0)
        self.objc.class_addMethod.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_char_p]
        selector = self.objc.sel_registerName(b'windowChanged:')
        self.objc.class_addMethod(cls, selector, C.cast(self.callback, C.c_void_p), b'v@:@')
        self.objc.objc_registerClassPair.argtypes = [C.c_void_p]
        self.objc.objc_registerClassPair(cls)
        self.observer = self.send(self.send(cls, 'alloc'), 'init')
        for name, obj in (('NSWindowDidResignKeyNotification', self.window),
                          ('NSWindowDidBecomeKeyNotification', self.window),
                          ('NSWindowDidResizeNotification', self.window),
                          ('NSWindowDidMoveNotification', self.window),
                          ('NSApplicationDidResignActiveNotification', self.app)):
            string = self.send(self.objc.objc_getClass(b'NSString'), 'stringWithUTF8String:',
                               args=(C.c_char_p,), values=(name.encode(),))
            self.send(self.center, 'addObserver:selector:name:object:', None,
                      (C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p),
                      (self.observer, selector, string, obj))

    def __call__(self):
        if not self.window:
            windows = self.send(self.app, 'windows')
            for i in range(self.send(windows, 'count', C.c_ulong)):
                candidate = self.send(windows, 'objectAtIndex:', args=(C.c_ulong,), values=(i,))
                title = self.send(self.send(candidate, 'title'), 'UTF8String', C.c_char_p)
                if title and title.startswith(b'Tank maze'):
                    self.window = candidate
                    self._watch()
                    break
        if not self.window:
            return RawWindow(False, (920, 464), (-1, -1), ('cocoa', self.epoch))
        view = self.send(self.window, 'contentView')
        bounds = self.rect(view, 'bounds')
        point = self.send(self.window, 'mouseLocationOutsideOfEventStream', Point)
        focused = bool(self.send(self.app, 'isActive', C.c_bool)
                       and self.send(self.window, 'isKeyWindow', C.c_bool))
        scale = self.send(self.window, 'backingScaleFactor', C.c_double)
        return RawWindow(focused, (bounds.size.width, bounds.size.height),
                         (point.x, bounds.size.height-point.y), ('cocoa', self.window, scale, self.epoch))

    def close(self):
        if self.observer:
            self.send(self.center, 'removeObserver:', None, (C.c_void_p,), (self.observer,))
            self.send(self.observer, 'release', None)
            self.observer = None


class Win32Window:
    def __init__(self):
        from ctypes import wintypes as W
        self.W = W
        self.user = C.WinDLL('user32', use_last_error=True)
        self.user.GetForegroundWindow.restype = W.HWND
        self.user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
        self.user.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
        self.hwnd = None
        self.epoch = 0
        self.hooks = []

    def _find(self):
        W, user = self.W, self.user
        enum_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        def visit(hwnd, _):
            pid = W.DWORD()
            user.GetWindowThreadProcessId(hwnd, C.byref(pid))
            title = C.create_unicode_buffer(256)
            user.GetWindowTextW(hwnd, title, 256)
            if pid.value == os.getpid() and title.value.startswith('Tank maze'):
                self.hwnd = hwnd
                return False
            return True
        callback = enum_type(visit)
        user.EnumWindows.argtypes = [enum_type, W.LPARAM]
        user.EnumWindows(callback, 0)
        if self.hwnd:
            hook_type = C.WINFUNCTYPE(None, W.HANDLE, W.DWORD, W.HWND,
                                      W.LONG, W.LONG, W.DWORD, W.DWORD)
            def changed(_hook, event, hwnd, *_):
                if event == 3 or hwnd == self.hwnd:
                    self.epoch += 1
            self.callback = hook_type(changed)
            user.SetWinEventHook.restype = W.HANDLE
            user.SetWinEventHook.argtypes = [W.DWORD, W.DWORD, W.HMODULE, hook_type,
                                            W.DWORD, W.DWORD, W.DWORD]
            for event, pid in ((3, 0), (0x800B, os.getpid())):
                hook = user.SetWinEventHook(event, event, None, self.callback, pid, 0, 0)
                if not hook:
                    raise OSError('Cannot observe native window events')
                self.hooks.append(hook)

    def __call__(self):
        if not self.hwnd:
            self._find()
        if not self.hwnd:
            return RawWindow(False, (920, 464), (-1, -1), ('win32', self.epoch))
        W, user = self.W, self.user
        # Explicit pointer-size signatures: HWND must never be truncated on x64.
        user.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
        user.ScreenToClient.argtypes = [W.HWND, C.POINTER(W.POINT)]
        rect, point = W.RECT(), W.POINT()
        user.GetClientRect(self.hwnd, C.byref(rect))
        user.GetCursorPos(C.byref(point))
        user.ScreenToClient(self.hwnd, C.byref(point))
        return RawWindow(user.GetForegroundWindow() == self.hwnd,
                         (rect.right-rect.left, rect.bottom-rect.top), (point.x, point.y),
                         ('win32', self.hwnd, self.epoch))

    def close(self):
        self.user.UnhookWinEvent.argtypes = [self.W.HANDLE]
        for hook in self.hooks:
            self.user.UnhookWinEvent(hook)
        self.hooks.clear()


class SDLWindow:
    """Linux source runtime: observe the bundled SDL2 queue without removing events."""
    def __init__(self):
        from ctypes.util import find_library
        self.sdl = C.CDLL(find_library('SDL2-2.0') or 'libSDL2-2.0.so.0')
        self.sdl.SDL_GetKeyboardFocus.restype = C.c_void_p
        self.sdl.SDL_GetWindowSize.argtypes = [C.c_void_p, C.POINTER(C.c_int), C.POINTER(C.c_int)]
        self.sdl.SDL_GetWindowFlags.argtypes = [C.c_void_p]
        self.sdl.SDL_GetWindowID.argtypes = [C.c_void_p]
        self.window = None
        self.epoch = 0
        callback_type = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_void_p)
        def watch(_data, event):
            raw = C.string_at(event, 16)
            if int.from_bytes(raw[:4], sys.byteorder) == 0x200:
                self.epoch += 1
            return 1
        self.callback = callback_type(watch)
        self.sdl.SDL_AddEventWatch.argtypes = [callback_type, C.c_void_p]
        self.sdl.SDL_DelEventWatch.argtypes = [callback_type, C.c_void_p]
        self.sdl.SDL_AddEventWatch(self.callback, None)

    def __call__(self):
        self.window = self.window or self.sdl.SDL_GetKeyboardFocus()
        if not self.window:
            return RawWindow(False, (920, 464), (-1, -1), ('sdl', self.epoch))
        width, height, x, y = (C.c_int() for _ in range(4))
        self.sdl.SDL_GetWindowSize(self.window, C.byref(width), C.byref(height))
        self.sdl.SDL_GetMouseState(C.byref(x), C.byref(y))
        return RawWindow(bool(self.sdl.SDL_GetWindowFlags(self.window) & 0x200),
                         (width.value, height.value), (x.value, y.value), ('sdl', self.epoch))

    def close(self):
        self.sdl.SDL_DelEventWatch(self.callback, None)
