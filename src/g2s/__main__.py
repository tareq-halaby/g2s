"""Module entry point for `python -m g2s`."""

import sys
from g2s.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
