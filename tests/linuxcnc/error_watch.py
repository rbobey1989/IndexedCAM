#!/usr/bin/env python3
"""Print every LinuxCNC error to a file, for the automated checks.

The interpreter reports problems (zero feed rate, travel limits, bad modal
state) through the NML error channel, not through stdout, so a check that only
looks at the log thinks a broken program passed.

    python3 tests/linuxcnc/error_watch.py /tmp/errors.txt configs/linuxcnc/indexedcam.nml

Runs until it is killed; each line it writes is an error the controller raised.
The NML file must be the one the running machine uses (``[EMC]NML_FILE``),
otherwise the module talks to a different set of buffers and sees nothing.
"""

from __future__ import annotations

import sys
import time


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/indexedcam_errors.txt"
    nml = sys.argv[2] if len(sys.argv) > 2 else ""
    poll = float(sys.argv[3]) if len(sys.argv) > 3 else 0.1
    import linuxcnc

    if nml:
        linuxcnc.nmlfile = nml
    channel = linuxcnc.error_channel()
    with open(path, "w", buffering=1) as out:
        while True:
            error = channel.poll()
            while error:
                kind, text = error
                out.write("{} {}\n".format("error" if kind == linuxcnc.OPERATOR_ERROR else kind, text))
                error = channel.poll()
            time.sleep(poll)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
