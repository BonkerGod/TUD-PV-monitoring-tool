# TUD-PV-monitoring-tool
PV monitoring tool for the TU Delft. It makes use of the OPET modules to collect measurement data and combines it with weather measurement data. This data then gets uploaded to a PostgreSQL database. This document will show you the database structure and how it works. 

## System
The system is set up as can be seen in the picture below. First, the OPET, i.e., measurement instruments, collect the data and save it as a CSV file on the server. This includes curve and point measurements. The server runs the PostgreSQL database. The weather data also gets pulled to this server and matched. The weather data is stored on an older server from LPVO. From the server that runs PostgreSQL, data can be downloaded so that the collected data can be studied. 

![system](images/Database_system.png)

## Database structure
The database contains 4 tables: 'pv_point', 'pv_curve', 'weather', and 'modules'. These tables get linked via some variables. The 'pv_point' and 'pv_curve' tables get linked to the 'modules' table via the variable 'module_name'. This means that if a module is not added to the modules list, data for that module cannot be collected. The 'pv_point' and 'pv_curve' tables get linked to the 'weather' table via the 'weather_id'. The system checks whether there were any weather measurements in the past 5 minutes and assigns the most recent weather_id of the weather measurement to the point/curve measurement. 
![database](images/Database_structure.svg)

## SETUP
Things that need to be installed on the server to run the system:
* postgresql
* [pgvector](https://github.com/pgvector/pgvector)
* 
