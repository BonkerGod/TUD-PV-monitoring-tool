import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helper_packages"))

from serial_by_serial import list_serial

print(list_serial())