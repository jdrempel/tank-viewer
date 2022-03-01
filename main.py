from argparse import ArgumentParser
from io import BytesIO
from serial import Serial

if __name__ == '__main__':
    parser = ArgumentParser(description='Display tank weights in real time')
    parser.add_argument('port', type=str, nargs=1, required=True)

    byte_stream = BytesIO()

    args = parser.parse_args()
    port = args['port']

    with Serial(port, 115200, timeout=1) as ser:
        while True:
            byte_stream.write(ser.read())
            if byte_stream.getbuffer().nbytes >= 8:
                pass  # But actually just read and parse it

    pass
