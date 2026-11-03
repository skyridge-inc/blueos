"""Relay a camera's RTP-wrapped raw H.264 to stdout as a plain H.264 byte stream.

The camera puts an Annex-B H.264 byte stream (start codes included) straight into
RTP payloads instead of RFC 6184 packetization, so RTP H.264 depayloaders reject
it. This drops each datagram's RTP header and writes the rest to stdout for
`ffmpeg -f h264 -i pipe:0`.

Usage: python3 -u rtp_raw_h264.py [port]

Written for a First Sensor DC3C-1-E4P-100 (fixed IP 10.201.41.105, 1280x960 H.264
at 30 fps, pushes RTP to 10.201.41.100:5005; the rover needs that address on the
camera's port). Rover YAML wiring:

  mediamtx:
    config:
      paths:
        dc3c:
          source: publisher
          runOnInit: >-
            sh -c 'python3 -u /usr/blueos/extensions/mediamtx/rtp_raw_h264.py 5005 |
            ffmpeg -hide_banner -loglevel error -use_wallclock_as_timestamps 1 -f h264
            -i pipe:0 -c copy -rtsp_transport tcp -f rtsp rtsp://localhost:8555/dc3c'
          runOnInitRestart: true
    files:
    - mediamtx/rtp_raw_h264.py
  video_streams:
  - name: dc3c
    source: Redirect
    endpoints:
    - rtsp://127.0.0.1:8555/dc3c
"""

import socket
import sys

port = int(sys.argv[1]) if len(sys.argv) > 1 else 5005
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
sock.bind(("0.0.0.0", port))
out = sys.stdout.buffer

while True:
    data = sock.recv(65535)
    if len(data) < 12 or data[0] >> 6 != 2:  # not RTP version 2
        continue
    start = 12 + 4 * (data[0] & 0x0F)  # fixed header + CSRC list
    if data[0] & 0x10:  # header extension
        start += 4 + 4 * int.from_bytes(data[start + 2:start + 4], "big")
    end = len(data) - data[-1] if data[0] & 0x20 else len(data)  # padding
    if start < end:
        try:
            out.write(data[start:end])
            out.flush()
        except BrokenPipeError:
            sys.exit(0)
