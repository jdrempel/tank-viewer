import serial
from serial import Serial
import time

from main import crc16_mcrf4xx

if __name__ == "__main__":
    with Serial("/dev/ttyUSB0", baudrate=19200, timeout=1) as ser:
        command = ""
        while command != "quit":
            command = input(">> ")
            data = ""
            if command == "tare":
                data = "T"
            elif command == "zero":
                data = "Z0"
            elif command == "reset":
                data = "R"
            elif command == "quit":
                break
            else:
                continue

            data += ";"
            print(data)
            ser.write(data.encode('ascii'))

            while ser.in_waiting > 0:
                print(ser.readline())
