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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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
        if datetime.datetime.now().hour == 0: #At midnight
            try:
                pastdataupload()
            except: print("Data could not be added, maybe the file is not yet created or there is an error")
            try:
                errordetect()
            except Exception as e:
                print(f"Error detection failed with error: {e}")
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
    addmoduledata(config)
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
        "INSERT INTO pv_point (date_time, scheduled_time, module_name, mounted_on, v, i, status_integer, axis_azimuth, axis_tilt, temperature_air, relative_humidity, dew_point, relative_pressure, wind_speed, wind_speed_std, wind_direction, wind_direction_std, irradiance) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (date_time, module_name) DO NOTHING"
    )
    for d in data:
        cur.execute(point_insert, d)
    conn.commit()
    
    #with open(data_file_path) as f:
    #with open("C:/Users/wesse/OneDrive/Documenten/Tu Delft/EE3P1/Database/SQL/pv.csv") as f: #test
        #cur.copy_expert("COPY pv_point(date_time, scheduled_time, module_id, v, i, g, t_ext, status_integer) FROM STDIN WITH DELIMITER',' HEADER CSV", f)
    
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
        "INSERT INTO pv_curve (date_time, scheduled_time, measurement_duration, module_name, mounted_on, v, i, axis_azimuth, axis_tilt, temperature_air, relative_humidity, dew_point, relative_pressure, wind_speed, wind_speed_std, wind_direction, wind_direction_std, irradiance) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (date_time, module_name) DO NOTHING"
    )
    for d in data:
        cur.execute(curve_insert, d)
    conn.commit()
    
def addmoduledata(config = config):
    for module in config['modules']:
        module_insert = (
            "INSERT INTO modules (module_name, tracer, username, user_email, area, technology, manufacturer) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (module_name) DO NOTHING"
        )
        cur.execute(module_insert, (module['module_id'], module['tracer'], module['username'], module['user_email'], module['area'], module['technology'], module['manufacturer']))

def count_entries(type):
    cur.execute("SELECT COUNT(*) FROM "+type)
    count = cur.fetchall()
    for i in count:
        print(i)
    conn.commit()


def printtable(type):
    cur.execute("SELECT * FROM "+type)
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
            PRIMARY KEY (date_time, module_name))"""
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
            PRIMARY KEY (date_time, module_name))"""
    if type == "curve_test":
        command = """CREATE TABLE pv_curve_test(
            date_time VARCHAR(255),
            scheduled_time VARCHAR(255),
            measurement_duration float,
            module_name VARCHAR(255),
            mounted_on VARCHAR(255),
            v VECTOR(100),
            i VECTOR(100),
            axis_azimuth float,
            axis_tilt float,
            weather_id int,
            constraint fk_weather FOREIGN KEY (weather_id) REFERENCES pv_Weather(weather_id),
            PRIMARY KEY (date_time, module_name))"""
    if type == "point_test":
        command = """CREATE TABLE pv_point_test(
            date_time VARCHAR(255),
            scheduled_time VARCHAR(255),
            module_name VARCHAR(255),
            mounted_on VARCHAR(255),
            v float,
            i float,
            status_integer INT,
            axis_azimuth float,
            axis_tilt float,
            weather_id int,
            constraint fk_weather FOREIGN KEY (weather_id) REFERENCES weather(weather_id),
            constraint fk_module FOREIGN KEY (module_name) REFERENCES modules(module_name),
            UNIQUE (date_time, module_name))"""
    if type == "weather":
        command = """CREATE TABLE weather(
            weather_id serial PRIMARY KEY,
            date_time varchar(255) UNIQUE,
            temperature_air float,
            relative_humidity float,
            dew_point float,
            relative_pressure float,
            wind_speed float,
            wind_speed_std float,
            wind_direction float,
            wind_direction_std float,
            irradiance float)"""
    if type == "modules":
        command = """CREATE TABLE modules(
            module_name varchar(255) PRIMARY KEY,
            tracer varchar(255),
            username varchar(255),
            user_email varchar(255),
            area float,
            technology varchar(255),
            manufacturer varchar(255))"""
    try:
        cur.execute(command)
        conn.commit()
        print('Table pv_'+type+' succesfully created')
    except Exception as e:
        conn.rollback()
        print(f"Table already exists or error: {e}")
    
def deletetable(type):
    try:
        cur.execute("DROP TABLE "+type+ " CASCADE")
        conn.commit()
        print("Table "+type+" succesfully deleted")
    except Exception as e:
        conn.rollback()
        print(f"Delete failed (table may not exist): {e}")


#File: ADDRESS LOCATION AND TYPE.   type: mearuements type.     datetime: put in datetime in "2024-12-20 16:00:50-07:00" to filter the moments.     module_names (array): only get the name of the modules.
def downloadtable(file, type, datetime1, datetime2, module_name):
        query = "COPY pv_"+type+" TO STDOUT WITH DELIMITER ',' CSV HEADER "
        with open(file, 'w') as f:
            cur.copy_expert(query, f)
        df = pd.read_csv(file)
        df['scheduled_time'] = pd.to_datetime(df['scheduled_time'])
        print(df['scheduled_time'])
        print(datetime.datetime.fromisoformat(datetime1))
        # print(df.dtypes)
        result = df.loc[(df['scheduled_time'] >= str(datetime.datetime.fromisoformat(datetime1))) & (df["scheduled_time"]<= str(datetime.datetime.fromisoformat(datetime2)))]
        result = result.loc[(df['module_name'].isin(module_name))]
        print(result)
        result.to_csv(file, index=False)
  
def printtabletype(type):
    cur.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{type}'")
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
    
def sendmail(error, receiver_email = ''):
    smpt_server = "smtp.gmail.com"
    port = 587
    sender_email = 'wessel.oosterkamp@gmail.com'
    password = 'puxp gwhx zrsa cczv'
    admin = config['admins_email']
    users = receiver_email + ',' + admin
    message = MIMEMultipart()
    message['From'] = sender_email
    message['To'] = users 
    message['Subject'] = 'There is a problem with the PV monitoring system'
    
    body = 'Error: ' + str(error)
    message.attach(MIMEText(body, 'plain'))
    
    try:
        server = smtplib.SMTP(smpt_server, port)
        server.starttls()
        server.login(sender_email, password)
        server.send_message(message)
        print("Email sent successfully")
        server.quit()
    except Exception as e:
        print(f"Error sending email: {e}")
        
def errordetect():
    point_measurements = True
    curve_measurements = True
    #Check if data is being collected, if not send an email to the admin.
    cur.execute("SELECT date_time FROM pv_point ORDER BY date_time DESC LIMIT 1")
    last_entry_point = cur.fetchone()[0]
    print(last_entry_point)
    cur.execute("SELECT date_time FROM pv_curve ORDER BY date_time DESC LIMIT 1")
    last_entry_curve = cur.fetchone()[0]
    print(last_entry_curve)
    if last_entry_point < str(datetime.datetime.now() - datetime.timedelta(days=1)) and (last_entry_curve < str(datetime.datetime.now() - datetime.timedelta(days=1))):
        sendmail('The PV monitoring system has not received data from both point and curve measurements in the past 24 hours \n' +
                'Most recent data from point measurements: ' + last_entry_point +
                '\nMost recent data from curve measurements: ' + last_entry_curve)
        point_measurements = False
        curve_measurements = False
    elif last_entry_point < str(datetime.datetime.now() - datetime.timedelta(days=1)):
        sendmail('The PV monitoring system database has not received data from point measurements in the past 24 hours \nMost recent data from point measurements: ' + last_entry_point)
        point_measurements = False
    elif last_entry_curve < str(datetime.datetime.now() - datetime.timedelta(days=1)):
        sendmail('The PV monitoring system database has not received data from curve measurements in the past 24 hours\nMost recent data from curve measurements: ' + last_entry_curve)
        curve_measurements = False

    #If data is collected check whether the OPETs are suffering from errors, ie status_integer is not 1. If there are errors, send an email to the user of the OPET and the admin.
    for module in config['modules']: 
        #send the number of errors in the last 24 hours and the total number of measurements in the last 24 hours.
        print(module['module_id'])
        cur.execute("SELECT date_time, status_integer FROM pv_point WHERE date_time > %s AND module_name = %s ORDER BY date_time DESC", (str(datetime.datetime.now() - datetime.timedelta(days=1)),) + (module['module_id'],))
        last_24h = cur.fetchall()
        #print(len(last_24h))
        errorcount = 0
        for i in range(len(last_24h)):
            if last_24h[i][1] != 1:
                errorcount += 1
        #print(errorcount)
        if errorcount > 0: # if there is at least one error in the last 24 hours, send an email
            if module['disabled'] == False:
                sendmail(module['module_id']+' Has had an error in the past 24 hours, please check the system. \n'+str(errorcount)+' of '+str(len(last_24h))+' measurements have had an error in the past 24 hours', module['user_email'])
        
        if module['disabled'] == False:
            cur.execute("SELECT date_time FROM pv_point WHERE module_name = %s ORDER BY date_time DESC LIMIT 1", (module['module_id'],))
            last_entry_point = cur.fetchone()[0]
            cur.execute("SELECT date_time FROM pv_curve WHERE module_name = %s ORDER BY date_time DESC LIMIT 1", (module['module_id'],))
            last_entry_curve = cur.fetchone()[0]
            if (last_entry_point < str(datetime.datetime.now() - datetime.timedelta(days=1)) and last_entry_curve < str(datetime.datetime.now() - datetime.timedelta(days=1)) and point_measurements == True and curve_measurements == True):
                sendmail(module['module_id']+' on tracer:'+module['tracer']+ ' has not received data from both point and curve measurements in the past 24 hours \n' +
                'Most recent data from point measurements: ' + last_entry_point +
                '\nMost recent data from curve measurements: ' + last_entry_curve, module['user_email'])
            elif last_entry_point < str(datetime.datetime.now() - datetime.timedelta(days=1)) and point_measurements == True:
                sendmail(module['module_id']+' on tracer:'+module['tracer']+ ' has not received data from point measurements in the past 24 hours \nMost recent data from point measurements: ' + last_entry_point, module['user_email'])
            elif last_entry_curve < str(datetime.datetime.now() - datetime.timedelta(days=1)) and curve_measurements == True:
                sendmail(module['module_id']+' on tracer:'+module['tracer']+ ' has not received data from curve measurements in the past 24 hours\nMost recent data from curve measurements: ' + last_entry_curve, module['user_email'])

def datatester():
    curve_insert = (
            "INSERT INTO weather (date_time, temperature_air, relative_humidity, dew_point, relative_pressure, wind_speed, wind_speed_std, wind_direction, wind_direction_std, irradiance) "
            "VALUES ('2026-05-18T10:05:50.028240+02:00', 23, 53, 10, 4, 10, 3, 360, 35, 400) "
            "ON CONFLICT (date_time) DO NOTHING")
    cur.execute(curve_insert)
    conn.commit()
    
    curve_insert = (
            "INSERT INTO modules (module_name, tracer, username, user_email, area, technology, manufacturer) "
            "VALUES ('My_solar_panel_1', 'O001', 'Wessel_Oosterkamp', 'woostekamp@tudelft.nl', 1.7, 'Monocrystalline', 'Longli') "
            "ON CONFLICT (module_name) DO NOTHING")
    cur.execute(curve_insert)
    conn.commit()
    
    curve_insert = (
            "INSERT INTO pv_point_test (date_time, scheduled_time, module_name, mounted_on, v, i, status_integer, axis_azimuth, axis_tilt, weather_id) "
            "VALUES ('2026-05-19T10:05:50.028240+02:00','2026-05-18T10:05:50+02:00','My_solar_panel_1','Egis-tracker',-0.000303534,8.00177e-07,1,180,30,1) "
            "ON CONFLICT (date_time, module_name) DO NOTHING")
    cur.execute(curve_insert)
    conn.commit()




conn.close()
