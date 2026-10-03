"""Independent test encoding of the approved IFC STATUS-V3 3.0.0.

No product formatter or MAC helper is used as the oracle. Records from
this module are consumer simulations, never proof that a command ran.
"""
import hashlib
import hmac

KEY = bytes.fromhex('a1' * 32)
EXEC_ID = 'b2' * 16


def record(key=KEY, exec_id=EXEC_ID, outcome='EXITED', rc='0'):
    rc = str(rc)
    message = b'ADC-TERM-STATUS-V3\0' + exec_id.encode('ascii') + b'\0' + outcome.encode('ascii') + b'\0' + rc.encode('ascii')
    tag = hmac.new(key, message, hashlib.sha256).hexdigest()
    return f'ADC-TERM-STATUS-V3 {exec_id} {outcome} {rc} {tag}\n'.encode('ascii')


# Standalone source for INERT terminal fixtures. The trusted fixture reads
# the launch JSON and simulates completion without running installations.
SIMULATED_STATUS_PY = '''from pathlib import Path
import hashlib, hmac, json
launch_path = Path(status_path).with_name('status.key')
launch = json.loads(launch_path.read_text())
launch_path.unlink()
fixture_id = launch['exec_id']
message = b'ADC-TERM-STATUS-V3\\0' + fixture_id.encode('ascii') + b'\\0EXITED\\0' + b'0'
tag = hmac.new(bytes.fromhex(launch['key']), message, hashlib.sha256).hexdigest()
Path(status_path).write_text(f'ADC-TERM-STATUS-V3 {fixture_id} EXITED 0 {tag}\\n')
'''
