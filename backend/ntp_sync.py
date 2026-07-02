import socket
import struct
import time
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("polypress.ntp")

# Global variables to store computed drift offset and last check timestamp
NTP_DRIFT_OFFSET = 0.0  # seconds
LAST_NTP_CHECK = 0.0

NTP_SERVERS = [
    "pool.ntp.org",
    "time.google.com",
    "time.cloudflare.com",
    "time.windows.com"
]

def query_ntp_server(host: str) -> float:
    # NTP client request headers: LI=0, VN=3, Mode=3 (0x1B)
    msg = bytes([0x1B] + [0] * 47)
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.settimeout(1.5)
        client.sendto(msg, (host, 123))
        data, address = client.recvfrom(1024)
        if data:
            unpacked = struct.unpack("!12I", data)
            # Transmit timestamp starts at byte 40 (which is the 10th index of 32-bit integers)
            seconds = unpacked[10]
            # NTP offset from Unix epoch (1900 to 1970)
            TIME1970 = 2208988800
            return float(seconds - TIME1970)
    except Exception as e:
        logger.debug(f"NTP query to {host} failed: {e}")
    return None

def update_ntp_offset():
    global NTP_DRIFT_OFFSET, LAST_NTP_CHECK
    
    for server in NTP_SERVERS:
        ntp_time = query_ntp_server(server)
        if ntp_time is not None:
            local_time = time.time()
            drift = ntp_time - local_time
            NTP_DRIFT_OFFSET = drift
            LAST_NTP_CHECK = local_time
            
            if abs(drift) > 1.0:
                logger.info(f"NTP Sync: System clock drift is {drift:+.3f}s from true network time (using {server})")
            if abs(drift) > 10.0:
                logger.warning(f"NTP Sync WARNING: Large clock drift detected ({drift:+.3f}s). Campaign scheduling will adjust by this offset.")
            return
            
    logger.warning("NTP Sync failed: All public NTP servers were unreachable. Defaulting to local host system time.")

def get_time_offset() -> float:
    global LAST_NTP_CHECK
    # Update drift every hour (3600 seconds)
    if time.time() - LAST_NTP_CHECK > 3600 or LAST_NTP_CHECK == 0.0:
        update_ntp_offset()
    return NTP_DRIFT_OFFSET

def get_corrected_time() -> datetime:
    offset = get_time_offset()
    return datetime.utcnow() + timedelta(seconds=offset)
