from src import db
from datetime import datetime, timedelta, timezone
import os

dsn = os.environ.get('LIGHTNING_TRACKER_PG_DSN', 'host=127.0.0.1 port=6543 dbname=lightning user=user password=pass')
try:
    with db.get_conn(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute('select count(*) from lightning_events where event_time > %s', (datetime.now(timezone.utc) - timedelta(hours=24),))
            count = cur.fetchone()[0]
            print(f'Events in last 24h: {count}')
            
            cur.execute('select max(event_time) from lightning_events')
            max_time = cur.fetchone()[0]
            print(f'Latest event time: {max_time}')
except Exception as e:
    print(f'Error: {e}')
