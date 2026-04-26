#!/usr/bin/env python3
"""
VICE Plus/4 DigiMuz I/O tracer.

Launches xplus4 with remote monitor enabled, autostarts the PRG,
sets watchpoints on $FD21-$FD23 (DigiMuz register select/data), and
collects a log of all stores/loads.

Output: build/vice_trace.log with format:
  FRAME  PC     ADDR  OP     VALUE
  ...
"""
import socket, subprocess, time, os, sys, select

PRG = sys.argv[1] if len(sys.argv) > 1 else 'build/play_template.prg'
DURATION_SEC = int(sys.argv[2]) if len(sys.argv) > 2 else 4
MON_PORT = 6510

# Start xplus4 with remote monitor + autostart
# -warp makes it run as fast as possible
# -silent reduces log noise
# Note: -initbreak ready hits break after BASIC is ready, BEFORE the prg runs
cmd = [
    'xvfb-run', '-a', 'xplus4',
    '-warp',
    '-sound', '+soundoutput',   # disable sound output (we're logging, not listening)
    '-remotemonitor',
    '-remotemonitoraddress', f'ip4://127.0.0.1:{MON_PORT}',
    '-autostart', PRG,
]
print(f"[launch] {' '.join(cmd)}")
proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# Wait for monitor socket to come up
sock = None
for retry in range(30):
    time.sleep(0.5)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(('127.0.0.1', MON_PORT))
        break
    except (ConnectionRefusedError, socket.timeout, OSError):
        if sock:
            sock.close()
            sock = None
if sock is None:
    print("[error] could not connect to VICE monitor")
    proc.terminate()
    sys.exit(1)

print("[mon] connected")

def send(cmd, wait=0.2):
    sock.send((cmd + '\n').encode())
    time.sleep(wait)

def recv_all(timeout=0.5):
    sock.settimeout(timeout)
    data = b''
    try:
        while True:
            chunk = sock.recv(65536)
            if not chunk: break
            data += chunk
    except socket.timeout:
        pass
    return data.decode(errors='replace')

# Drain any banner
banner = recv_all(1.0)
print(f"[mon] banner len={len(banner)}")
# print(banner[:500])

# Set watchpoints. VICE monitor syntax:
#   watch store $FD22   -> breakpoint on store
#   watch load $FD21    -> breakpoint on load
# Actually "watch" is for changes. We want stop-on-access which is:
#   break store $FD22 / break load $FD21
# Use "watch" (which triggers without stopping) ... but that needs a tracepoint.
# VICE has "trace" which runs a command and continues.
#
# Easiest: 'watch store $FD21 $FD23' - stops execution on write to that range,
# then we issue 'registers' and 'return' to see state & continue.
# More practical: use tracepoints via 'tr store $FD21 $FD23' that print and continue.
# Let's try 'tr'.

send('tr store $FD21 $FD23')
time.sleep(0.3)
send('tr store $FF09')   # IRQ ack
time.sleep(0.3)
# Start execution
send('x')  # exit monitor, continue
print("[mon] tracepoints installed, continuing execution...")

# Let it run for DURATION_SEC, collecting tracepoint hits via monitor output
time.sleep(DURATION_SEC)

# Break
sock.send(b'\x04')  # ctrl-D? Or send 'monitor' command
time.sleep(0.3)
# Try: send break
# send('mon\n')  # open monitor via hotkey? not via socket probably

# Actually: remote monitor has to be commanded back. Let's hit CPU break.
# VICE monitor responds to `break` from an external source — simplest is Ctrl-C via signal.
# But our sock is the monitor channel. Sending newline on inactive channel should reopen.
# Try sending any command:
send('\n')
time.sleep(0.2)

# Collect any remaining trace output
trace_data = recv_all(2.0)

# Dump + summarize
log_path = 'build/vice_trace.log'
with open(log_path, 'w') as f:
    f.write(trace_data)
print(f"[trace] {len(trace_data)} chars written to {log_path}")

# Quit VICE
send('quit', wait=0.3)
sock.close()
proc.terminate()
try:
    proc.wait(timeout=2)
except subprocess.TimeoutExpired:
    proc.kill()

# Analyze
print("\n=== Trace summary ===")
lines = trace_data.split('\n')
print(f"Total lines: {len(lines)}")
# Show first 40 non-empty lines
nonempty = [l for l in lines if l.strip()]
for l in nonempty[:40]:
    print(f"  {l}")
print(f"... ({len(nonempty)-40} more)" if len(nonempty) > 40 else "")
