import mysql.connector

conn = mysql.connector.connect(
    host="131.180.192.70",
    user="OPET",
    password="npjust",
    database="pvmonitoring",
    port=3306                   # default MySQL port
)

cursor = conn.cursor()
cursor.execute("SELECT NOW();")
print(cursor.fetchone())