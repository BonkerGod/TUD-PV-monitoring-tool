import psycopg2
import datetime
import time
import json
from pathlib import Path
import numpy as np
import pandas as pd
import ast
from dateutil import parser
import pgvector.psycopg2
from sqlalchemy import create_engine

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

# Create pgvector extension if it doesn't exist
try:
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    conn.commit()
    print("pgvector extension loaded")
except Exception as e:
    print(f"Could not create pgvector extension: {e}")
    print("Make sure pgvector is installed in PostgreSQL")

#print(datetime.datetime.now().hour)

def dailyloop():
     while(1):
        if print(datetime.datetime.now().hour)==1: #When time is equal to 1 hour, upload the data from yesterday
            adddata()
        time.sleep(1*60*60) # Wait for an hour and check again. This is done to reduce cpu load, so that it does not check unnecessarily quickly.
             
             
             


def adddata():
    today = datetime.date.today()
    date = str(today-datetime.timedelta(days=1)) #upload the data of the day before
    date = '2024-12-20' #test
    print(date)
    data_path = data_path_base / date / config['data_destination']
    
    #point data add
    data_file_path = (
        data_path / (
        'opet_results_'
        + 'point'
        + '_' + date
        + '.csv'
        )
    )
    #with open(data_file_path) as f:
    #with open("C:/Users/wesse/OneDrive/Documenten/Tu Delft/EE3P1/Database/SQL/pv.csv") as f: #test
        #cur.copy_expert("COPY pv_point(measurement_time, scheduled_time, module_id, v, i, g, t_ext, status_integer) FROM STDIN WITH DELIMITER',' HEADER CSV", f)
    
    #curve data add
    data_file_path = (
        data_path / (
        'opet_results_'
        + 'curve'
        + '_' + date
        + '.csv'
        )
    )
    
    # Could not get the string away, but this may be for the better, because postgres expects array in {} and not in [].
    df = pd.read_csv("example-data/2024-12-20/config_2024-12-20T15-16-00/opet_results_curve_2024-12-20.csv", delimiter=",")
    # print(df['v'].iloc[0])
    # print(type(df['v'].iloc[0]))
    df["v"] = df["v"].apply(ast.literal_eval)
    df['i'] = df['i'].apply(ast.literal_eval)
    print(df['v'].iloc[0])
    print(np.shape(df['v'].iloc[0]))
    print(type(df["v"].iloc[0]))
    #df.to_sql("pv_curve_test", conn, if_exists='append', index=False)
    #df.to_json("example-data/2024-12-20/config_2024-12-20T15-16-00/opet_results_curve2_2024-12-20.json", orient="records", lines=True)
    
    # with open(data_file_path) as f:
    # #with open("example-data/2024-12-20/config_2024-12-20T15-16-00/opet_results_curve2_2024-12-20.csv") as f: #test
    #     #cur.copy_expert("COPY pv_curve(measurement_time, scheduled_time, measurement_duration, module_name, mounted_on, v,i, azimuth, inclination, t_air, humidity, dewpoint, relative_pressure, wind_speed, wind_speed_spread, wind_direction, wind_direction_spread, irradiance) FROM STDIN WITH DELIMITER',' HEADER CSV", f)
    #     cur.copy_expert("COPY pv_curve_test(measurement_time, scheduled_time, measurement_duration, module_id, v, i, g) FROM STDIN WITH DELIMITER',' HEADER CSV", f)
    
    data = df.to_numpy()
    print(data[0])
    for d in data:

        cur.execute("INSERT into pv_curve_test VALUES (%s, %s, %s, %s, %s, %s, %s)", d)
    conn.commit()

def count_entries(type):
    cur.execute("SELECT COUNT(*) FROM pv_"+type)
    count = cur.fetchall()
    for i in count:
        print(i)
    conn.commit()


def printtable(type):
    cur.execute("SELECT * FROM pv_"+type)
    table_pv = cur.fetchall()
    for i in table_pv:
        print(i)
    conn.commit()
    
def createtable(type):
    if type == "curve":
        command = """CREATE TABLE pv_curve(
            measurement_time VARCHAR(255),
            scheduled_time VARCHAR(255),
            measurement_duration VARCHAR(255),
            module_name VARCHAR(255),
            mounted_on VARCHAR(255),
            v VARCHAR(),
            i VARCHAR(),
            azimuth float,
            inclination float,
            t_air float,
            humidity float,
            dewpoint float,
            relative_pressure float,
            wind_speed float,
            wind_speed_spread float,
            wind_direction float,
            wind_direction_spread float,
            irradiance float)"""
    if type == "point":
        command = """CREATE TABLE pv_point(
            measurement_time VARCHAR(255),
            scheduled_time VARCHAR(255),
            module_name VARCHAR(255),
            mounted_on VARCHAR(255),
            v float,
            i float,
            status_integer INT,
            azimuth float,
            inclination float,
            t_air float,
            humidity float,
            dewpoint float,
            relative_pressure float,
            wind_speed float,
            wind_speed_spread float,
            wind_direction float,
            wind_direction_spread float,
            irradiance float)"""
    if type == "curve_test":
        command = """CREATE TABLE pv_curve_test(
            measurement_time VARCHAR(255),
            scheduled_time VARCHAR(255),
            measurement_duration VARCHAR(255),
            module_id VARCHAR(255),
            v VECTOR(100),
            i VECTOR(100),
            g float)"""
    try:
        cur.execute(command)
    except:
        print("Table already exists, could not be created")
    conn.commit()
    
def deletetable(type):
    try:
        cur.execute("""DROP TABLE pv_"""+type)
        print("Table pv_"+type+" succesfully deleted")
    except:
        print("Whoops something went wrong, could not delete")
        
    conn.commit()


#File: ADDRESS LOCATION AND TYPE.   type: mearuements type.     datetime: put in datetime in "2024-12-20 16:00:50-07:00" to filter the moments.     module_names (array): only get the name of the modules.
def downloadtable(file, type, datetime1, datetime2, module_name):
        query = "COPY pv_"+type+" TO STDOUT WITH DELIMITER ',' CSV HEADER "
        with open(file, 'w') as f:
            cur.copy_expert(query, f)
        df = pd.read_csv(file)
        df['scheduled_time'] = pd.to_datetime(df['scheduled_time'])
        # print(df['scheduled_time'])
        # print(df.dtypes)
        result = df.loc[(df['scheduled_time'] >= datetime.datetime.fromisoformat(datetime1)) & (df["scheduled_time"]<= datetime.datetime.fromisoformat(datetime2))]
        result = df.loc[(df['module_id'].isin(module_name))]
        #print(result)
  
  


createtable("curve_test")
adddata()
#printtable("curve_test")
downloadtable("test.json", "curve_test", "2024-12-20 00:00:00-07:00", "2024-12-21 00:00:00-07:00", ["P-0000-01", "module_2"])


conn.close()
