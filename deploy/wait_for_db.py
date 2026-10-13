"""Wait for Supabase to be reachable after a persistent timer fires at boot.

The user systemd manager's network-online.target does not track the system's
Wi-Fi state; both scheduled jobs can start before DNS is configured.
"""
import os
import sys
import time

import psycopg2


def wait_for_database(dsn, timeout=300, interval=5, *, connect=psycopg2.connect,
                      clock=time.monotonic, pause=time.sleep):
    deadline = clock() + timeout
    while True:
        try:
            conn = connect(dsn, connect_timeout=5)
        except (psycopg2.OperationalError, OSError):
            remaining = deadline - clock()
            if remaining <= 0:
                raise TimeoutError("database unavailable after network wait") from None
            pause(min(interval, remaining))
        else:
            conn.close()
            return True


if __name__ == "__main__":
    try:
        wait_for_database(os.environ["DATABASE_URL"])
    except TimeoutError as exc:
        print(f"PLAZA preflight: {exc}", file=sys.stderr)
        sys.exit(1)
