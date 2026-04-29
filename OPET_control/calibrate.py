"""Calibration routines for OPET loads using a calibrator.

Requires the ``calibration`` extra: ``pip install ".[calibration]"``
"""

import numpy as np
from scipy.stats import kendalltau, pearsonr
from scipy.optimize import curve_fit
from datetime import datetime
import json
from pathlib import Path


def round_digits(number, digits):
    '''Round `number` to `digits` number of significant digits'''
    if number == 0:
        return 0
    order = int(np.floor(np.log10(abs(number))))
    return round(number / (10 ** order), digits - 1) * (10 ** order)


round_digits = np.vectorize(round_digits)


def value_from_counts(counts, scale, offset):
    return scale * (counts + offset)


def validate_cal(
    cal_points, counts_actual,
    scale_old, scale_new,
    offset_old, offset_new
):
    # Check if monotonic
    kt_statistic = kendalltau(cal_points, counts_actual).statistic
    kt_threshold = 0.9
    if kt_statistic < kt_threshold:
        raise RuntimeError(f'''
            Calibration is invalid: Result is not monotonic. Kendall tau is
            {kt_statistic} and we expected at least {kt_threshold}
        ''')

    # Check if linear
    pr_statistic = pearsonr(cal_points, counts_actual).statistic
    pr_threshold = 0.99
    if pr_statistic < pr_threshold:
        raise RuntimeError(f'''
            Calibration is invalid: Result is not linear. Pearson R is
            {pr_statistic} and we expected at least {pr_threshold}
        ''')

    # Check if a small change in scale
    scale_change = (scale_old - scale_new) / scale_old
    scale_change_threshold = 0.1
    if abs(scale_change) > scale_change_threshold:
        raise RuntimeError(f'''
            Calibration is invalid: Scale change is too big. Scale change is
            {scale_change} and we expected at most {scale_change_threshold}
        ''')

    # Check if a small change in offset
    offset_change = (offset_old - offset_new) / offset_old
    offset_change_threshold = 0.1
    if abs(offset_change) > offset_change_threshold:
        raise RuntimeError(f'''
            Calibration is invalid: Offset change is too big. Offset change is
            {offset_change} and we expected at most {offset_change_threshold}
        ''')


def run_calibration(
    calibrator,
    target_opet,
    calibration_type,
    n_points=5,
    n_repetitions=10,
    voltage_safety_limit=99,
    validate_calibration_constants=True,
    update_calibration_constants=True,
    report_destination=None
):
    '''Calibrate `target_opet` using `calibrator`. Available values for
    `calibration_type` are:
    - voltage: voltage calibration
    - current-low: current calibration, up to the calibrator's current post
    switch point (3 A for the Fluke 5522A)
    - current-high: current calibration, above the calibrator's current post
    switch point (3 A for the Fluke 5522A)

    `n_points` is how many voltage or current points are used between zero and
    the range's maximum. `n_repetitions` is how many times the OPET measurement
    is repeated and averaged.

    Voltage will never be set above `voltage_safety_limit`. If a voltage range
    exceeds it, we'll do the best cal we can below the limit.

    Returns a dictionary of information about the calibration results. If a
    `Path` is passed to `report_destination`, a calibration report is written
    or appended in that location.'''

    # Validate arguments
    valid_calibration_types = ['voltage', 'current-low', 'current-high']
    voltage_calibration_types = ['voltage']
    current_calibration_types = ['current-low', 'current-high']
    if calibration_type not in valid_calibration_types:
        raise ValueError(f'''
            The passed cal type {calibration_type} is not one of
            {valid_calibration_types}
        ''')
    report_addendum = {}
    if report_destination:
        if isinstance(report_destination, str):
            report_destination = Path(report_destination)
        report_destination.mkdir(exist_ok=True, parents=True)

    # Reset the calibrator
    calibrator.reset()

    # Store the calibrator's identification in the report
    report_addendum['calibrator_identification'] = {
        k: v.decode() for k, v in calibrator.identification.items()
    }

    # Reset the OPET
    target_opet.reset()

    # Put it in Voc or Isc according to the cal type
    if calibration_type in current_calibration_types:
        target_opet.mode = 'isc'
    elif calibration_type in voltage_calibration_types:
        target_opet.mode = 'voc'
    # Activate OPET output
    target_opet.output_enabled = True

    # Store the OPET's identification and address in the report
    report_addendum['opet_identification'] = {
        k: v.decode() for k, v in target_opet.identification.items()
    }
    report_addendum['opet_address_integer'] = target_opet.address_integer
    
    # Use this moment as the timestamp of this calibration
    report_addendum['calibration_timestamp'] = (
        datetime.now().astimezone().isoformat()
    )
    # Report the calibration type
    report_addendum['calibration_type'] = calibration_type

    if report_destination:
        # Use the OPET serial number and date to name the report file
        report_path = report_destination / (
            'opet-calibration-report_'
            + report_addendum['opet_identification']['serial_number']
            + '_'
            + datetime.now().astimezone().date().isoformat()
            + '.json'
        )
        # Load prior data on this unit, if available
        if report_path.exists():
            with open(report_path) as f:
                try:
                    report_base = json.load(f)
                except json.JSONDecodeError:
                    raise RuntimeError(f'''
                        The file at {report_path} is not valid JSON. Fix or
                        delete the file.
                    ''')
        else:
            report_base = []

    # Get the OPET into a slow-averaging state for low noise
    target_opet.n_adc_average_vc = 100
    target_opet.n_adc_cycles_vc = 100

    # Work out the possible values of range index
    if calibration_type in current_calibration_types:
        current_ranges = target_opet.current_ranges
        if calibration_type == 'current-low':
            # Keep only current ranges up to the calibrator's switch point
            ranges = {
                index: current_range
                for index, current_range
                in current_ranges.items()
                if current_range <= calibrator.current_switch_point
            }
        elif calibration_type == 'current-high':
            # Keep only current ranges above the calibrator's switch point
            ranges = {
                index: current_range
                for index, current_range
                in current_ranges.items()
                if current_range > calibrator.current_switch_point
            }
    elif calibration_type in voltage_calibration_types:
        ranges = target_opet.voltage_ranges

    cal_results_all = []
    # Now calibrate each applicable range
    for range_index in ranges:
        cal_result_single = {}
        cal_result_single['range_index'] = range_index
        # Set the range
        if calibration_type in current_calibration_types:
            target_opet.current_range_index = range_index
        elif calibration_type in voltage_calibration_types:
            target_opet.voltage_range_index = range_index
        
        # Read the actual voltage and current limits
        v_max, i_max = target_opet.ranges

        if calibration_type in current_calibration_types:
            print(f'On the {i_max} A range:')
            cal_result_single['current_range'] = i_max
        elif calibration_type in voltage_calibration_types:
            print(f'On the {v_max} V range:')
            cal_result_single['voltage_range'] = v_max

        # Set limits on the calibrator
        calibrator.i_limits = (-0.001, 1.05 * i_max)
        calibrator.v_limits = (-0.1, min(1.05 * v_max, voltage_safety_limit))
        # Add them to the report
        cal_result_single['calibrator_current_limits'] = (
            calibrator.i_limits
        )
        cal_result_single['calibrator_voltage_limits'] = (
            calibrator.v_limits
        )
        
        # Place the OPET in calibration mode (readouts will be in counts)
        if calibration_type in current_calibration_types:
            target_opet.activate_current_calibration_mode()
        elif calibration_type in voltage_calibration_types:
            target_opet.activate_voltage_calibration_mode()
        
        # Read out the old scale and offset
        scale_old = target_opet.calibration_scale
        offset_old = target_opet.calibration_offset
        cal_result_single['scale_old'] = scale_old
        cal_result_single['offset_old'] = offset_old
        
        # Decide on calibration setpoints
        if calibration_type in current_calibration_types:
            cal_set_values = round_digits(np.linspace(i_max, 0, n_points), 4)
        elif calibration_type in voltage_calibration_types:
            cal_set_values = np.clip(
                np.linspace(v_max, 0, n_points),
                0, voltage_safety_limit
            )
            cal_set_values = round_digits(cal_set_values, 4)
        cal_result_single['calibrator_set_values'] = list(cal_set_values)
        
        # This holds the values read back from the calibrator
        cal_actual_values = []
        # This holds the counts read back from the OPET
        opet_actual_counts = []
        
        # For each point, set the calibrator and read back from the OPET
        for set_value in cal_set_values:
            # Set the calibrator output and turn it on
            if calibration_type in current_calibration_types:
                print(f'{set_value} A  ', end='')
                calibrator.i_set = set_value
                if calibration_type == 'current-low':
                    # Switch to the low-current output posts
                    calibrator.current_output_posts = 'AUX'
                if calibration_type == 'current-high':
                    # Switch to the high-current output posts
                    calibrator.current_output_posts = 'A20'
            elif calibration_type in voltage_calibration_types:
                print(f'{set_value} V  ', end='')
                calibrator.v_set = set_value
            calibrator.output_on = True

            for _ in range(n_repetitions):
                # Read back the calibrator output and store it
                if calibration_type in current_calibration_types:
                    cal_actual_value = calibrator.i_set
                elif calibration_type in voltage_calibration_types:
                    cal_actual_value = calibrator.v_set
                cal_actual_values.append(cal_actual_value)
                # Read the OPET output in counts and store it
                if calibration_type in current_calibration_types:
                    actual_counts = target_opet.sample['current']
                elif calibration_type in voltage_calibration_types:
                    actual_counts = target_opet.sample['voltage']
                opet_actual_counts.append(actual_counts)

            # Turn off the calibrator output
            calibrator.output_on = False                

        # Record the results
        cal_result_single['calibrator_actual_values'] = cal_actual_values
        cal_result_single['opet_actual_counts'] = opet_actual_counts

        print('')
        
        # Calculate the new scale and offset
        (scale_new, offset_new), _ = curve_fit(
            value_from_counts,
            opet_actual_counts,
            cal_actual_values
        )
        cal_result_single['scale_new'] = scale_new
        cal_result_single['offset_new'] = offset_new

        print(f'scale: {scale_old} → {scale_new}')
        print(f'offset: {offset_old} → {offset_new}')
        
        # Optionally check that the new calibration is valid
        cal_result_single['calibration_constants_validated'] = (
            validate_calibration_constants
        )
        if validate_calibration_constants:
            validate_cal(
                cal_actual_values, opet_actual_counts,
                scale_old, scale_new,
                offset_old, offset_new
            )
        
        # Optionally send the new coefficients to the OPET
        if update_calibration_constants:
            target_opet.calibration_scale = scale_new
            target_opet.calibration_offset = offset_new
            print('Updated calibration constants')
            cal_result_single['calibration_constants_updated'] = True
        else:
            print('Calibration constants not updated')
            cal_result_single['calibration_constants_updated'] = False
        print('')

        # Add this range's results to the results list
        cal_results_all.append(cal_result_single.copy())

    # Reset the OPET to get it out of calibration mode
    target_opet.reset()

    # Store all ranges' results in the report
    report_addendum['calibration_results'] = cal_results_all
    if report_destination:
        # Add this report at the end of the existing reports
        report_base.append(report_addendum)
        with open(report_path, 'w') as f:
            json.dump(report_base, f, indent=2)
    return report_addendum
