import mysql.connector

conn = mysql.connector.connect(
    host="100.98.143.82",
    user="OPET",
    password="npjust",
    database="pvmonitoring",
    port=3306                   # default MySQL port
)

cursor = conn.cursor()
# cursor.execute("SELECT * FROM results;")
# print(cursor.fetchone())

cursor.execute("SELECT * FROM results LIMIT 5;")
for row in cursor:
    print(row)

conn.close()