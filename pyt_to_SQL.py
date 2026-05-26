import psycopg2
from psycopg2 import sql
import datetime
import zoneinfo
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
from Weatherdb_to_pyth import download_weather_last24hours, mysql_init, mysql_close, weather_last, weather_all

def init():
    """This program sets the entire program up. 
    It opens the config file, it loads the datapath and established the connection with the postgreSQL db and the MySQL db.

    Returns:
        conn: The connection to the PostgreSQL database
        cur: The cursor for the PostgreSQL database
        mysql_conn: The connection to the MySQL database
        mysql_cur: The cursor for the MySQL database
        config (dict): The measurement config
        data_path_base: The base location of the files. 
    """
    # Open the documents with all the instructions.
    with open('opet-supervisor-config.json') as f:
        opet_supervisor_config = json.load(f)
    data_path_base = Path(opet_supervisor_config['data_path_base'])
    config_path = Path(opet_supervisor_config['config_path'])
    with open(config_path / 'measurement_config.json') as f:
        config = json.load(f)

    # Make connection with the PostgreSQL database.
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
    
    # Make connection to the MySQL database.
    try:
        mysql_conn, mysql_cur = mysql_init()
    except:
        print('Weather database not connected succesfully')

    # Create pgvector extension if it doesn't exist
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        conn.commit()
        print("pgvector extension loaded")
    except Exception as e:
        print(f"Could not create pgvector extension: {e}")
        print("Make sure pgvector is installed in PostgreSQL")
        
    return conn, cur, mysql_conn, mysql_cur, config, data_path_base


def update_loop():
    """ This loop adds newly collected data to the database every 10s."""
    conn, cur, mysql_conn, mysql_cur, config, data_path_base = init()
    while(1):
        #print(str(datetime.date.today()))
        try:
            date = str(datetime.date.today())
            add_data(date, conn, cur ,mysql_conn , mysql_cur, config, data_path_base)
            count_entries("pv_point", conn, cur)
            count_entries('pv_curve', conn, cur)
        except: print("Data could not be added, maybe the file is not yet created or there is an error")
        
        try:
            add_weather_data(download_weather_last24hours(1, mysql_conn, mysql_cur))
        except:
            print('Weather data could not be added')
        
        if (datetime.datetime.now().minute == 5 and datetime.datetime.now().hour == 0): 
            try:
                date = str(datetime.date.today()-datetime.timedelta(days=1))
                add_data(date, conn, cur, mysql_conn, mysql_cur, config, data_path_base)
            except: print("Data could not be added, maybe the file is not yet created or there is an error")
        time.sleep(10) # Wait for an 10s and check again.
    db_close(conn)

def daily_loop():
    """ This loop uploads past data at midnight so that data that was missed still gets uploaded.
        It also checks for errors in the system.
    """
    conn, cur, mysql_conn, mysql_cur, config, data_path_base = init()
    while(1):
        if datetime.datetime.now().hour == 0: #At midnight
            try:
                past_data_upload(conn, cur, mysql_conn, mysql_cur, config, data_path_base)
            except: print("Data could not be added, maybe the file is not yet created or there is an error")
            
            try:
                error_detect(conn, cur, config)
            except Exception as e:
                print(f"Error detection failed with error: {e}")
        time.sleep(60*60*1) # Wait for an hour and check again.
    db_close(conn)    
    
       
def past_data_upload(conn, cur, mysql_conn, mysql_cur, config, data_path_base):
    """ This function adds all the data to the database from the past starting a the start_date.

    Args:
        conn (_type_): The connection to the PostgreSQL database
        cur (_type_): The cursor for the PostgreSQL database
        mysql_conn (_type_): The connection to the MySQL database
        mysql_cur (_type_): The cursor for the MySQL database
        config (dict): The measurement config
        data_path_base (_type_): The base location of the files. 
    """
    start_date = datetime.date(2026, 5, 20)
    for date in (start_date + datetime.timedelta(days=n) for n in range((datetime.date.today() - start_date + datetime.timedelta(days=1)).days)):
        try:
            add_data(str(date), conn, cur, mysql_conn, mysql_cur , config, data_path_base)
        except: print("Data could not be added, maybe the file is not yet created or there is an error")
    try:    
        add_weather_data(weather_all(start_date, mysql_conn, mysql_cur), conn, cur)
    except:
        print('Could not add the weather data')
             


def add_data(date, conn, cur, mysql_conn, mysql_cur, config, data_path_base):
    """ Adds the data on a specifc date to the 

    Args:
        date (string): The date for which the data has to be added, example: "2026-05-20"
        conn (_type_): The connection to the PostgreSQL database
        cur (_type_): The cursor for the PostgreSQL database
        mysql_conn (_type_): The connection to the MySQL database
        mysql_cur (_type_): The cursor for the MySQL database
        config (dict): The measurement config
        data_path_base (_type_): The base location of the files. 
    """
    print(date)
    
    # Every time new measurement data gets added first for a new module has to be checked.
    add_module_data(config, conn, cur)
    
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
    
    
    df['weather_id'] = None # add weather_id column with None values, this is done because the weather data is not always available, so the weather_id will be added later when the weather data is available, and by adding the column with None values, the data can still be added to the database without having to worry about missing weather data.
    newest = weather_last(mysql_conn, mysql_cur)
    df['date_time']=pd.to_datetime(df['date_time'])
    df['scheduled_time'] = pd.to_datetime(df['scheduled_time'])
    UTC_PLUS_2 = datetime.timezone(datetime.timedelta(hours=2))
    newest_time = pd.to_datetime(newest[1]).replace(tzinfo=UTC_PLUS_2)
    if (df['date_time'] < newest_time + datetime.timedelta(minutes=5)).any():   #Only add data when there is a weather id from the previous 5 minutes.
        df['weather_id']=newest[0]
    
    
    data = df.to_numpy()
    point_insert = (
        "INSERT INTO pv_point (date_time, scheduled_time, module_name, mounted_on, v, i, status_integer, temperature_cell, axis_azimuth, axis_tilt, weather_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (date_time, module_name) DO NOTHING"
    )
    for d in data:
        cur.execute(point_insert, d)
    conn.commit()
    
    # Curve data add
    #Open document
    data_file_path = (
        data_path / (
        'opet_results_'
        + 'curve'
        + '_' + date
        + '.csv'
        )
    )
    df = pd.read_csv(data_file_path, delimiter=",")
    
    #From string to vector
    df["v"] = df["v"].apply(ast.literal_eval)
    df['i'] = df['i'].apply(ast.literal_eval)
    
    #Assigning weather_id to the last weather measurement in the last 5 minutes.
    df['weather_id'] = None
    newest = weather_last(mysql_conn, mysql_cur)
    df['date_time']=pd.to_datetime(df['date_time'])
    df['scheduled_time'] = pd.to_datetime(df['scheduled_time'])    
    UTC_PLUS_2 = datetime.timezone(datetime.timedelta(hours=2))
    newest_time = pd.to_datetime(newest[1]).replace(tzinfo=UTC_PLUS_2)
    if (df['date_time'] < newest_time + datetime.timedelta(minutes=5)).any():   
        df['weather_id']=newest[0]
    
    # Insert the curve data into the database
    data = df.to_numpy()
    curve_insert = (
        "INSERT INTO pv_curve (date_time, scheduled_time, measurement_duration, module_name, mounted_on, v, i, iv_status_integer, temperature_cell, axis_azimuth, axis_tilt, weather_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (date_time, module_name) DO NOTHING"
    )
    for d in data:
        cur.execute(curve_insert, d)
    conn.commit()
    
def add_module_data(config, conn, cur):
    """ Adds the module data to the modules table

    Args:
        config (dict): The measurement config
        conn (_type_): The connection to the PostgreSQL database
        cur (_type_): The cursor for the PostgreSQL database
    """
    for module in config['modules']:
        module_insert = (
            "INSERT INTO modules (module_name, tracer, username, user_email, area, technology, manufacturer) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (module_name) DO NOTHING" # If there is already a module with the same name, the data will not be added.
        )
        cur.execute(module_insert, (module['module_name'], module['tracer'], module['username'], module['user_email'], module['area'], module['technology'], module['manufacturer']))

def add_weather_data(weather_data, conn, cur):
    """ Add the weather data collected to the weather table

    Args:
        weather_data (list): The weather data is to be added to the database
        conn (_type_): The connection to the PostgreSQL database
        cur (_type_): The cursor for the PostgreSQL database
    """
    weather_insert = (
        "INSERT INTO weather (weather_id, weather_time, temperature_air, relative_humidity, dew_point, relative_pressure, wind_speed, wind_speed_std, wind_direction, wind_direction_std, irradiance) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (weather_id) DO NOTHING"
    )
    df = pd.DataFrame(weather_data, columns=['weather_id', 'weather_time', 'temperature_air', 'relative_humidity', 'dew_point', 'relative_pressure', 'wind_speed', 'wind_speed_std', 'wind_direction', 'wind_direction_std', 'irradiance', 'IrrDirect', 'IrrDiffused', 'ETotal', 'EDirect', 'EDiffused'])
    df = df.drop(['IrrDirect', 'IrrDiffused', 'ETotal', 'EDirect', 'EDiffused'], axis=1) # drop the columns that are not needed.
    for d in df:
        cur.execute(weather_insert, d) # the first column is the weather_id which is automatically generated by the database and is not needed to be added.
    conn.commit()


def count_entries(type, conn, cur):
    """ Count the entries in a specific table

    Args:
        type (string): The table type, example: 'pv_point'
        conn (_type_): The connection to the PostgreSQL database
        cur (_type_): The cursor for the PostgreSQL database
    """
    cur.execute("SELECT COUNT(*) FROM "+type)
    count = cur.fetchall()
    for i in count:
        print(i)
    conn.commit()


def print_table(type, conn, cur):
    """ Prints a specific table

    Args:
        type (string): The table type, example: 'pv_point'
        conn (_type_): The connection to the PostgreSQL database
        cur (_type_): The cursor for the PostgreSQL database
    """
    cur.execute("SELECT * FROM "+type)
    table_pv = cur.fetchall()
    for i in table_pv:
        print(i)
    conn.commit()
    
def create_table(type, conn, cur):
    """ Creates a table of a specific type
    
    Args:
        type (string): The table type, example: 'pv_point'
        conn (_type_): The connection to the PostgreSQL database
        cur (_type_): The cursor for the PostgreSQL database
    """   
    
    
    if type == "pv_curve":
        command = """CREATE TABLE pv_curve(
            date_time TIMESTAMP WITH TIME ZONE,
            scheduled_time TIMESTAMP WITH TIME ZONE,
            measurement_duration float,
            module_name VARCHAR(255),
            mounted_on VARCHAR(255),
            v VECTOR(100),
            i VECTOR(100),
            iv_status_integer INT,
            temperature_cell float,
            axis_azimuth float,
            axis_tilt float,
            weather_id int,
            constraint fk_module FOREIGN KEY (module_name) REFERENCES modules(module_name),
            UNIQUE (date_time, module_name))"""
            #  constraint fk_weather FOREIGN KEY (weather_id) REFERENCES pv_Weather(weather_id),
    if type == "pv_point":
        command = """CREATE TABLE pv_point(
            date_time TIMESTAMP WITH TIME ZONE,
            scheduled_time TIMESTAMP WITH TIME ZONE,
            module_name VARCHAR(255),
            mounted_on VARCHAR(255),
            v float,
            i float,
            status_integer INT,
            temperature_cell float,
            axis_azimuth float,
            axis_tilt float,
            weather_id int,
            constraint fk_module FOREIGN KEY (module_name) REFERENCES modules(module_name),
            UNIQUE (date_time, module_name))"""
            #   constraint for the module_name means that module_name must be present in the modules table to be able to add data.
            #   constraint fk_weather FOREIGN KEY (weather_id) REFERENCES weather(weather_id), 
    if type == "pv_curve_test":
        command = """CREATE TABLE pv_curve_test(
            date_time TIMESTAMP WITH TIME ZONE,
            scheduled_time TIMESTAMP WITH TIME ZONE,
            measurement_duration float,
            module_name VARCHAR(255),
            mounted_on VARCHAR(255),
            v VECTOR(100),
            i VECTOR(100),
            iv_status_integer INT,
            temperature_cell float,
            axis_azimuth float,
            axis_tilt float,
            weather_id int,
            constraint fk_module FOREIGN KEY (module_name) REFERENCES modules(module_name),
            UNIQUE (date_time, module_name))"""
            #  constraint fk_weather FOREIGN KEY (weather_id) REFERENCES pv_Weather(weather_id),
    if type == "pv_point_test":
        command = """CREATE TABLE pv_point_test(
            date_time TIMESTAMP WITH TIME ZONE,
            scheduled_time TIMESTAMP WITH TIME ZONE,
            module_name VARCHAR(255),
            mounted_on VARCHAR(255),
            v float,
            i float,
            status_integer INT,
            temperature_cell float,
            axis_azimuth float,
            axis_tilt float,
            weather_id int,
            constraint fk_module FOREIGN KEY (module_name) REFERENCES modules(module_name),
            UNIQUE (date_time, module_name))"""
            #   constraint for the module_name means that module_name must be present in the modules table to be able to add data.
            #   constraint fk_weather FOREIGN KEY (weather_id) REFERENCES weather(weather_id), 
            #   have removed it, because if the weather key would be missing the data would not be added, and this is not desired, because the weather data is not always available.
            #   By removing the foreign key constraint, the data will still be added, even if the weather data is missing.
    if type == "weather":
        command = """CREATE TABLE weather(
            weather_id int PRIMARY KEY,
            weather_time TIMESTAMP WITH TIME ZONE UNIQUE,
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
        print('Table '+type+' succesfully created')
    except Exception as e:
        conn.rollback()
        print(f"Table already exists or error: {e}")
    
def delete_table(type, conn, cur):
    """ Deletes an entire table and its contents. This cannot be undone and the table must recreated from scratch

    Args:
        type (string): The table type, example: 'pv_point'
        conn (_type_): The connection to the PostgreSQL database
        cur (_type_): The cursor for the PostgreSQL database
    """
    try:
        cur.execute("DROP TABLE "+type+ " CASCADE")
        conn.commit()
        print("Table "+type+" succesfully deleted")
    except Exception as e:
        conn.rollback()
        print(f"Delete failed (table may not exist): {e}")


#File: ADDRESS LOCATION AND TYPE.   type: mearuements type.     datetime: put in datetime in "2024-12-20 16:00:50-07:00" to filter the moments.     module_names (array): only get the name of the modules.
def download_table(file, type, datetime1, datetime2, module_name, conn, cur):
    """This function gives the ability to download the data from the database with filters over time and over modules.

    Args:
        file (csv): 'file_name.csv'
        type (string): Measurement type: 'pv_point' or 'pv_curve'.
        datetime1 (string): start datetime in string, example: "2024-12-20 16:00:50-07:00".
        datetime2 (string): end datetime in string, example: "2026-12-20 16:00:50-07:00".
        module_name (list or string): List of the modules selected.
        conn (_type_): Connection to the PostgreSQL database.
        cur (_type_): cursor for the PostgreSQL database.
    """

    dt1 = datetime.datetime.fromisoformat(datetime1)
    dt2 = datetime.datetime.fromisoformat(datetime2)
    query = sql.SQL("COPY (SELECT * FROM " +type+ " LEFT JOIN weather ON "+type+".weather_id = weather.weather_id WHERE scheduled_time > %s AND scheduled_time < %s) TO STDOUT WITH DELIMITER ',' CSV HEADER ")
    with open(file, 'w') as f:
        formatted_query = cur.mogrify(query, [dt1,dt2]).decode('utf-8')
        cur.copy_expert(formatted_query, f)
    df = pd.read_csv(file)
    df['scheduled_time'] = pd.to_datetime(df['scheduled_time'])
    df.drop('weather_id.1', axis=1, inplace=True) # Drop the double weahter_id column
    #print(df['scheduled_time'])
    #print(datetime.datetime.fromisoformat(datetime1))
    # print(df.dtypes)
    #result = df.loc[(df['scheduled_time'] >= str(datetime.datetime.fromisoformat(datetime1))) & (df["scheduled_time"]<= str(datetime.datetime.fromisoformat(datetime2)))]
    result = df.loc[(df['module_name'].isin(module_name))]
    print(result)
    result.to_csv(file, index=False)
  
def print_table_type(type, conn, cur):
    """ Prints the types of each column of a specific table.

    Args:
        type (string): The table type, example: 'pv_point
        conn (_type_): The connection to the PostgreSQL database
        cur (_type_): The cursor for the PostgreSQL database
    """
    
    cur.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{type}'")
    columns = cur.fetchall()
    for i in columns:
        print(i)
    conn.commit()
    
def retrieve_vector(conn, cur):
    """ Retrieves the voltage vector of the pv_curve

    Args:
        conn (_type_): The connection to the PostgreSQL database
        cur (_type_): The cursor for the PostgreSQL database
    """
    cur.execute("SELECT v FROM pv_curve")
    vector = cur.fetchall()
    for i in vector:
        print(i)
    conn.commit()
    
def send_mail(error, config, receiver_email = ''):
    """ Send an email with a specific message to a specific person and to admins.

    Args:
        error (string): The message that you want to send
        config (dict): The measurement config to load the setup.
        receiver_email (str, optional): additional emailaddress to send an email to. Defaults to ''.
    """
    
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
        
def error_detect(conn, cur, config):
    """ This function detects error in the system such as: problems with the entire system and issues per module. 
        When it has detected a problem it sends an email.
    
    Args:
        conn (_type_): The connection to the PostgreSQL database
        cur (_type_): The cursor for the PostgreSQL database
        config (dict): The measurement config to load the setup.
    """
    point_measurements = True
    curve_measurements = True
    # Check if data is being collected, if not send an email to the admin.
    cur.execute("SELECT date_time FROM pv_point ORDER BY date_time DESC LIMIT 1")
    last_entry_point = cur.fetchone()[0]
    cur.execute("SELECT date_time FROM pv_curve ORDER BY date_time DESC LIMIT 1")
    last_entry_curve = cur.fetchone()[0]
    print(last_entry_curve)
    print(datetime.datetime.now(zoneinfo.ZoneInfo("Europe/Amsterdam")))
    
    # Check if curve and/or point measurements are being received
    if ((last_entry_point < (datetime.datetime.now(zoneinfo.ZoneInfo("Europe/Amsterdam")) - datetime.timedelta(days=1))) and 
        (last_entry_curve < (datetime.datetime.now(zoneinfo.ZoneInfo("Europe/Amsterdam")) - datetime.timedelta(days=1)))):
        send_mail('The PV monitoring system has not received data from both point and curve measurements in the past 24 hours \n' 
                 +'Most recent data from point measurements: ' + str(last_entry_point) 
                 +'\nMost recent data from curve measurements: ' + str(last_entry_curve), config
                 )
        point_measurements = False
        curve_measurements = False       
    elif last_entry_point < (datetime.datetime.now(zoneinfo.ZoneInfo("Europe/Amsterdam")) - datetime.timedelta(days = 1)):
        send_mail('The PV monitoring system database has not received data from point measurements in the past 24 hours \n'
                 +'Most recent data from point measurements: ' 
                 + str(last_entry_point), config
                 )
        point_measurements = False
    elif last_entry_curve < (datetime.datetime.now(zoneinfo.ZoneInfo("Europe/Amsterdam")) - datetime.timedelta(days=1)):
        send_mail('The PV monitoring system database has not received data from curve measurements in the past 24 hours.\n'
                 +'Most recent data from curve measurements: ' 
                 + str(last_entry_curve), config
                 )
        curve_measurements = False

    # If data is collected check whether the OPETs are suffering from errors, ie status_integer is not 1. 
    # If there are errors, send an email to the user of the OPET and the admin.
    # Send the number of errors in the last 24 hours and the total number of measurements in the last 24 hours.
    for module in config['modules']: 
        print(module['module_name'])
        cur.execute("SELECT date_time, status_integer FROM pv_point WHERE date_time > %s AND module_name = %s ORDER BY date_time DESC", 
                    (str(datetime.datetime.now() - datetime.timedelta(days=1)),) + (module['module_name'],)
                    )
        last_24h = cur.fetchall()
        errorcount = 0
        for i in range(len(last_24h)):
            if last_24h[i][1] != 1:
                errorcount += 1
        if errorcount > 0: # if there is at least one error in the last 24 hours, send an email
            if module['disabled'] == False:
                send_mail(module['module_name']+' Has had an error in the past 24 hours, please check the system. \n'
                         +str(errorcount)+' of '+str(len(last_24h))
                         +' measurements have had an error in the past 24 hours', config, module['user_email']
                         )
        
        # Check whether the gets collected from the individual modules
        if module['disabled'] == False:
            cur.execute("SELECT date_time FROM pv_point WHERE module_name = %s ORDER BY date_time DESC LIMIT 1", (module['module_name'],))
            last_entry_point = cur.fetchone()[0]
            cur.execute("SELECT date_time FROM pv_curve WHERE module_name = %s ORDER BY date_time DESC LIMIT 1", (module['module_name'],))
            last_entry_curve = cur.fetchone()[0]
            if (last_entry_point < (datetime.datetime.now(zoneinfo.ZoneInfo("Europe/Amsterdam")) - datetime.timedelta(days=1)) 
                and last_entry_curve < (datetime.datetime.now(zoneinfo.ZoneInfo("Europe/Amsterdam")) - datetime.timedelta(days=1)) 
                and point_measurements == True and curve_measurements == True):
                send_mail(module['module_name']+' on tracer:'+module['tracer']
                         + ' has not received data from both point and curve measurements in the past 24 hours \n' 
                         + 'Most recent data from point measurements: ' 
                         + str(last_entry_point)
                         + '\nMost recent data from curve measurements: ' 
                         + str(last_entry_curve), 
                         config, module['user_email']
                         )
            elif (last_entry_point < (datetime.datetime.now(zoneinfo.ZoneInfo("Europe/Amsterdam")) - datetime.timedelta(days=1)) and 
                  point_measurements == True):
                send_mail(module['module_name']+' on tracer:'+module['tracer']
                         + ' has not received data from point measurements in the past 24 hours \nMost recent data from point measurements: ' 
                         + str(last_entry_point), 
                         config, module['user_email']
                         )
            elif (last_entry_curve < (datetime.datetime.now(zoneinfo.ZoneInfo("Europe/Amsterdam")) - datetime.timedelta(days=1)) and 
                  curve_measurements == True):
                send_mail(module['module_name']+' on tracer:'+module['tracer'] 
                         + ' has not received data from curve measurements in the past 24 hours\nMost recent data from curve measurements: ' 
                         + str(last_entry_curve), 
                         config, module['user_email']
                         )

def data_tester(conn, cur):
    curve_insert = (
            "INSERT INTO weather (weather_time, temperature_air, relative_humidity, dew_point, relative_pressure, wind_speed, wind_speed_std, wind_direction, wind_direction_std, irradiance) "
            "VALUES ('2026-05-18T10:05:50.028240+02:00', 23, 53, 10, 4, 10, 3, 360, 35, 400) "
            "ON CONFLICT (weather_time) DO NOTHING"
            )
    cur.execute(curve_insert)
    conn.commit()
    
    curve_insert = (
            "INSERT INTO modules (module_name, tracer, username, user_email, area, technology, manufacturer) "
            "VALUES ('My_solar_panel_1', 'O001', 'Wessel_Oosterkamp', 'woostekamp@tudelft.nl', 1.7, 'Monocrystalline', 'Longli') "
            "ON CONFLICT (module_name) DO NOTHING"
            )
    cur.execute(curve_insert)
    conn.commit()
    
    curve_insert = (
            "INSERT INTO pv_point_test (date_time, scheduled_time, module_name, mounted_on, v, i, status_integer, axis_azimuth, axis_tilt, weather_id) "
            "VALUES ('2026-05-19T10:05:50.028240+02:00','2026-05-18T10:05:50+02:00','My_solar_panel_1','Egis-tracker',-0.000303534,8.00177e-07,1,180,30,5) "
            "ON CONFLICT (date_time, module_name) DO NOTHING"
            )
    cur.execute(curve_insert)
    conn.commit()

def db_close(conn):
    """ Close the connection with the PostgreSQL database

    Args:
        conn (_type_): The connection to the PostgreSQL database
    """
    conn.close()

conn, cur, mysql_conn, mysql_cur, config, data_base_path = init()
add_data("2026-05-20", conn, cur, mysql_conn, mysql_cur, config, data_base_path)

db_close(conn)
