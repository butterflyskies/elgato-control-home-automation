"""Entry points for GUI components (tray + panel).

Wraps imports to provide helpful errors when GTK4/GI bindings are missing.
"""

from __future__ import annotations

import sys

_GI_HELP = """\
Error: GTK4 bindings (PyGObject) not found.

Install with the gui extra:

  uv tool install 'elgato-keylight[gui]'

PyGObject builds from source and needs GObject Introspection headers and
GTK4/Adwaita typelibs on your system:

  Fedora:  sudo dnf install gobject-introspection-devel cairo-gobject-devel gtk4-devel libadwaita-devel
  Ubuntu:  sudo apt install libgirepository1.0-dev libcairo2-dev pkg-config gir1.2-gtk-4.0 gir1.2-adw-1
  Arch:    sudo pacman -S gobject-introspection gtk4 libadwaita
"""


def tray():
    try:
        from elgato_keylight.tray import main
    except ImportError:
        print(_GI_HELP, file=sys.stderr)
        sys.exit(1)
    main()


def panel():
    try:
        from elgato_keylight.panel import main
    except ImportError:
        print(_GI_HELP, file=sys.stderr)
        sys.exit(1)
    main()
