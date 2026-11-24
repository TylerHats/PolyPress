import socket
import struct
import time
import logging
from datetime import datetime, timedelta

import threading

logger = logging.getLogger("polypress.ntp")

# Global variables to store computed drift offset and last check timestamp
NTP_DRIFT_OFFSET = 0.0  # seconds
LAST_NTP_CHECK = 0.0
_NTP_LOCK = threading.Lock()

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
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(1.5)
            client.sendto(msg, (host, 123))
            data, _address = client.recvfrom(1024)
            if data and len(data) >= 48:
                unpacked = struct.unpack("!12I", data[:48])
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
    if not _NTP_LOCK.acquire(blocking=False):
        return
    try:
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

        LAST_NTP_CHECK = time.time()
        logger.warning("NTP Sync failed: All public NTP servers were unreachable. Defaulting to local host system time.")
    finally:
        _NTP_LOCK.release()

def needs_ntp_refresh() -> bool:
    return (time.time() - LAST_NTP_CHECK > 3600) or (LAST_NTP_CHECK == 0.0)

def refresh_ntp_offset_if_needed():
    if needs_ntp_refresh():
        update_ntp_offset()

def get_time_offset() -> float:
    refresh_ntp_offset_if_needed()
    return NTP_DRIFT_OFFSET

def get_cached_corrected_time() -> datetime:
    """Return UTC time adjusted by cached NTP drift without blocking the caller."""
    return datetime.utcnow() + timedelta(seconds=NTP_DRIFT_OFFSET)

def get_corrected_time() -> datetime:
    offset = get_time_offset()
    return datetime.utcnow() + timedelta(seconds=offset)
