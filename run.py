"""Opens the PeerCheck menu, as `python run.py` did in CONF_Submission_Checker_Suite."""

import sys

from peercheck.cli import main

if __name__ == "__main__":
    sys.exit(main(["menu"]))
