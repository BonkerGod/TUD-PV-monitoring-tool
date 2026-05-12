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

def updateloop():
    while(1):
        if datetime.datetime.now().minute % 1 == 0: #When the time is a multiple of 5.\
            print(str(datetime.date.today()))
            try:
                date = str(datetime.date.today())
                adddata(date)
                count_entries("point")
                count_entries('curve')
            except: print("Data could not be added, maybe the file is not yet created or there is an error")
            
        elif (datetime.datetime.now().minute == 5 and datetime.datetime.now().hour == 0): #When time is equal to 1 hour, upload the data from yesterday
            try:
                date = str(datetime.date.today()-datetime.timedelta(days=1))
                adddata(date)
            except: print("Data could not be added, maybe the file is not yet created or there is an error")
        time.sleep(10) # Wait for an 10s and check again. This is done to reduce cpu load, so that it does not check unnecessarily quickly.

def dailyloop():
    while(1):
        if datetime.datetime.now().hour == 15: #At midnight
            try:
                pastdataupload()
            except: print("Data could not be added, maybe the file is not yet created or there is an error")
        time.sleep(5) # Wait for an hour and check again.
             
def pastdataupload():
    start_date = datetime.date(2026, 5, 1)
    for date in (start_date + datetime.timedelta(days=n) for n in range(datetime.date.today().day - start_date.day+1)):
        try:
            adddata(str(date))
            print('hello')
        except: print("Data could not be added, maybe the file is not yet created or there is an error")
             


def adddata(date):
    #date = '2024-12-20' #test
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
    df = pd.read_csv(data_file_path, delimiter=",")
    data = df.to_numpy()
    point_insert = (
        "INSERT INTO pv_point (measurement_time, scheduled_time, module_name, mounted_on, v, i, status_integer, azimuth, inclination, t_air, humidity, dewpoint, relative_pressure, wind_speed, wind_speed_spread, wind_direction, wind_direction_spread, irradiance) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (measurement_time, module_name) DO NOTHING"
    )
    for d in data:
        cur.execute(point_insert, d)
    conn.commit()
    
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
    
    df = pd.read_csv(data_file_path, delimiter=",")
    df["v"] = df["v"].apply(ast.literal_eval)
    df['i'] = df['i'].apply(ast.literal_eval)
    #print(df['v'].iloc[0])
    #print(np.shape(df['v'].iloc[0]))
    #print(type(df["v"].iloc[0]))
    
    data = df.to_numpy()
    curve_insert = (
        "INSERT INTO pv_curve (measurement_time, scheduled_time, measurement_duration, module_name, mounted_on, v, i, azimuth, inclination, t_air, humidity, dewpoint, relative_pressure, wind_speed, wind_speed_spread, wind_direction, wind_direction_spread, irradiance) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (measurement_time, module_name) DO NOTHING"
    )
    for d in data:
        cur.execute(curve_insert, d)
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
            date_time VARCHAR(255),
            scheduled_time VARCHAR(255),
            measurement_duration float,
            module_name VARCHAR(255),
            mounted_on VARCHAR(255),
            v VECTOR(100),
            i VECTOR(100),
            axis_azimuth float,
            axis_tilt float,
            temperature_air float,
            relative_humidity float,
            dew_point float,
            relative_pressure float,
            wind_speed float,
            wind_speed_std float,
            wind_direction float,
            wind_direction_std float,
            irradiance float,
            PRIMARY KEY (measurement_time, module_name))"""
    if type == "point":
        command = """CREATE TABLE pv_point(
            date_time VARCHAR(255),
            scheduled_time VARCHAR(255),
            module_name VARCHAR(255),
            mounted_on VARCHAR(255),
            v float,
            i float,
            status_integer INT,
            axis_azimuth float,
            axis_tilt float,
            temperature_air float,
            relative_humidity float,
            dew_point float,
            relative_pressure float,
            wind_speed float,
            wind_speed_std float,
            wind_direction float,
            wind_direction_std float,
            irradiance float,
            PRIMARY KEY (measurement_time, module_name))"""
    if type == "curve_test":
        command = """CREATE TABLE pv_curve_test(
            measurement_time VARCHAR(255),
            scheduled_time VARCHAR(255),
            measurement_duration VARCHAR(255),
            module_id VARCHAR(255),
            v VECTOR(100),
            i VECTOR(100),
            g float,
            PRIMARY KEY (measurement_time, module_id))"""
    try:
        cur.execute(command)
        print('Table pv_'+type+' succesfully created')
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
        result = df.loc[(df['module_name'].isin(module_name))]
        #print(result)
  
def printtabletype(type):
    cur.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'pv_{type}'")
    columns = cur.fetchall()
    for i in columns:
        print(i)
    conn.commit()
    
def retrievevector():
    cur.execute("SELECT v FROM pv_curve_test")
    vector = cur.fetchall()
    for i in vector:
        print(i)
    conn.commit()


#dailyloop()
downloadtable("export/point.csv", "point", "2024-12-20 16:00:50-07:00", "2024-12-21 16:00:50-07:00", ["My_solar_panel_1", "module_2"])
downloadtable("export/curve.csv", "curve", "2024-12-20 16:00:50-07:00", "2024-12-21 16:00:50-07:00", ["My_solar_panel_1", "module_2"])

conn.close()
