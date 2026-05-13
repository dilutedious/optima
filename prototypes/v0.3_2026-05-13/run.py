#!/usr/bin/env python3
"""Launch Optima.

Run from the project root:
    python3 run.py            # native desktop window (pywebview)
    python3 run.py --browser  # open at http://127.0.0.1:5050 in your browser

This shim only exists so users don't have to remember the
`python3 -m app.main` invocation.
"""

from app.main import main

if __name__ == "__main__":
    raise SystemExit(main())
