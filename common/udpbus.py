"""UDP bus: one destination address, one port per channel, any number of
subscribers per port on the same host.

Transport decision (frozen here so nothing else cares):
- Default mode is IPv4 subnet **broadcast on the loopback network**
  (127.255.255.255). The whole demo runs on one host; loopback broadcast
  needs no NIC, no IGMP, no routes, and survives network changes.
- **Multicast** (239.42.0.1) is implemented for multi-host setups:
  AIRKAL_BUS_MODE=multicast.

All receive sockets set SO_REUSEADDR + SO_REUSEPORT: the kernel delivers each
broadcast/multicast datagram to every socket bound to the port, so agents,
C2 and netstats can all listen to the same channel concurrently.

This module moves raw bytes only; schema encode/decode lives in common.msg.
"""

import asyncio
import logging
import socket
import struct
from typing import Callable

from common import config

log = logging.getLogger(__name__)

def tx_addr(port: int) -> tuple[str, int]:
    if config.BUS_MODE == "multicast":
        return (config.MULTICAST_GROUP, port)
    return (config.BROADCAST_ADDR, port)

def make_tx_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if config.BUS_MODE == "multicast":
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL,
                        config.MULTICAST_TTL)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    return sock

def make_rx_socket(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.bind(("", port))
    if config.BUS_MODE == "multicast":
        mreq = struct.pack("=4sl", socket.inet_aton(config.MULTICAST_GROUP),
                           socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    return sock

class BusSender:
    """Blocking-free datagram publisher for one channel port."""

    def __init__(self, port: int):
        self._addr = tx_addr(port)
        self._sock = make_tx_socket()
        self.tx_msgs = 0
        self.tx_bytes = 0

    def send(self, payload: bytes) -> int:
        sent = self._sock.sendto(payload, self._addr)
        self.tx_msgs += 1
        self.tx_bytes += sent
        return sent

    def close(self) -> None:
        self._sock.close()

class _RxProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_datagram: Callable[[bytes, tuple], None]):
        self._on_datagram = on_datagram

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        try:
            self._on_datagram(data, addr)
        except Exception:  # a bad packet must never kill the receive loop
            log.exception("unhandled error in datagram handler")

    def error_received(self, exc: OSError) -> None:
        log.warning("udp receive error: %s", exc)

async def open_rx(port: int,
                  on_datagram: Callable[[bytes, tuple], None]
                  ) -> asyncio.DatagramTransport:
    """Subscribe to a channel port; on_datagram(data, addr) per packet.

    Returns the transport; call .close() to unsubscribe.
    """
    loop = asyncio.get_running_loop()
    sock = make_rx_socket(port)
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _RxProtocol(on_datagram), sock=sock)
    return transport
