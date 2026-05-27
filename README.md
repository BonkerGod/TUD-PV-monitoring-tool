# TUD-PV-monitoring-tool
PV monitoring tool for the TU Delft. It makes use of the OPET modules to collect measurement data and combines it with weather measurement data. This data then gets uploaded to a PostgreSQL database. This document will show you the database structure and how it works. 

## System
The system is set up as can be seen in the picture below. First, the OPET, i.e., measurement instruments, collect the data and save it as a CSV file on the server. This includes curve and point measurements. The server that is on Windows runs the PostgreSQL database. The weather data also gets pulled to this server and matched. The weather data is stored on an older server from LPVO, which runs MySQL. This server is accessed over the network, so you need to forward the ports to it. If it is not possible to open up the firewall or connect over the network, we would advise using a vpn service like [Tailscale](https://tailscale.com/). For this to work, you need to set up a subnet on the old server from which you want to get the weather data. From the server that runs PostgreSQL, data can be downloaded so that the collected data can be studied. 

![system](images/Database_setup.jpeg)

## Database structure
The database contains 4 tables: 'pv_point', 'pv_curve', 'weather', and 'modules'. These tables get linked via some variables. The 'pv_point' and 'pv_curve' tables get linked to the 'modules' table via the variable 'module_name'. This means that if a module is not added to the modules list, data for that module cannot be collected. To add a module to the list, you need to add it to the 'measurement_config.json'. The 'pv_point' and 'pv_curve' tables get linked to the 'weather' table via the 'weather_id'. The system checks whether there were any weather measurements in the past 5 minutes and assigns the most recent weather_id of the weather measurement to the point/curve measurement.
> [!Caution]
>  All the fields of the 'measurement_config.json' must be filled in; otherwise, the system will break down. To leave space blank fill in:"".

![database](images/Database_structure.svg)

## Setup
Things that need to be installed on the server to run the system:
* [Python](https://www.python.org/downloads/) (Get the most recent fully supported version, i.e., no pre-release)
* [PostgreSQL](https://www.postgresql.org/download/) 
* [pgvector](https://github.com/pgvector/pgvector) (This enables curve measurements to be stored in a vector)
* `pip install psycopg2`
* `pip install psycopg2-binary`
* `pip install pandas`
* `pip install serial`
* `pip install mysql-connector-python`
* `pip install setuptools`

When all these programs are installed, and the database has been set up using the PostgreSQL installer, the program 'pyt_to_SQL.py' can be used to continue the setup. The tables for data storage can be created using the function `create_table(type, conn, cur)`. This needs to be done for the types: 'pv_point', 'pv_curve', 'weather', and 'modules'. Running the following code does that: 
```python
conn, cur, mysql_conn, mysql_cur, config, data_path_base = init()
create_table('pv_point', conn, cur)
create_table('pv_curve', conn, cur)
create_table('weather', conn, cur)
create_table('modules', conn, cur)
db_close(conn)
```

> [!TIP]
> These functions are stored in 'pyt_to_SQL.py'; it is advised to run this code in a different file, so you do not accidentally destroy the code. Do this by adding `from pyt_to_SQL import init, create_table, db_close` at the top of your file.

The next step is to configure the JSON files properly, to see how to do this click [here](#example-config-test). 
When you have completed all previous steps, you can start using the database by running 'TUD-opet-supervisor.py'.

## File descriptions
Here are some high-level descriptions of each document. To fully understand the code, you will have to look into the Python file for more specific explanations. 

<details>
    <summary><b>TUD-opet-supervisor.py</b></summary>
    <p>This document is the heart of the operation. It schedules functions in the code. It plans the measurements and plans the updates of the database.</p>
</details>

<details>
    <summary><b>pyt_to_SQL.py</b></summary>
    <p>
      This document contains all the operations that update the PostgreSQL database. <br><br>
      Firstly, to do any operations with the database, a connection needs to be made. This is done using <code>init()</code>. After using the program, it needs to be shut down <code>db_close(conn)</code> <br>
      It contains the looping functions such as: <code>daily_loop()</code> and <code>update_loop()</code>. It also contains the mechanism to add the collected data to all the tables: <code>add_data(...)</code>, <code>add_module_data(...)</code>, <code>add_weather_data(...)</code>, <code>past_data_upload(...)</code>. <br>
      It also contains an error detection service <code>error_detect(...)</code> that can detect whether any information has been received in the past 24 hours for the entire database or per solar module. It also collects the number of status_integer errors relative to the total amount of measurements for each module in the past 24 hours for the point measurements. It sends an email <code>send_mail(...)</code> to the admins and owner of the solar module when a problem has been detected. <br>
      This also contains multiple programs to print, check, or delete the tables, but this is meant for debugging purposes. <br>
      Lastly and most importantly for most users, it contains the function <code>download_table(...)</code>. This function can be used to extract measurements between 2 dates for multiple solar modules at once. 
    </p>
</details>

<details>
    <summary><b>Weatherdb_to_pyth.py</b></summary>
    <p>
      This document contains various ways of extracting information from the weather database that runs on MySQL. <br><br>
      Firstly, it again has to establish a connection with the MySQL database <code>mysql_init()</code> and at the end we use <code>mysql_close(conn)</code> <br>
      The other function can collect all the weather data from a specific start date <code>weather_all(...)</code>, collect the last measurement <code>weather_last(...)</code>, or collect the data from the last 24 hours <code>download_weather_last24hours(...)</code>. 
    </p>
</details>

<details>
  <summary><b>opet-supervisor-config.json</b></summary>
    <p>This document contains the information on where the data, logs, and configurations can be found.</p>
</details>

<details>
    <summary><b>test_log</b></summary>
    <p>This folder contains the data from the measurements and stores the log files.</p>
</details>

### example-config-test
<details>
    <summary><b>example-config-test</b></summary>
    <p>This folder contains all the settings that need to be set up when a new solar module is connected. <br>
        In <code>measurement_config.json</code>, data about the solar module must be added. <br>
        In <code>opet_bus_info.json</code>, the serial number of the USB to RS-485 adapter needs to be listed. This serial number can be found using <code>port_finder.py</code></p>. If you have multiple USB adapters, you need to do this multiple times and start at 'a', 'b', 'c',... <br>
    Lastly, the <code>opet_info.json</code> needs to be set up. This contains the tracers that need to be named according to the following format 'O001', where the number increases with the tracer. The rest contains the bus that the tracer is on and the address of the OPET.
</details>

<details>
    <summary><b>opet_supervisor_tools</b></summary>
    <p>This folder contains documents that help the operation of the <code>TUD-opet-supervisor.py</code>
        In <code>opet_supervisor_tools.py</code>, the code that performs the point and curve measurements can be found, and the program that writes the collected data to a CSV file. <br>
        In <code>port_finder.py</code>, you can find the code that enables you to find the port of your USB adapter.
    </p>
</details>

<details>
    <summary><b>OPET_control</b></summary>
    <p>This folder contains the <code>OPET_control.py</code>. This piece of code acts as the translation layer between the OPETs and the <code>TUD-opet-supervisor.py</code>. 
    </p>
</details>

<details>
    <summary><b>user_tools</b></summary>
    <p>This folder contains programs that can be used by the users to setup or extract data. <code>plot_csv.py</code> plots a couple of measurements. </p>
</details>

