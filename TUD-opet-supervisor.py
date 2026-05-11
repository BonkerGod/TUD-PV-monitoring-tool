import multiprocessing
import datetime
from time import sleep
import csv
from measurement_scheduling_tools import datetime_range, present, next_occurrence
import json
from pathlib import Path
from OPET_control import OPETBus, OPET
from serial_by_serial import device_name
from serial import Serial
from opet_supervisor_tools.opet_supervisor_tools import measurement_loop, writer_loop
import logging
import sys
import traceback
from zoneinfo import ZoneInfo

weather_data = {'t_air': 23.0,
            'humidity': 67.0,
            'dewpoint': 24.0,
            'relative_pressure': 1.0,
            'wind_speed': 1.5,
            'wind_speed_spread':0.5,
            'wind_direction':10.0 ,
            'wind_direction_spread':1.5,
            'irradiance': 17.0
        }


#Constants
# Measurements more than this far into the future will be handled on a
# subsequent loop
maximum_wait = 0.1  # s
# Infinite loops with nothing to do will delay this much before checking again
minimum_wait = 0.01  # s
# Measurements are scheduled only this far into the future
schedule_horizon = 32  # s
# The schedule is updated this often
schedule_interval = 30  # s

TZ_LOCAL = ZoneInfo("Europe/Amsterdam")

#Load from .json files
with open('opet-supervisor-config.json') as f:
    opet_supervisor_config = json.load(f)

config_path = Path(opet_supervisor_config['config_path'])
data_path_base = Path(opet_supervisor_config['data_path_base'])
log_path_base = Path(opet_supervisor_config['log_path_base'])

with open(config_path / 'opet_info.json') as f:
    load_info = json.load(f)

print(load_info)
with open(config_path / 'opet_bus_info.json') as f:
    bus_info = json.load(f)

#Setup logging
log_path_base.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger(__name__)
logging.basicConfig(
    filename=(log_path_base / 'opet-supervisor.log'),
    encoding='utf-8',
    level=logging.DEBUG,
    format='%(asctime)s %(message)s'
)

logger.debug('opet-supervisor started')

# Set up a handler to log uncaught exceptions
def exception_handler(exctype, value, tb):
    logger.exception(''.join(traceback.format_exception(exctype, value, tb)))

sys.excepthook = exception_handler


if __name__ == '__main__':
    with multiprocessing.Manager() as manager:
        # Job definitions will be values in this shared dictionary.
        # Keys are unique job IDs so they can be removed from the dictionary
        # even if the dictionary gets updated while a job is underway. The
        # Manager doesn't handle updates to *nested* dictionaries for other
        # processes, so this code tends to pop things out of dictionaries,
        # work with them, then reinsert them if needed
        jobs = manager.dict({})
        results = manager.dict({})
        jobs_in_progress = manager.dict({})
        job_id = 0

        # All possible buses. Each bus will get a process
        buses_all = set([
            load_info_datum['bus']
            for load_name, load_info_datum
            in load_info.items()
        ])
        # Create a process for each bus
        processes = [
            multiprocessing.Process(
                target=measurement_loop,
                args=(bus, jobs, jobs_in_progress, results, bus_info, load_info, logger, maximum_wait, minimum_wait)
            )
            for bus
            in buses_all
        ]

        # Add one to do the logging
        processes.append(
            multiprocessing.Process(
                target=writer_loop,
                args=(results, data_path_base, TZ_LOCAL, minimum_wait,weather_data )
            )
        )
        
        for process in processes:
            process.start()

        schedule_update_time = next_occurrence(
            present(),
            datetime.timedelta(seconds=schedule_interval)
        )
        schedule_never_updated = True
        try:
            while True:
                if schedule_never_updated:
                    schedule_never_updated = False
                else:
                    while present() < schedule_update_time:
                        sleep(minimum_wait)
                    schedule_update_time += datetime.timedelta(seconds=schedule_interval)

                # Reload the configuration
                with open(config_path / 'measurement_config.json') as f:
                    config = json.load(f)

                # OPETs are tracers that start with 'O'; these are the modules for
                # OPETs only, ignoring other tracers
                modules = [
                    x for x in config['modules']
                    if x['tracer'].startswith('O')
                ]
                #Only schedule modules which are enabled
                modules = [
                    x for x in modules
                    if not x.get('disabled', False)
                ]

                #Only schedule modules which are not due
                modules = [
                    x for x in modules
                    if x["stopdate"] == None or 
                    datetime.datetime.strptime(x["stopdate"], "%Y-%m-%d").date() >= datetime.datetime.now().date()
                ]         

                # Add set_load_mode jobs
                for module in modules:
                    #module is enabled, and stopdate has yet not passed
                    if not module.get('disabled') and (module["stopdate"] == None or datetime.datetime.strptime(module["stopdate"], "%Y-%m-%d").date() >= datetime.datetime.now().date()):  
                        if module.get('load_mode'):
                            scheduled_time = present()
                            jobs[job_id] = {
                                'scheduled_time': scheduled_time,
                                'expiration_time': schedule_update_time,
                                'opet_name': module['tracer'],
                                'opet_bus': load_info[module['tracer']]['bus'],
                                'opet_address': load_info[module['tracer']]['address'],
                                'module_name': module['module_name'],
                                'mounted_on': module['mounted_on'],
                                'azimuth': config[module['mounted_on']]['azimuth'],
                                'inclination': config[module['inclination']]['inclination'],
                                'job_type': 'set_load_mode',
                                'load_mode': module['load_mode'],
                                'disabled':  module['disabled']
                            }
                            print(f'manager: {job_id} (set_load_mode: {module["load_mode"]}) scheduled for {scheduled_time.astimezone(TZ_LOCAL)}')
                            job_id += 1

                    else: #Module should be disabled
                        scheduled_time = present()
                        jobs[job_id] = {
                            'scheduled_time': scheduled_time,
                            'expiration_time': schedule_update_time,
                            'opet_name': module['tracer'],
                            'opet_bus': load_info[module['tracer']]['bus'],
                            'opet_address': load_info[module['tracer']]['address'],
                            'module_name': module['module_name'],
                            'mounted_on': module['mounted_on'],
                            'azimuth': config[module['mounted_on']]['azimuth'],
                            'inclination': config[module['inclination']]['inclination'],
                            'job_type': 'set_load_mode',
                            'load_mode': 'disable',
                            'disabled':  module['disabled']
                        }
                        print(f'manager: {job_id} (set_load_mode: {module["load_mode"]}) scheduled for {scheduled_time.astimezone(TZ_LOCAL)}')
                        job_id += 1                       



                # Time to update the jobs list
                if jobs:
                    schedule_start = max([job['scheduled_time'] for job in jobs.values()])
                else:
                    schedule_start = present()
                schedule_end = present() + datetime.timedelta(seconds=schedule_horizon)
                for module in modules:
                    # Schedule point measurements
                    point_interval = datetime.timedelta(
                        seconds=module['interval_point']
                    )
                    # Find times in the scheduling window, spaced by the interval
                    scheduled_times = datetime_range(
                        schedule_start,
                        schedule_end,
                        point_interval,
                        include_start_point=False
                    )

                    # Jobs expire when they reach the scheduled time plus the
                    # measurement interval, because then they are redundant with
                    # the next repetition of the measurement.

                    # Eliminate times that would already have expired
                    scheduled_times = [
                        t
                        for t
                        in scheduled_times
                        if t + point_interval >= present()
                    ]

                    # Create a dict that gives the job instructions
                    for scheduled_time in scheduled_times:
                        jobs[job_id] = {
                            'scheduled_time': scheduled_time,
                            'expiration_time': scheduled_time + point_interval,
                            'opet_name': module['tracer'],
                            'opet_bus': load_info[module['tracer']]['bus'],
                            'opet_address': load_info[module['tracer']]['address'],
                            'module_name': module['module_name'],
                            'mounted_on': module['mounted_on'],
                            'azimuth': config[module['mounted_on']]['azimuth'],
                            'inclination': config[module['inclination']]['inclination'],
                            'job_type': 'point',
                            'data_destination': config['data_destination']
                        }
                        print(f'manager: {job_id} (point) scheduled for {scheduled_time.astimezone(TZ_LOCAL)}')
                        job_id += 1

                    # Schedule curve measurements
                    curve_interval = datetime.timedelta(
                        seconds=module['interval_curve']
                    )

                    # Find times in the scheduling window, spaced by the interval
                    scheduled_times = datetime_range(
                        schedule_start,
                        schedule_end,
                        curve_interval,
                        include_start_point=False
                    )

                    # Eliminate times that would already have expired
                    scheduled_times = [
                        t
                        for t
                        in scheduled_times
                        if t + curve_interval >= present()
                    ]

                    # Create a dict that gives the job instructions
                    for scheduled_time in scheduled_times:
                        jobs[job_id] = {
                            'scheduled_time': scheduled_time,
                            'expiration_time': scheduled_time + curve_interval,
                            'opet_name': module['tracer'],
                            'opet_bus': load_info[module['tracer']]['bus'],
                            'opet_address': load_info[module['tracer']]['address'],
                            'module_name': module['module_name'],
                            'mounted_on': module['mounted_on'],
                            'azimuth': config[module['mounted_on']]['azimuth'],
                            'inclination': config[module['inclination']]['inclination'],
                            'job_type': 'curve',
                            'data_destination': config['data_destination']
                        }
                        print(f'manager: {job_id} (curve) scheduled for {scheduled_time.astimezone(TZ_LOCAL)}')
                        job_id += 1
                print(f'manager: {len(jobs)} jobs are scheduled')
                print(f'manager: {jobs.keys()}')
        
        #Handle keyboard interrupt
        except KeyboardInterrupt:
            print("Keyboard interrupt: shutting down")
            #Let processes close cleanly

            #First disable outputs of all opets
            modules = [
                    x for x in config['modules']
                    if x['tracer'].startswith('O')
                ]     
            print("disabling opets")
            # Add set_load_mode jobs
            for module in modules:
                if module.get('load_mode'):
                    scheduled_time = present()
                    jobs[job_id] = {
                        'scheduled_time': scheduled_time,
                        'expiration_time': schedule_update_time,
                        'opet_name': module['tracer'],
                        'opet_bus': load_info[module['tracer']]['bus'],
                        'opet_address': load_info[module['tracer']]['address'],
                        'module_name': module['module_name'],
                        'mounted_on': module['mounted_on'],
                        'azimuth': config[module['mounted_on']]['azimuth'],
                        'inclination': config[module['inclination']]['inclination'],
                        'job_type': 'set_load_mode',
                        'load_mode': 'disable',
                        'disabled':  module['disabled']
                    }
                    print(f'manager: {job_id} (set_load_mode: {module["load_mode"]}) scheduled for {scheduled_time.astimezone(TZ_LOCAL)}')
                    job_id += 1

            for process in processes:
                process.join()  
            for process in processes:
                process.terminate()
            Serial.close()         
            print("Done")
