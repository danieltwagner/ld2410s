#!/usr/bin/env python3
import serial
import struct
import sys

FRAME_HEAD = b'\xFD\xFC\xFB\xFA'
FRAME_END = b'\x04\x03\x02\x01'
def frame(cmd, value):
    data_len = struct.pack('<H', len(cmd) + len(value) + 1)
    return FRAME_HEAD + data_len + cmd + b'\x00' + value + FRAME_END

STATUS_SUCCESS = b'\x00\x00'

class Commands:
    CONFIG_START    = frame(b'\xFF', b'\x01\x00')
    CONFIG_END      = frame(b'\xFE', b'')
    GET_VERSION     = frame(b'\x00', b'')
    PARAMS_READ     = frame(b'\x71', b'\x02\x00\x0c\x00\x05\x00\x0a\x00\x06\x00\x0b\x00')
    SERIAL_READ     = frame(b'\x11', b'')

class Responses:
    CONFIG_START    = b'\xFF\x01'
    CONFIG_END      = b'\xFE\x01'
    GET_VERSION     = b'\x00\x01'
    PARAMS_READ     = b'\x71\x01'
    SERIAL_READ     = b'\x11\x01'

class LD2410s:
    def __init__(self, serial: serial.Serial) -> None:
        self.serial = serial
        self.buf = b''
        self.waiting_for_frame = False

        self.config_started = False

        self.version = None
        self.serial_number = None
        self._freq_status = None         # parameter 02 (0.5-8Hz, .5 increment)
        self._freq_distance = None       # parameter 0C (0.5-8Hz, .5 increment)
        self._distance_max = None        # parameter 05 (1-16 -> max 11.2m)
        self._distance_min = None        # parameter 0A (0-16 -> max 11.2m)
        self._unattended_delay = None    # parameter 06 (10-120s)
        self._response_speed = None      # parameter 0B (5=normal, 10=fast)

    @property
    def freq_status(self):
        return self._freq_status * 0.1
    
    @freq_status.setter
    def freq_status(self, val: float):
        if val < 0.5 or val > 8:
            raise Exception(f"Value {val} out of range 0.5 - 8")
        self._freq_status = int(val * 2)/2 # force it to be 0.5 increment

    @property
    def freq_distance(self):
        return self._freq_distance * 0.1
    
    @freq_distance.setter
    def freq_distance(self, val: float):
        if val < 0.5 or val > 8:
            raise Exception(f"Value {val} out of range 0.5 - 8")
        self._freq_distance = int(val * 2)/2 # force it to be 0.5 increment

    @property
    def distance_max(self):
        return round(self._distance_max * 0.7, 1) # convert 0-16 to 0-11.2m

    @property
    def distance_min(self):
        return round(self._distance_min * 0.7, 1) # convert 0-16 to 0-11.2m

    @property
    def unattended_delay(self):
        return self._unattended_delay

    @property
    def response_speed(self):
        return "fast" if self._response_speed == 10 else "normal"

    def done_reading(self) -> bool:
        return self.get_next_cmd() is None

    # Most commands rely on having config enabled first
    def with_config(self, cmd: bytes) -> bytes:
        return Commands.CONFIG_START if not self.config_started else cmd

    def get_next_cmd(self) -> bytes:
        if not self.version:
            return Commands.GET_VERSION

        if not self.serial_number:
            return self.with_config(Commands.SERIAL_READ)

        if not self._freq_status:
            return self.with_config(Commands.PARAMS_READ)

        # We have fetched all configuration. Exit config mode again
        if self.config_started:
            return Commands.CONFIG_END

        return None

    # Fetch more information. Returns whether more information was requested
    def update(self) -> bool:
        self.buf += self.serial.read()
        data = self.unframe()
        if data:
            self.parse(data)
            self.waiting_for_frame = False

        if not self.waiting_for_frame and not self.done_reading():
            self.serial.write(self.get_next_cmd())
            self.waiting_for_frame = True

        return self.waiting_for_frame

    def unframe(self) -> bytes:
        try:
            end_idx = self.buf.index(FRAME_END)
            remainder = self.buf[end_idx+4:]
            try:
                start_idx = self.buf.index(FRAME_HEAD)
                data = self.buf[start_idx+4:end_idx]
                data_len = struct.unpack('<H', data[0:2])[0]
                if len(data) != data_len + 2:
                    print(f"expected length {data_len} but got {len(data)-2}")

                self.buf = remainder
                return data[2:]

            except Exception as e:
                # didn't find a FRAME_START marker (should really only happen at the very beginning)
                self.buf = remainder
                return None
        except:
            # Didn't find a FRAME_END marker
            return None

    def parse(self, data: bytes) -> None:
        resp_word = data[0:2]
        match resp_word:
            case Responses.CONFIG_START:
                self.config_started = True
                return

            case Responses.CONFIG_END:
                if len(data) < 4: raise Exception("Malformed response")
                if data[2:4] == STATUS_SUCCESS:
                    self.config_started = False
                return

            case Responses.GET_VERSION:
                if len(data) < 14: raise Exception("Malformed version response")
                equipment_type = data[2:6]
                version_type = data[6:8]
                major, minor, patch = struct.unpack('<HHH', data[8:14])
                self.version = f"{major}.{minor}.{patch}"
                return

            case Responses.PARAMS_READ:
                if data[2:4] == STATUS_SUCCESS:
                    # we expect 6 responses of 4 bytes each
                    if len(data) < (4+4*6): raise Exception("Malformed parameter response")
                    (
                        self._freq_status,
                        self._freq_distance,
                        self._distance_max,
                        self._distance_min,
                        self._unattended_delay,
                        self._response_speed
                    ) = struct.unpack('<IIIIII', data[4:])
                return

            case Responses.SERIAL_READ:
                if len(data) < 4: raise Exception("Malformed response")
                if data[2:4] == STATUS_SUCCESS:
                    serial_len = struct.unpack('<H', data[4:6])[0]
                    self.serial_number = struct.unpack(f'<{serial_len}s', data[6:6+serial_len])[0].decode('ascii')
                return

            case _:
                print(f"Received unknown response 0x{resp_word.hex()}")
                return

def main(dev: str):
    print(f"Opening {dev}...")

    buf = b''
    with serial.Serial(dev, 115200, timeout=1) as ser:
        sensor = LD2410s(ser)
        while sensor.update():
            pass

    print(f"Version:          {sensor.version}")
    print(f"Serial:           {sensor.serial_number}")
    print(f"Freq status:      {sensor.freq_status} Hz")
    print(f"Freq distance:    {sensor.freq_distance} Hz")
    print(f"Distance max:     {sensor.distance_max} m")
    print(f"Distance min:     {sensor.distance_min} m")
    print(f"Unattended delay: {sensor.unattended_delay} s")
    print(f"Response sepeed:  {sensor.response_speed}")

if __name__ == '__main__':
    dev = sys.argv[1] if len(sys.argv) > 1 else '/dev/ttyUSB0'
    main(dev)
