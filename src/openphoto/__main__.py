from __future__ import annotations

import argparse
import os
import multiprocessing
import secrets
import socket
import threading
import sys
from pathlib import Path

import uvicorn

from .processes import configure_threads
from .desktop import DesktopBridge, focus_existing, forget_instance, register_instance, show_startup_error
from .projects import default_project, remember_project

configure_threads()


def main():
    from .api import create_app

    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description="OpenPhoto — local photo laboratory")
    parser.add_argument("--project", type=Path)
    parser.add_argument(
        "--browser", action="store_true", help="Serve in a local browser instead of a desktop window"
    )
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-worker", action="store_true", help="Diagnostic API-only mode")
    parser.add_argument(
        "--session-file", type=Path, help="Private temporary launch metadata for a supervising tool"
    )
    parser.add_argument("--self-test", type=Path, help="Write an offline installation diagnostic report")
    args = parser.parse_args()
    if args.self_test:
        from .diagnostics import self_test
        from .api import resource_root

        raise SystemExit(self_test(args.self_test, resource_root()))
    args.project = (args.project or default_project()).expanduser().resolve()
    if sys.stdout is None or sys.stderr is None:
        logs = args.project / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        stream = (logs / "desktop.log").open("a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = stream
    token = secrets.token_urlsafe(32)
    # Reserve and pass the listening socket to uvicorn: no free-port race.
    sock = socket.socket()
    sock.bind(("127.0.0.1", args.port))
    port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}/?token={token}"
    try:
        app = create_app(args.project, token, start_worker=not args.no_worker)
    except Exception as error:
        sock.close()
        if not args.browser:
            if focus_existing(args.project):
                return
            show_startup_error(error)
        raise
    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="warning", access_log=False, proxy_headers=False
        )
    )
    if args.browser:
        print(f"OpenPhoto: http://127.0.0.1:{port}/", flush=True)
        if args.session_file:
            import json

            args.session_file.parent.mkdir(parents=True, exist_ok=True)
            with args.session_file.open("x", encoding="utf-8") as session:
                json.dump({"url": f"http://127.0.0.1:{port}", "token": token}, session)
        else:
            import webbrowser

            # Open only once the HTTP listener is ready.
            def open_when_ready():
                import time

                for _ in range(200):
                    if server.started:
                        webbrowser.open(url)
                        return
                    time.sleep(0.05)

            threading.Thread(target=open_when_ready, daemon=True).start()
        try:
            server.run(sockets=[sock])
        finally:
            if args.session_file:
                args.session_file.unlink(missing_ok=True)
    else:
        import webview

        thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
        thread.start()
        import time

        instance = None
        bridge = DesktopBridge()
        try:
            for _ in range(200):
                if server.started or not thread.is_alive():
                    break
                time.sleep(0.05)
            if not server.started:
                raise RuntimeError("Не удалось открыть проект. Проверьте журнал и другое окно OpenPhoto.")
            bridge._project = args.project
            bridge._window = webview.create_window(
                "OpenPhoto", url, js_api=bridge, width=1440, height=940,
                min_size=(1000, 680), background_color="#101310",
            )
            bridge._window.events.loaded += bridge._on_loaded
            bridge._window.events.closing += bridge._on_closing
            instance = register_instance(args.project)
            remember_project(args.project)
            webview.start(gui="edgechromium")
        except Exception as error:
            show_startup_error(error)
            raise
        finally:
            server.should_exit = True
            thread.join(timeout=30)
            sock.close()
            if instance:
                forget_instance(instance)
        if bridge._next_project:
            if thread.is_alive():
                raise RuntimeError("Рабочий процесс ещё закрывается. Запустите выбранный проект повторно.")
            command = [sys.executable]
            if not getattr(sys, "frozen", False):
                command += ["-m", "openphoto"]
            command += ["--project", str(bridge._next_project)]
            os.execv(sys.executable, command)


if __name__ == "__main__":
    main()
