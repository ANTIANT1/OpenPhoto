from openphoto.__main__ import DesktopBridge


def test_native_window_is_not_exposed_to_javascript():
    bridge = DesktopBridge()
    bridge._window = object()
    public = [name for name in dir(bridge) if not name.startswith("_")]
    assert set(public) == {"choose_folder", "choose_photos", "open_project"}
    assert all(callable(getattr(bridge, name)) for name in public)


def test_close_waits_for_confirmed_save_and_keeps_window_on_failure():
    import threading

    class Window:
        callback = None
        destroyed = False
        evaluated = threading.Event()

        def evaluate_js(self, script, callback):
            assert 'openPhotoFlush' in script
            self.callback = callback
            self.evaluated.set()

        def destroy(self):
            self.destroyed = True

    bridge = DesktopBridge()
    bridge._window = window = Window()
    bridge._loaded = True
    assert bridge._on_closing() is False
    assert window.evaluated.wait(2)
    assert not window.destroyed
    window.callback(False)
    assert not window.destroyed and not bridge._allow_close
    window.evaluated.clear()
    assert bridge._on_closing() is False
    assert window.evaluated.wait(2)
    window.callback(True)
    assert window.destroyed and bridge._on_closing() is True
