"""Narrow native bridge and activation of an already-open desktop project."""
import json
import os
import threading
from pathlib import Path

import psutil

from .projects import validate_project


class DesktopBridge:
    # pywebview exposes public members to JS; native objects stay private.
    _window = None
    _project = None
    _next_project = None
    _loaded = False
    _allow_close = False
    _closing = False

    def _on_loaded(self):
        self._loaded = True

    def _on_closing(self):
        if self._allow_close or not self._loaded:
            return True
        if not self._closing:
            self._closing = True
            # Never wait for JavaScript on WinForms' closing/UI thread.
            threading.Thread(target=self._flush_before_close, daemon=True).start()
        return False

    def _flush_before_close(self):
        try:
            self._window.evaluate_js(
                "window.openPhotoFlush ? window.openPhotoFlush() : Promise.resolve(true)",
                callback=self._save_finished,
            )
        except Exception as error:
            self._closing = False
            self._next_project = None
            show_startup_error(f"Не удалось сохранить правку перед закрытием: {error}")

    def _save_finished(self, success):
        self._closing = False
        if success is True:
            self._allow_close = True
            self._window.destroy()
        else:
            self._next_project = None

    def choose_folder(self):
        import webview

        return list(self._window.create_file_dialog(webview.FileDialog.FOLDER) or [])

    def choose_photos(self, references=False):
        import webview

        extensions = "*.arw;*.jpg;*.jpeg;*.png;*.tif;*.tiff" + (";*.psd" if references else "")
        return list(self._window.create_file_dialog(webview.FileDialog.OPEN,
                    allow_multiple=True, file_types=(f"Photos ({extensions})",)) or [])

    def open_project(self, directory, create=False):
        target = Path(directory).expanduser().resolve()
        if self._project and target == Path(self._project).resolve():
            return {"restarting": False}
        self._next_project = validate_project(target, bool(create))
        self._window.destroy()
        return {"restarting": True}


def register_instance(directory):
    from .service import atomic_text

    path = Path(directory) / ".desktop-instance.json"
    atomic_text(path, json.dumps({"pid": os.getpid(), "created": psutil.Process().create_time()}))
    return path


def forget_instance(path):
    try:
        if json.loads(path.read_text())["pid"] == os.getpid():
            path.unlink(missing_ok=True)
    except (OSError, ValueError, KeyError):
        pass


def focus_existing(directory):
    if os.name != "nt":
        return False
    try:
        state = json.loads((Path(directory) / ".desktop-instance.json").read_text())
        if psutil.Process(state["pid"]).create_time() != state["created"]:
            return False
    except (OSError, ValueError, KeyError, psutil.Error):
        return False
    import ctypes
    from ctypes import wintypes

    user = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    found = []

    @callback_type
    def visit(window, _):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(window, ctypes.byref(pid))
        if pid.value == state["pid"] and user.IsWindowVisible(window):
            user.ShowWindow(window, 9)
            user.SetForegroundWindow(window)
            found.append(True)
            return False
        return True

    user.EnumWindows(visit, 0)
    return bool(found)


def show_startup_error(message):
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, str(message), "OpenPhoto — не удалось открыть проект", 0x10)
