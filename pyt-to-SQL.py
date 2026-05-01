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
cur.execute("\copy pv(measurement_time, scheduled_time, module_id, v, i, g, t_ext, status_integer) FROM 'C:/Users/wesse/OneDrive/Documenten/Tu Delft/EE3P1/Database/SQL/pv.csv' DELIMITER ';' CSV HEADER")
conn.commit()
cur.execute("SELECT COUNT(*)")
conn.commit()
cur.execute("SELECT * FROM pv")
conn.commit()
conn.close()
