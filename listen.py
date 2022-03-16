import serial
from serial import Serial
import time

from main import crc16_mcrf4xx

if __name__ == "__main__":
    with Serial("/dev/ttyUSB0", baudrate=19200, timeout=1) as ser:
        while True:
            while ser.in_waiting > 0:
                print(ser.read())
