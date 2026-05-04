'''
Tool for identifying a serial port's device name based on its serial number
'''

from serial.tools import list_ports


def ports_filtered(port_properties=None, return_attribute=None):
    '''Returns a list of `serial.tools.ListPortInfo` objects, one for each
    connected serial device whose attributes match those specified in the
    dictionary `port_properties`. Acceptable keys are: `description`, `hwid`,
    `interface`, `location`, `manufacturer`, `name`, `pid`, `product`,
    `serial_number` and `vid`. If `port_properties` is None, all ports will
    be returned.

    If `return_attribute` is specified, a list of this attribute of the port is
    returned. Valid attributes include the acceptable keys listed above, plus
    `device`, which can be passed to `serial.Serial` or `aioserial.AioSerial`
    as the `port` argument.'''
    ports = list_ports.comports()
    candidates = []
    for port in ports:
        if port_properties is None:
            candidates.append(port)
        else:
            for attribute, value in port_properties.items():
                if getattr(port, attribute) == value:
                    candidates.append(port)
    if return_attribute is None:
        return candidates
    else:
        return [
            getattr(port, return_attribute)
            for port
            in candidates
        ]


def device_name(serial_number):
    '''Given a serial port's serial number, return a list of device names,
    each of which can be passed to `serial.Serial` or `aioserial.AioSerial`
    as the `port` argument. Returns an empty list if a matching device is not
    found.

    This works on Windows and macOS, with one caveat: Sometimes devices report
    a different serial number to different OSes. For example, Sabrent
    USB-serial adapters have an 8-character alphanumeric serial number on
    macOS. On Windows, these devices have the same serial number, but with an
    'A' appended.'''
    return sorted(ports_filtered({'serial_number': serial_number}, 'device'))


def list_serial():
    '''Lists serial ports and their serial numbers. This helps discover the
    serial numbers of new devices.'''
    return [
        {port.device: port.serial_number}
        for port
        in list_ports.comports()
    ]
