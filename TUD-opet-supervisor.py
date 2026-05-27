import multiprocessing
import datetime
from time import sleep
from measurement_scheduling_tools import datetime_range, present, next_occurrence
import json
from pathlib import Path
from opet_supervisor_tools import measurement_loop, writer_loop
from pyt_to_SQL import daily_loop, update_loop
import logging
import sys
import traceback
from zoneinfo import ZoneInfo



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

        shutdown = manager.Event()

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
                args=(bus, jobs, jobs_in_progress, results, bus_info, load_info, maximum_wait, minimum_wait, shutdown),
                name=f'measurement-bus-{bus}',
            )       
            for bus
            in buses_all
        ]

        # Add one to do the logging
        processes.append(
            multiprocessing.Process(
                target=writer_loop,
                args=(results, data_path_base, TZ_LOCAL, minimum_wait,shutdown),
                name='writer',
            )
        )

        processes.append(
            multiprocessing.Process(
                target=daily_loop,
                name='daily_loop'
            )
        )       

        processes.append(
            multiprocessing.Process(
                target=update_loop,
                name='update_loop'
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
            while not shutdown.is_set():
                if schedule_never_updated:
                    schedule_never_updated = False
                else:
                    while present() < schedule_update_time and not shutdown.is_set():
                        shutdown.wait(minimum_wait)
                    schedule_update_time += datetime.timedelta(seconds=schedule_interval)

                #Check if processes are still active and restart inactive ones
                for i, process in enumerate(processes):
                    if shutdown.is_set():
                        break
                    
                    if process.is_alive():
                        continue
                    
                    logger.error(f'Process {process.name} died: restarting')
                    process.join(timeout=1)

                    old_name = process.name
                    
                    #make new process based on name
                    if old_name.startswith('measurement-bus-'):
                        bus = old_name.removeprefix('measurement-bus-')

                        new_process = multiprocessing.Process(
                            target=measurement_loop,
                            args=(bus,jobs,jobs_in_progress,results,bus_info,load_info,maximum_wait,minimum_wait,shutdown),
                            name=old_name,
                        )

                    elif old_name == 'writer':
                        new_process = multiprocessing.Process(
                            target=writer_loop,
                            args=(results,data_path_base,TZ_LOCAL,minimum_wait,shutdown),
                            name='writer',
                        )

                    elif old_name == 'daily_loop':
                        new_process = multiprocessing.Process(
                            target=daily_loop,
                            name='daily_loop'
                        )
                    elif old_name == 'update_loop':
                        new_process = multiprocessing.Process(
                            target=update_loop,
                            name='update_loop'
                        )                       
                    else:
                        logger.error(f'unknown child process name {old_name}; cannot restart')
                        continue
                    
                    new_process.start()
                    processes[i] = new_process

                    logger.info(f'restarted {new_process.name}')

                # Reload the configuration
                with open(config_path / 'measurement_config.json') as f:
                    config = json.load(f)

                # OPETs are tracers that start with 'O'; these are the modules for
                # OPETs only, ignoring other tracers
                modules = [
                    x for x in config['modules']
                    if x['tracer'].startswith('O')
                ]   

                # Add set_load_mode jobs
                for module in modules:
                    #module is enabled, and stopdate has yet not passed
                    if not module.get('disabled', False) and (module.get('stopdate') is None or datetime.datetime.strptime(module["stopdate"], "%Y-%m-%d").date() >= datetime.datetime.now().date()):  
                        if module.get('load_mode'):
                            scheduled_time = present() + datetime.timedelta(seconds=3)
                            jobs[job_id] = {
                                'scheduled_time': scheduled_time,
                                'expiration_time': schedule_update_time,
                                'opet_name': module['tracer'],
                                'opet_bus': load_info[module['tracer']]['bus'],
                                'opet_address': load_info[module['tracer']]['address'],
                                'module_name': module['module_name'],
                                'mounted_on': module['mounted_on'],
                                'axis_azimuth': config[module['mounted_on']]['axis_azimuth'],
                                'axis_tilt': config[module['mounted_on']]['axis_tilt'],
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
                            'axis_azimuth': config[module['mounted_on']]['axis_azimuth'],
                            'axis_tilt': config[module['mounted_on']]['axis_tilt'],
                            'job_type': 'set_load_mode',
                            'load_mode': 'disable',
                            'disabled':  module['disabled']
                        }
                        print(f'manager: {job_id} (set_load_mode: disabled) scheduled for {scheduled_time.astimezone(TZ_LOCAL)}')
                        job_id += 1                       

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
                            'axis_azimuth': config[module['mounted_on']]['axis_azimuth'],
                            'axis_tilt': config[module['mounted_on']]['axis_tilt'],
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
                            'axis_azimuth': config[module['mounted_on']]['axis_azimuth'],
                            'axis_tilt': config[module['mounted_on']]['axis_tilt'],
                            'job_type': 'curve',
                            'data_destination': config['data_destination']
                        }
                        print(f'manager: {job_id} (curve) scheduled for {scheduled_time.astimezone(TZ_LOCAL)}')
                        job_id += 1
                print(f'manager: {len(jobs)} jobs are scheduled')
                print(f'manager: {jobs.keys()}')
        
        #Handle Exceptions
        except Exception:
            logger.exception('shutting down child processes')
            shutdown.set()   
        except KeyboardInterrupt:
            logger.info('shutting down child processes')
            shutdown.set()               
        finally:
            shutdown.set()            
            #Wait for processes to finish 
            for process in processes:
                process.join(timeout=10)  
            
            #Otherwise terminate remaining processes
            for process in processes:  
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)