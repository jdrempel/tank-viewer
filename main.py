#!/usr/bin/python3

from argparse import ArgumentParser
from io import BytesIO
import re as regex
import serial
from serial import Serial
from sys import platform
import time

if 'linux' in platform:
    from serial.tools import list_ports_linux as list_ports
elif 'darwin' in platform:
    from serial.tools import list_ports_osx as list_ports
elif 'win32' in platform:
    from serial.tools import list_ports_windows as list_ports
else:
    from serial.tools import list_ports_posix as list_ports

CRLF = bytes(bytearray([13, 10]))
BAUD = 115200
TIMEOUT = 1


def configure_port(arg):
    comports = [tuple(p) for p in list(list_ports.comports())]
    comports = [c for c in comports if regex.match(r'(.*Ard.*)|(.*Ser.*)', f'{c[1]} {c[2]}')]

    if len(comports) == 0:
        print('No available ports found, exiting...')
        exit(1)

    selection = 0
    if arg is None:
        print()
        print('No port argument provided -- scanned and found the following candidate(s):')
        for c in comports:
            print(c)

        if len(comports) > 1:
            print('More than one Arduino device found. Please select one:')
            for n, c in enumerate(comports):
                print(f'{n}.', c)
            selection = int(input('Selection:'))

    else:
        sub_comports = [c[0] for c in comports]
        if arg not in sub_comports:
            print(f'Port {arg} not found in list of available ports, exiting...')
            exit(1)
        else:
            selection = sub_comports.index(arg)

    return comports[selection][0]


def check_port_presence(device, backoff):
    try:
        with Serial(device, BAUD, timeout=TIMEOUT) as s:
            s.write(b'0xabc123')
    except serial.PortNotOpenError:
        time.sleep(backoff)
        return False
    return True


if __name__ == '__main__':

    parser = ArgumentParser(description='Display tank weights in real time')
    parser.add_argument('port', type=str, nargs='?')
    parser.add_argument('--max-tries', dest='max_tries', type=int, nargs=1, default=5,
                        help='number of times to attempt a serial connection (default: 5)')
    parser.add_argument('--num-tanks', dest='num_tanks', nargs=1, default=5,
                        help='number of presented air seeder tanks (default: 5)')
    args = parser.parse_args()
    port = configure_port(args.port)

    byte_stream = BytesIO()

    tries = 0
    max_tries = args.max_tries
    success = False
    while tries < max_tries:
        tries += 1
        if check_port_presence(port, tries):
            success = True
            break
        print(f'Unable to communicate on port {port} ({tries}/{max_tries}')

    if success:
        print(f'Established communication with device on port {port}')
    else:
        print(f'Max attempts reached, exiting...')
        exit(1)

    with Serial(port, BAUD, timeout=TIMEOUT) as ser:
        while True:
            try:
                byte_stream.write(ser.read())
            except serial.SerialTimeoutException:
                print(f'Connection with device on port {port} timed out, exiting...')
                exit(1)
            except serial.SerialException:
                print(f'Connection lost on port {port}, exiting...')
                exit(1)

    pass
