"""OS-owned lock: automatically released if the application crashes."""
from pathlib import Path


class ProjectLock:
    def __init__(self, directory, name=".openphoto.lock"):
        self.path = Path(directory) / name
        self.stream = None

    def acquire(self):
        import os
        self.stream = self.path.open("a+b")
        try:
            if self.path.stat().st_size == 0:
                self.stream.write(b"0")
                self.stream.flush()
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            self.stream = None
            raise RuntimeError("Этот проект уже открыт в другом окне OpenPhoto") from None

    def release(self):
        if self.stream:
            self.stream.close()
            self.stream = None
