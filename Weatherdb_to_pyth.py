import mysql.connector
import datetime
import pandas as pd


def mysql_init():
    try:
        conn = mysql.connector.connect(
            host="100.98.143.82",
            user="OPET",
            password="npjust",
            database="pvmonitoring",
            port=3306                   # default MySQL port
        )

        cursor = conn.cursor()
        print('Succesfully connected to mysql db')
        return conn, cursor
    except:
        print('Failed to connect to mysql db')
# cursor.execute("SELECT * FROM results;")
# print(cursor.fetchone())

# cursor.execute("SELECT * FROM weather ORDER BY RecTime DESC LIMIT 5 ;")
# for row in cursor:
#     print(row)
    
def download_weather_last24hours(days, conn, cursor):
    cursor.execute("SELECT * FROM weather WHERE RecTime > %s;", (datetime.datetime.now() - datetime.timedelta(days=days),))
    weather_data = cursor.fetchall()
    # for row in weather_data:
    #     print(row)
    
    return weather_data

def weather_last(conn, cursor):
    cursor.execute("SELECT idWeather, RecTime FROM weather ORDER BY RecTime DESC LIMIT 1")
    last = cursor.fetchone()
    return last

#still finish this
def weather_all(startdate, conn, cursor):
    cursor.execute("SELECT * FROM weather WHERE RecTime > %s;", (pd.to_datetime(startdate),))
    data = cursor.fetchall()
    return data
    
def mysql_close(conn):
    conn.close()
    