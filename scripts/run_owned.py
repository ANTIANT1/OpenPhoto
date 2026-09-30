"""Run a verification command with automatic cleanup of its entire process tree."""

import subprocess
import sys

from openphoto.processes import OwnedProcesses, configure_threads

configure_threads()
with OwnedProcesses() as owner:
    process = owner.popen(sys.argv[1:], stdout=sys.stdout, stderr=sys.stderr)
    try:
        code = process.wait(timeout=3600)
    except subprocess.TimeoutExpired:
        code = 124
raise SystemExit(code)
