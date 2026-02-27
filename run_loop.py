#!/usr/bin/env python3
"""
Run predictions every REFRESH_MINUTES. Stop with Ctrl+C.
Usage: python run_loop.py [--minutes 30]
"""
import argparse
import os
import time
import sys
from config import REFRESH_MINUTES

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=REFRESH_MINUTES)
    args = ap.parse_args()
    interval = args.minutes * 60
    print("Refreshing every {} minutes. Ctrl+C to stop.".format(args.minutes))
    import subprocess
    while True:
        try:
            subprocess.run([sys.executable, "main.py"], cwd=PROJECT_ROOT)
        except Exception as e:
            print("Run failed:", e, file=sys.stderr)
        print("\nSleeping {}s...".format(interval))
        time.sleep(interval)

if __name__ == "__main__":
    main()
