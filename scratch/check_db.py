import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path.cwd()))
from src.db import get_conn
from src.config import load_settings

dsn = "postgresql://postgres:postgres@localhost:5432/lightning_tracker"

def check():
    conn = get_conn(dsn)
    cur = conn.cursor()
    
    print("Checking counts...")
    cur.execute("SELECT kind, count(*) FROM lightning_events GROUP BY kind")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]}")
        
    print("\nChecking latest events...")
    cur.execute("SELECT max(event_time) FROM lightning_events")
    print(f"  Max event_time: {cur.fetchone()[0]}")
    
    print("\nTiming query for last 30 minutes...")
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=30)
    
    t0 = datetime.now()
    cur.execute("SELECT count(*) FROM lightning_events WHERE event_time >= %s AND event_time <= %s AND kind = 'flash'", (start, end))
    count = cur.fetchone()[0]
    t1 = datetime.now()
    print(f"  Flash query took {(t1-t0).total_seconds():.2f}s (count={count})")
    
    cur.close()
    conn.close()

if __name__ == "__main__":
    check()
