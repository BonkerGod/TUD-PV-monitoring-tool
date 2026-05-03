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
import logging
import sys
import traceback

# Measurements more than this far into the future will be handled on a
# subsequent loop
maximum_wait = 0.1  # s
# Infinite loops with nothing to do will delay this much before checking again
minimum_wait = 0.01  # s
# Measurements are scheduled only this far into the future
schedule_horizon = 11  # s
# The schedule is updated this often
schedule_interval = 10  # s

with open('opet-supervisor-config.json') as f:
    opet_supervisor_config = json.load(f)

config_path = Path(opet_supervisor_config['config_path'])
data_path_base = Path(opet_supervisor_config['data_path_base'])
log_path_base = Path(opet_supervisor_config['log_path_base'])


log_path_base.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger(__name__)
logging.basicConfig(
    filename=(log_path_base / 'opet-supervisor.log'),
    encoding='utf-8',
    level=logging.DEBUG,
    format='%(asctime)s %(message)s'
)

# Set up a handler to log uncaught exceptions
def exception_handler(exctype, value, tb):
    logger.exception(''.join(traceback.format_exception(exctype, value, tb)))


sys.excepthook = exception_handler

logger.debug('opet-supervisor started')

TZ_LOCAL = datetime.timezone(datetime.timedelta(hours=-7))

with open(config_path / 'opet_info.json') as f:
    load_info = json.load(f)

print(load_info)
with open(config_path / 'opet_bus_info.json') as f:
    bus_info = json.load(f)


def measurement_loop(bus, jobs, jobs_in_progress, results):
    '''In an infinite loop, do the jobs in `dict` that are assigned to `bus`
    and store the `results`.'''
    def initialize_bus():
        # Set up the OPET bus serial communication, returning a list of
        # individual OPETs. Returns None if something goes wrong.
        # TODO: handle the hot-plugging and power failure cases
        try:
            serial_port_name = "COM3"
            serial_port = Serial(serial_port_name, baudrate=200000, timeout=1)
            opet_bus = OPETBus(serial_port)
            this_bus_opet_addresses = [
                v['address']
                for k, v
                in load_info.items()
                if v['bus'] == bus
            ]
            opets = {
                address: OPET(opet_bus, address, iv_time_multiplier=2)
                for address
                in this_bus_opet_addresses
            }
            return opets
        except IndexError:
            logging.error(f'Couldn\'t find the serial port for bus {bus}')
            return None

    # Attempt to set up the bus
    opets = initialize_bus()

    # Do jobs as they are scheduled and become due
    while True:
        if opets is None:
            # Attempt to set up the bus
            opets = initialize_bus()
            # If it failed, wait before retrying
            if opets is None:
                sleep(5)
            # Return to the top of the loop
            continue
        # These jobs belong to this bus, so other processes will not touch them
        bus_jobs = {
            job_id: job
            for job_id, job
            in jobs.items()
            if job['opet_bus'] == bus
        }

        # Consider each job that is scheduled for this bus
        # Sort by scheduled time
        bus_jobs = dict(sorted(bus_jobs.items(), key=lambda x: x[1]['scheduled_time']))
        this_bus_job_ids = list(bus_jobs.keys())
        
        # Repeat this as long as there are job ids listed for this bus
        while this_bus_job_ids:
            # Consider the first remaining job in this_bus_job_ids
            job_id = this_bus_job_ids[0]

            # Skip this job if it has reached or passed the expiration time
            if present() >= jobs[job_id]['expiration_time']:
                logger.debug(f'bus {bus}: job {job_id}: job expired (skipping)')
                # Pop this job from the shared jobs dict and this bus's id list
                this_bus_job_ids.pop(this_bus_job_ids.index(job_id))
                jobs.pop(job_id)
                # Return to the top of the loop
                continue
            
            # Determine how far into the future this job should be scheduled
            seconds_until_target = (
                jobs[job_id]['scheduled_time'] - present()
            ).total_seconds()
            
            # Ignore this job if it's too far into the future
            if seconds_until_target > maximum_wait:
                # All other jobs are later than this, so this loop is finished
                break
            
            # It's time to do this job. Pop it out of the shared jobs dict and
            # this bus's job id list.
            this_bus_job_ids.pop(this_bus_job_ids.index(job_id))
            job = jobs.pop(job_id)

            # Delay until the right moment
            sleep(max(0, seconds_until_target))
            
            # Check if this OPET is available:
            if not opets[job['opet_address']].available:
                logger.debug(f'bus {bus}: job {job_id}: delayed because {job["opet_name"]} is not available')
                # The OPET isn't available (measuring a curve) so we'll
                # put this job back on the shared dictionary, but not back in 
                # `this_bus_job_ids`, so we won't try again until the next loop
                jobs[job_id] = job
                # Return to the top of the loop to handle the next job in
                # `this_bus_job_ids`
                continue

            # Handle the job types differently
            if job['job_type'] == 'set_load_mode':
                logger.debug(f'bus {bus}: job {job_id}: setting load mode on {job["opet_name"]} to {job["load_mode"]}')
                if job["load_mode"] == 'pmp':
                    opets[job['opet_address']].mode = 'mppt'
                elif job["load_mode"] == 'voc':
                    opets[job['opet_address']].mode = 'voc'
            elif job['job_type'] == 'point':
                # Point measurements are requested and recorded in immediate
                # succession

                # Do the job
                try:
                    result = opets[job['opet_address']].sample
                    logger.debug(f'bus {bus}: job {job_id}: {result["voltage"], result["current"]}, {present() - job["scheduled_time"]} late')
                    # Store the results
                    results[job_id] = {
                        'measurement_time': present(),
                        'scheduled_time': job['scheduled_time'],
                        'measurement_type': job['job_type'],
                        'v': result['voltage'],
                        'i': result['current'],
                        'module_id': job['module_id'],
                        'status_integer': result['status_integer'],
                        'data_destination': job['data_destination']
                    }
                # We may get ValueError if the load returned something that
                # isn't a valid float, for example
                except ValueError: 
                    logger.error(f'bus {bus}: job {job_id}: ValueError in `sample` property on load {job["opet_name"]}; couldn\'t parse the load\'s reply')
                    # The job has already been taken off the jobs list
            elif job['job_type'] == 'curve':
                # Curve measurements are first all requested as scheduled,
                # then collected and recorded later in a separate step
                # Request the curve
                reply = opets[job['opet_address']].start_iv_curve()
                if reply:
                    logger.debug(f'bus {bus}: job {job_id}: curve measurement (start) {job_id}, {present() - job["scheduled_time"]} late')
            
                    # Add the job to jobs_in_progress
                    job['measurement_time'] = present()
                    job['measurement_duration'] = reply
                    jobs_in_progress[job_id] = job
                else:
                    logger.debug(f'bus {bus}: job {job_id}: curve measurement (not started) {job_id}, {present() - job["scheduled_time"]} late')
            
        # Now check whether the jobs in progress are complete, reading back
        # results as they become available

        # These jobs belong to this bus, so other threads will not touch them
        bus_jobs_in_progress = {
            job_id: job
            for job_id, job
            in jobs_in_progress.items()
            if job['opet_bus'] == bus
        }
        # Sort by scheduled time so we can FIFO
        bus_jobs_in_progress = dict(sorted(bus_jobs_in_progress.items(), key=lambda x: x[1]['scheduled_time']))
        for job_id, _ in bus_jobs_in_progress.items():
            # Pop a job out of the shared in-progress jobs dictionary
            job = jobs_in_progress.pop(job_id)
            # logger.debug(f'bus {bus}: job {job_id}: curve measurement (check if ready) {present() - job["scheduled_time"]} late')
            # Check if the measurement is complete
            if not opets[job['opet_address']].available:
                measurement_complete = False
            else:
                measurement_complete = opets[job['opet_address']].operation_complete()
            if measurement_complete:
                # The measurement is ready
                logger.debug(f'bus {bus}: job {job_id}: curve measurement (complete) {present() - job["scheduled_time"]} late')
                # Read the result
                try:
                    result = opets[job['opet_address']].iv_data
                    # Store the result
                    results[job_id] = {
                        'scheduled_time': job['scheduled_time'],
                        'measurement_time': job['measurement_time'],
                        'measurement_duration': job['measurement_duration'],
                        'measurement_type': job['job_type'],
                        'module_id': job['module_id'],
                        'v': result['voltage'],
                        'i': result['current'],
                        'data_destination': job['data_destination']
                    }
                # We may get ValueError if the load returned something that
                # isn't a valid float, for example
                except ValueError: 
                    logger.error(f'bus {bus}: job {job_id}: ValueError in `iv_data` property on load {job["opet_name"]}; couldn\'t parse the load\'s reply')
                    # The job has already been taken off the jobs_in_progress
                    # list
            else:
                # The measurement is not yet ready
                # logger.debug(f'bus {bus}: job {job_id}: curve measurement (not yet ready) {present() - job["scheduled_time"]} late')
                # We popped this job out of the dict, now we put it back
                jobs_in_progress[job_id] = job
                continue
        sleep(minimum_wait)


def writer_loop(results):
    headers = {
        'point': [
            'measurement_time',
            'scheduled_time',
            'module_id',
            'v',
            'i',
            'g',
            't_ext',
            'status_integer'
        ],
        'curve': [
            'measurement_time',
            'scheduled_time',
            'measurement_duration',
            'module_id',
            'v',
            'i',
            'g'
        ]
    }
    while True:
        while results:
            result = results.pop(next(iter(results.keys())))
            measurement_date = result['measurement_time'].astimezone(TZ_LOCAL).date().isoformat()
            data_path = data_path_base / measurement_date / result['data_destination']
            data_file_path = (
                data_path / (
                    'opet_results_'
                    + result['measurement_type']
                    + '_' + measurement_date
                    + '.csv'
                )
            )

            # Convert datetimes to ISO 8601 strings
            result['measurement_time'] = result['measurement_time'].astimezone(TZ_LOCAL).isoformat()
            result['scheduled_time'] = result['scheduled_time'].astimezone(TZ_LOCAL).isoformat()

            # Create the log file directory, if necessary
            data_file_path.parent.mkdir(parents=True, exist_ok=True)

            # Decide whether to write headers
            need_headers = not data_file_path.exists()

            with open(data_file_path, 'a') as log:
                writer = csv.DictWriter(
                    log,
                    fieldnames=headers[result['measurement_type']],
                    extrasaction='ignore'
                )
                if need_headers:
                    writer.writeheader()
                writer.writerow(result)
        sleep(minimum_wait)


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
                args=(bus, jobs, jobs_in_progress, results)
            )
            for bus
            in buses_all
        ]

        # Add one to do the logging
        processes.append(
            multiprocessing.Process(
                target=writer_loop,
                args=(results, )
            )
        )
        
        for process in processes:
            process.start()

        schedule_update_time = next_occurrence(
            present(),
            datetime.timedelta(seconds=schedule_interval)
        )
        schedule_never_updated = True
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
                        'module_id': module['module_id'],
                        'job_type': 'set_load_mode',
                        'load_mode': module['load_mode']
                    }
                    print(f'manager: {job_id} (set_load_mode: {module["load_mode"]}) scheduled for {scheduled_time.astimezone(TZ_LOCAL)}')
                    job_id += 1

            modules = [
                x for x in modules
                if not x.get('disabled', False)
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
                        'module_id': module['module_id'],
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
                    if t + point_interval >= present()
                ]
                
                # Create a dict that gives the job instructions
                for scheduled_time in scheduled_times:
                    jobs[job_id] = {
                        'scheduled_time': scheduled_time,
                        'expiration_time': scheduled_time + curve_interval,
                        'opet_name': module['tracer'],
                        'opet_bus': load_info[module['tracer']]['bus'],
                        'opet_address': load_info[module['tracer']]['address'],
                        'module_id': module['module_id'],
                        'job_type': 'curve',
                        'data_destination': config['data_destination']
                    }
                    print(f'manager: {job_id} (curve) scheduled for {scheduled_time.astimezone(TZ_LOCAL)}')
                    job_id += 1
            print(f'manager: {len(jobs)} jobs are scheduled')
            print(f'manager: {jobs.keys()}')

        for process in processes:
            process.join()
