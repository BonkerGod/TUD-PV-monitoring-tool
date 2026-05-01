import psycopg2

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


with open("C:/Users/wesse/OneDrive/Documenten/Tu Delft/EE3P1/Database/SQL/pv.csv") as f:
    cur.copy_expert("COPY pv(measurement_time, scheduled_time, module_id, v, i, g, t_ext, status_integer) FROM STDIN WITH DELIMITER';' HEADER CSV", f)

#cur.copy_from(file, 'pv', sep=';', columns=('measurement_time', 'scheduled_time', 'module_id', 'v', 'i', 'g', 't_ext', 'status_integer'))
conn.commit()
cur.execute("SELECT COUNT(*) FROM pv")
count = cur.fetchall()
for i in count:
    print(i)

conn.commit()
cur.execute("SELECT * FROM pv")
table_pv = cur.fetchall()
for i in table_pv:
    print(i)
conn.commit()
conn.close()
