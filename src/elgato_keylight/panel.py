"""Elgato Key Light control panel — thin wrapper.

If the tray daemon (elgato-tray) is running, this activates it to toggle
the panel. Otherwise, starts a standalone panel (no tray icon).
"""

from __future__ import annotations

import signal


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    from elgato_keylight.tray import ElgatoApp
    app = ElgatoApp(start_tray=False)
    app.run(None)


if __name__ == "__main__":
    main()
