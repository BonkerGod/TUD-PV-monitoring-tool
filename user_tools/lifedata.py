import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "supervisor_tools"))

from pyt_to_SQL import init, db_close
import time

def last_measurement(conn, cur):
    cur.execute("SELECT * FROM pv_point ORDER BY date_time DESC LIMIT 1")
    column = cur.fetchone()
    print(column)
    conn.commit()
    
conn, cur, mysql_conn, mysql_cur = init()
while(1):
    last_measurement(conn, cur)
    time.sleep(3)
db_close(conn, mysql_conn)