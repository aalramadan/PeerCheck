"""Opens the PeerCheck menu, the same as `peercheck menu`."""

import sys

from peercheck.cli import main

if __name__ == "__main__":
    sys.exit(main(["menu"]))
