#!/usr/bin/env python3
import serial
import struct
import sys

FRAME_HEAD = b'\xFD\xFC\xFB\xFA'
FRAME_END = b'\x04\x03\x02\x01'
GET_VERSION = FRAME_HEAD + b'\x02\x00' + b'\x00\x00' + FRAME_END

CMD_ENABLE_CFG_SUCCESS = b'\xFF\x01'
CMD_FW_VERSION_SUCCESS = b'\x00\x01'

COMMAND_WORDS = {
    CMD_ENABLE_CFG_SUCCESS: 'enable config success',
    CMD_FW_VERSION_SUCCESS: 'firmware version',
}

def unframe(buf):
    try:
        end_idx = buf.index(FRAME_END)
        remainder = buf[end_idx+4:]
        try:
            start_idx = buf.index(FRAME_HEAD)
            data = buf[start_idx+4:end_idx]
            data_len = struct.unpack('<H', data[0:2])[0]
            if len(data) != data_len + 2:
                print(f"expected length {data_len} but got {len(data)-2}")
            return data[2:], remainder
        except Exception as e:
            return None, remainder
    except:
        return None, buf

def parse(data):
    if data[0:2] not in COMMAND_WORDS:
        return "unknown command word"

    ret = COMMAND_WORDS[data[0:2]]

    if data[0:2] == CMD_FW_VERSION_SUCCESS:
        equipment_type = data[2:6]
        version_type = data[6:8]
        major, minor, patch = struct.unpack('<HHH', data[8:14])
        ret += f". equipment type = 0x{equipment_type.hex()}, version type = 0x{version_type.hex()}, version = {major}.{minor}.{patch}"
    return ret        


def main(dev: str):
    print(f"Opening {dev}...")
    did_write = False

    buf = b''
    with serial.Serial(dev, 115200, timeout=1) as ser:
        ser.write(GET_VERSION)
        while True:
            buf += ser.read()
            data, buf = unframe(buf)
            if data:
                print(f'{data.hex()}: {parse(data)}')
                if not did_write:
                    ser.write(GET_VERSION)
                    did_write = True

if __name__ == '__main__':
    dev = sys.argv[1] if len(sys.argv) > 1 else '/dev/ttyUSB0'
    main(dev)
