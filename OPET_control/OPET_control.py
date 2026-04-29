"""Core classes for communicating with OPET loads over an RS485 bus.

Provides `OPETBus` for the shared serial bus and `OPET` for individual load
control, measurement, and configuration.
"""

from time import sleep
from datetime import datetime, timedelta


class OPETTimeoutError(Exception):
    '''Raise this when OPET has not replied before the bus's timeout'''

    def __init__(self):
        super(OPETTimeoutError, self).__init__()

    def __str__(self):
        return 'Got an empty reply on the OPET bus because the OPET bus\'s \
timeout has expired.'


class UnexpectedReplyError(Exception):
    '''Raise this when the OPET reply fails verification'''

    def __init__(self, expected, received):
        super(UnexpectedReplyError, self).__init__()
        self.expected = expected
        self.received = received

    def __str__(self):
        return f'Got an unexpected reply on the OPET bus. Expected: \
{self.expected} \
but got: \
{self.received}'


class NotAvailableError(Exception):
    '''Raise this when the moment of `available_time` has not yet been reached,
    so a reply is not yet expected'''

    def __init__(self, time):
        super(NotAvailableError, self).__init__()
        self.time = time

    def __str__(self):
        return f'Based on a measurement already requested, this OPET is \
expected not to reply until {self.time}, so no command has been sent.'


class OPETBus:
    '''Represents a daisy-chained serial bus of OPETs.

    Methods operate on a single OPET on the bus, specified using its
    address.'''
    def __init__(self, serial_object):
        '''`serial_object` is an instance of serial.Serial, representing an
        RS485 connection.'''
        self.ser = serial_object
    
    def send_verify(
                self, address, message,
                raw_reply=False, skip_verify=False
            ):
        '''Sends `message` to the OPET at `address` and verifies that
        the reply begins with a correct echo of the command. If `skip_verify`,
        this verification is skipped. Adds a `\\n` line ending to `message` if
        one is not supplied.

        If `raw_reply`, this returns the exact reply string. Otherwise, this
        returns a list of the elements in the tab-separated reply, with the
        echoed command and the final line ending removed.'''
        if isinstance(address, str):
            address = address.encode('ASCII')
        if isinstance(message, str):
            message = message.encode('ASCII')
        if message[-1] != 10:
            message += b'\n'
        self.ser.reset_input_buffer()
        self.ser.write(address + b'#' + message)
        reply = self.ser.readline()
        if reply == b'':
            raise OPETTimeoutError
        if not skip_verify:
            reply_command = reply.split(b'\t')[0]
            expected_reply_command = (
                message.split(b'\t')[0].rstrip()
            )
            if not reply_command == expected_reply_command:
                raise UnexpectedReplyError(
                    expected_reply_command, reply_command
                )
        if raw_reply:
            return reply
        else:
            return reply.rstrip().split(b'\t')[1:]


class OPET:
    '''Represents a single OPET'''
    def __init__(self, opet_bus, address_integer, iv_time_multiplier=1):
        '''`opet_bus` is an instance of OPETBus and address_integer is the
        OPET's address as set with the on-board jumpers.'''
        self._address_integer = address_integer
        self._address = chr(64 + address_integer)
        self._bus = opet_bus
        self.iv_time_multiplier = iv_time_multiplier
        # TODO: Confirm the EEPROM is really set this way for the HW version
        # (we've only checked it on HC units)
        self._hardware_configurations = {
            0: 'HC',
            1: 'LC'
        }
        self._voltage_ranges_all = {
            'HC': {
                0: 1,
                1: 4.2,
                2: 10,
                3: 30,
                4: 100
            },
            'LC': {
                0: 1,
                1: 4.2,
                2: 10,
                3: 30,
                4: 100
            }
        }
        self._current_ranges_all = {
            'HC': {
                0: 0.050,
                1: 0.150,
                2: 0.500,
                3: 1.5,
                4: 5,
                5: 15
            },
            'LC': {
                0: 0.00107,
                1: 0.0032,
                2: 0.011,
                3: 0.033,
                4: 0.110,
                5: 0.340
            }
        }
        # This can contain a datetime before which no communication should be
        # attempted
        self._available_time = None

    def send_verify(
        self, message,
        raw_reply=False, skip_verify=False,
        check_availability=True, block_until_available=False
    ):
        '''This is a wrapper for the OPETBus's send_verify method.

        If `check_availability`, this checks if the OPET's `available_time`
        property is in the future. If it is, we raise NotAvailableError,
        except if `block_until_available` is also true, in which case we wait
        until `available_time` before attempting communication.'''
        if check_availability:
            while not self.available:
                if block_until_available:
                    sleep(0.02)
                else:
                    raise NotAvailableError(self.available_time)

        return self._bus.send_verify(
            self._address,
            message,
            raw_reply=raw_reply,
            skip_verify=skip_verify
        )

    def read_eeprom(self, address):
        '''Returns the contents of an EEPROM `address`'''
        return self.send_verify(f'EEROM:READ?\t{address}')[1]

    def write_eeprom(self, address, value):
        '''Sets EEPROM `address` to `value`, returning the value that was
        written (sometimes rounded or reformatted by the hardware).'''
        return self.send_verify(f'EEROM:WRITE\t{address}\t{value}')[1]

    def reset(self, skip_delay=False):
        '''Resets the OPET, sleeping 300 ms before returning. If anything is
        sent during this delay, it won't be properly received and processed.
        If `skip_delay`, the delay is skipped.'''
        self.send_verify('*RST')
        if not skip_delay:
            sleep(0.3)

    @property
    def address_integer(self):
        return self._address_integer

    @property
    def max_voltage_range_index(self):
        return 4

    @property
    def max_current_range_index(self):
        return 5

    @property
    def hardware_configuration(self):
        ''''HC' for the high-current configuration and 'LC' for low-current, 
        based on the highest available current range'''
        highest_current_range = float(self.read_eeprom(82))
        if highest_current_range == 15:
            return 'HC'
        elif highest_current_range == 0.32:
            return 'LC'
        else:
            raise RuntimeError(
                f'Unexpected highest current range {highest_current_range} '
                f'read from EEPROM address 82. Expected 15 (HC) or 0.32 (LC).'
            )

    @property
    def current_ranges(self):
        '''Current ranges, in A, available for this load'''
        return self._current_ranges_all[self.hardware_configuration]

    @property
    def voltage_ranges(self):
        '''Voltage ranges, in V, available for this load'''
        return self._voltage_ranges_all[self.hardware_configuration]

    # @property
    def operation_complete(self):
        # OPET doesn't echo the command for this one, so we skip verification
        return bool(int(self.send_verify(
            '*OPC?', skip_verify=True, raw_reply=True
        ).strip()))

    @property
    def available_time(self):
        return self._available_time

    @available_time.setter
    def available_time(self, time):
        self._available_time = time

    @property
    def available(self):
        if self.available_time is None:
            return True
        else:
            return datetime.now().astimezone() >= self.available_time

    @property
    def status_integer(self):
        return int(self.send_verify('*SBR?')[0])
    
    @staticmethod
    def parse_system_status_integer(integer):
        '''Parses the system status integer, returned as the `status` item
        of `get_sample()` or as the .status property, into a human-readable
        dictionary.

        Can be called without a device connection:
            OPET.parse_system_status_integer(5)
        '''
        status_bits = [
            'output_enabled',
            'calibration_mode',
            'voltage_input_error',
            'current_input_error',
            'overcurrent_bypass',
            'bias_voltage_error',
            'temperature_1_alarm',
            'temperature_2_alarm',
            'main_loop_timer_overrun',
            'iv_data_ready',
            'voltage_range_hold_up',
            'current_range_hold_up'
        ]
        status = dict.fromkeys(status_bits, 0)
        for n, key in enumerate(status_bits):
            if integer & (1 << n):
                status[key] = 1
        return status

    @property
    def status(self):
        return self.parse_system_status_integer(self.status_integer)
    
    @property
    def sample(self):
        '''Dictionary with a single measurement sample'''
        keys = [
            'status_integer',
            'voltage',
            'current',
            'voltage_offset_internal',
            'voltage_bias',
            'temperature_1',
            'temperature_2'
        ]
        measurement_time = datetime.now().astimezone()
        reply = self.send_verify('READ?')
        reply = dict(zip(keys, reply))
        for key in keys[1:]:
            reply[key] = float(reply[key])
        reply['power'] = reply['voltage']*reply['current']
        reply['status_integer'] = int(reply['status_integer'])
        reply['measurement_time'] = measurement_time
        reply.update(self.parse_system_status_integer(reply['status_integer']))
        reply.update({'address_integer': self._address_integer})
        return reply

    @property
    def identification(self):
        keys = [
            'hardware_version', 'software_version', 'serial_number'
        ]
        reply = self.send_verify('*IDN?')
        return dict(zip(keys, reply))

    @property
    def output_enabled(self):
        return self.status['output_enabled']

    @output_enabled.setter
    def output_enabled(self, requested_value):
        if requested_value:
            requested_value = 1
        else:
            requested_value = 0
        self.send_verify('OUTP\t' + str(requested_value))
        # It can take a bit of time for the output status to change
        sleep(0.02)
        actual_value = self.output_enabled
        if actual_value != requested_value:
            raise RuntimeError(f'''The requested `output_enabled` value was
                {requested_value} but the hardware set it to {actual_value}''')

    @property
    def mode(self):
        '''The load mode of the OPET, set as a string or integer and returned
        as an integer:
        'off': 0
        'voc': 1
        'isc': 2
        'vset': 3
        'cset': 4
        'mppt': 5'''
        return int(self.send_verify('LOAD:MODE?')[0])

    @mode.setter
    def mode(self, mode):
        modes = {
            'off': 0,
            'voc': 1,
            'isc': 2,
            'vset': 3,
            'cset': 4,
            'mppt': 5
        }
        if not isinstance(mode, int):
            mode = modes[mode]
        self.send_verify('LOAD:MODE\t' + str(mode))
        # We can only check the actual value of mode if output is enabled,
        # otherwise we have to trust the system
        if self.output_enabled:
            actual_value = self.mode
            if actual_value != mode:
                raise RuntimeError(f'''The requested `mode` value was
                    {mode} but the hardware set it to {actual_value}''')

    @property
    def fixed_voltage(self):
        '''The fixed voltage setting, which is only used when .mode is 3
        ('vset') and output is 1 (on)'''
        return float(self.send_verify('LOAD:SETVOLT?')[0])

    @fixed_voltage.setter
    def fixed_voltage(self, value):
        self.send_verify('LOAD:SETVOLT\t' + str(value))
        actual_value = self.fixed_voltage
        if actual_value != value:
            raise RuntimeError(f'''The requested `fixed_voltage` value was
                {value} but the hardware set it to {actual_value}''')

    @property
    def fixed_current(self):
        '''The fixed current setting, which is only used when .mode is 4
        ('cset') and output is 1 (on)'''
        return float(self.send_verify('LOAD:SETCURR?')[0])

    @fixed_current.setter
    def fixed_current(self, value):
        self.send_verify('LOAD:SETCURR\t' + str(value))
        actual_value = self.fixed_current
        if actual_value != value:
            raise RuntimeError(f'''The requested `fixed_current` value was
                {value} but the hardware set it to {actual_value}''')

    def start_iv_curve(self, delay=False):
        '''Requests an I-V curve measurement. The actual measurement is read
        back using the .iv_data property. Returns an estimated time, in ms, for
        the curve to complete. If `delay` is True, this blocks for this amount
        of time.

        If this method returns zero, the measurement has not been started.
        Possible reasons include:
        - bias voltage error is active
        - probably others

        After the curve is started, the unit can receive messages, but can't
        respond until the curve is finished. This method automatically sets
        the `available_time` property to the datetime when the measurement is
        expected to be finished. It is suggested that communication not be
        attempted before `available_time` is reached.'''
        reply = self.send_verify('IV:MEAS')
        expected_measurement_duration = int(reply[0]) / 1000
        self.available_time = (
            datetime.now().astimezone()
            + timedelta(seconds=(
                self.iv_time_multiplier * expected_measurement_duration
            ))
        )
        if delay:
            sleep(expected_measurement_duration)
        return expected_measurement_duration

    @property
    def iv_data(self):
        '''Stored I-V curve data from the latest IV or transient measurement.
        The measurement is updated using `start_iv_curve()`.'''
        result = {}
        reply = self.send_verify('IV:DATA?')
        # TODO: parse this iv_status integer into a human-readable dictionary
        result['iv_status'] = int(reply[0])
        result['voltage'] = [float(value) for value in reply[1::2]]
        result['current'] = [float(value) for value in reply[2::2]]
        return result

    @property
    def n_adc_average_vc(self):
        '''Number of voltage and current measurements averaged per cycle'''
        return int(self.send_verify('ADC:AVR:VC?')[0])

    @n_adc_average_vc.setter
    def n_adc_average_vc(self, value):
        self.send_verify('ADC:AVR:VC\t' + str(value))
        actual_value = self.n_adc_average_vc
        if actual_value != value:
            raise RuntimeError(f'''The requested `n_adc_average_vc` value was
                {value} but the hardware set it to {actual_value}''')

    @property
    def n_adc_cycles_vc(self):
        '''Number of cycles averaged for current and voltage'''
        return int(self.send_verify('ADC:CYCLES:VC?')[0])

    @n_adc_cycles_vc.setter
    def n_adc_cycles_vc(self, value):
        self.send_verify('ADC:CYCLES:VC\t' + str(value))
        actual_value = self.n_adc_cycles_vc
        if actual_value != value:
            raise RuntimeError(f'''The requested `n_adc_cycles_vc` value was
                {value} but the hardware set it to {actual_value}''')
    
    @property
    def n_adc_average_other(self):
        '''Number of measurements other than voltage and current averaged
        per cycle'''
        return int(self.send_verify('ADC:AVR:OTHER?')[0])

    @n_adc_average_other.setter
    def n_adc_average_other(self, value):
        self.send_verify('ADC:AVR:OTHER\t' + str(value))
        actual_value = self.n_adc_average_other
        if actual_value != value:
            raise RuntimeError(f'''The requested `n_adc_average_other` value
                was {value} but the hardware set it to {actual_value}''')

    @property
    def gain_proportional(self):
        '''Index of the resistor that sets the proportional gain of the analog
        PI regulator. Possible values are (0, 1, 2, 3). Increasing the value
        increases the value of the resistor, making the loop slower, but more
        stable.'''
        return int(self.send_verify('DRIV:IDGAIN?')[0])

    @gain_proportional.setter
    def gain_proportional(self, value):
        self.send_verify('DRIV:IDGAIN\t' + str(value))
        actual_value = self.gain_proportional
        if actual_value != value:
            raise RuntimeError(f'''The requested `gain_proportional`
                value was {value} but the hardware set it to {actual_value}''')

    @property
    def gain_integral(self):
        '''Index of the capacitor that sets the integral gain of the analog
        PI regulator. Possible values are (0, 1, 2, 3). Increasing the value
        increases the value of the capacitor, making the loop slower, but more
        stable.'''
        return int(self.send_verify('DRIV:IDINT?')[0])

    @gain_integral.setter
    def gain_integral(self, value):
        self.send_verify('DRIV:IDINT\t' + str(value))
        actual_value = self.gain_integral
        if actual_value != value:
            raise RuntimeError(f'''The requested `gain_integral`
                value was {value} but the hardware set it to {actual_value}''')

    @property
    def voltage_range_index(self):
        '''Index of the voltage range. See load.voltage_ranges for values.
        'auto' is a special value that sets the load to auto-range.'''
        reply = self.send_verify('RANGE:IDVOLT?')[0]
        if reply == b'auto':
            return reply
        else:
            return int(reply)

    @voltage_range_index.setter
    def voltage_range_index(self, value):
        # When autoranging, the OPET returns 'auto' for RANGE:IDVOLT, but it
        # does not accept 'auto' as a command. Instead, it interprets any
        # out-of-range positive integer as the command to auto-range. So when
        # this setter gets 'auto', we instead send a definitely out-of-range
        # number here:
        if isinstance(value, str):
            value = value.encode('ASCII')
        if value == b'auto':
            self.send_verify('RANGE:IDVOLT\t' + str(999))
        else:
            self.send_verify('RANGE:IDVOLT\t' + str(value))
        actual_value = self.voltage_range_index
        if actual_value != value:
            raise RuntimeError(f'''The requested `voltage_range_index`
                value was {value} but the hardware set it to {actual_value}''')

    @property
    def current_range_index(self):
        '''Index of the current range. See load.current_ranges_all for values.
        'auto' is a special value that sets the load to auto-range.'''
        reply = self.send_verify('RANGE:IDCURR?')[0]
        if reply == b'auto':
            return reply
        else:
            return int(reply)

    @current_range_index.setter
    def current_range_index(self, value):
        # When autoranging, the OPET returns 'auto' for RANGE:IDCURR, but it
        # does not accept 'auto' as a command. Instead, it interprets any
        # out-of-range positive integer as the command to auto-range. So when
        # this setter gets 'auto', we instead send a definitely out-of-range
        # number here:
        if isinstance(value, str):
            value = value.encode('ASCII')
        if value == b'auto':
            self.send_verify('RANGE:IDCURR\t' + str(999))
        else:
            self.send_verify('RANGE:IDCURR\t' + str(value))
        actual_value = self.current_range_index
        if actual_value != value:
            raise RuntimeError(f'''The requested `current_range_index`
                value was {value} but the hardware set it to {actual_value}''')

    @property
    def ranges(self):
        '''Currently active (voltage, current) range, in a tuple'''
        # OPET firmware does not correctly echo the question mark in this query
        # so we skip verification on this one
        ranges = self.send_verify('RANGE:ACTVAL?', skip_verify=True)
        return [float(range) for range in ranges]

    @property
    def current_range(self):
        '''Present current range, in A'''
        return self.ranges[1]

    @property
    def voltage_range(self):
        '''Present voltage range, in V'''
        return self.ranges[0]

    def activate_voltage_calibration_mode(self):
        self.send_verify('RANGE:CAL:MODE\tVOLT')

    def activate_current_calibration_mode(self):
        self.send_verify('RANGE:CAL:MODE\tCURR')

    @property
    def calibration_scale(self):
        return float(self.send_verify('RANGE:CAL:SCALE?')[0])

    @calibration_scale.setter
    def calibration_scale(self, scale_new):
        self.send_verify(f'RANGE:CAL:SCALE\t{scale_new:.5e}')
        actual_value = self.calibration_scale
        scale_new_rounded = float(f'{scale_new:.5e}')
        if actual_value != scale_new_rounded:
            raise RuntimeError(f'''
                The requested `calibration_scale` value was {scale_new_rounded}
                but the hardware set it to {actual_value}
            ''')
    
    @property
    def calibration_offset(self):
        return float(self.send_verify('RANGE:CAL:OFFSET?')[0])

    @calibration_offset.setter
    def calibration_offset(self, offset_new):
        self.send_verify(f'RANGE:CAL:OFFSET\t{offset_new:.5e}')
        actual_value = self.calibration_offset
        offset_new_rounded = float(f'{offset_new:.5e}')
        if actual_value != offset_new_rounded:
            raise RuntimeError(f'''
                The requested `calibration_offset` value was
                {offset_new_rounded} but the hardware set it to {actual_value}
            ''')
