import psycopg2
import datetime
import json
from pathlib import Path

with open('opet-supervisor-config.json') as f:
    opet_supervisor_config = json.load(f)
data_path_base = Path(opet_supervisor_config['data_path_base'])
config_path = Path(opet_supervisor_config['config_path'])
with open(config_path / 'measurement_config.json') as f:
    config = json.load(f)


DB_NAME = "postgres"
DB_USER = "postgres"
DB_PASS = "1234"
DB_HOST = "localhost"
DB_PORT = "5432"

try:
    conn = psycopg2.connect(database=DB_NAME,
                            user =DB_USER,
                            password=DB_PASS,
                            host=DB_HOST,
                            port=DB_PORT)
    print("Database connected succefully")
except:
    print("Database not connected succesfully")
    
cur = conn.cursor()


def adddata():
    today = datetime.date.today()
    date = str(today-datetime.timedelta(days=1))
    print(date)
    data_path = data_path_base / date / config['data_destination']
    data_file_path = (
        data_path / (
        'opet_results_'
        + 'point'
        + '_' + date
        + '.csv'
        )
    )
    #with open(data_file_path) as f:
    with open("C:/Users/wesse/OneDrive/Documenten/Tu Delft/EE3P1/Database/SQL/pv.csv") as f:
        cur.copy_expert("COPY pv(measurement_time, scheduled_time, module_id, v, i, g, t_ext, status_integer) FROM STDIN WITH DELIMITER';' HEADER CSV", f)

    conn.commit()

def count_entries():
    cur.execute("SELECT COUNT(*) FROM pv")
    count = cur.fetchall()
    for i in count:
        print(i)
    conn.commit()


def printtable():
    cur.execute("SELECT * FROM pv")
    table_pv = cur.fetchall()
    for i in table_pv:
        print(i)
    conn.commit()

count_entries()
adddata()
count_entries()
conn.close()
