"""netstats: passive UDP traffic statistics.

    python -m netstats.main [--quiet]

Joins all four channels, counts every datagram (including its own 1 Hz stats
messages — they are control-plane traffic too), renders a live CLI table and
publishes the aggregated snapshot on the stats channel for C2/web.
"""

import argparse
import asyncio
import logging
import sys
import time

from common import config, msg, udpbus
from netstats.aggregate import TrafficAggregator
from netstats.cliview import render

log = logging.getLogger("netstats")

class NetStats:
    def __init__(self, quiet: bool):
        self.quiet = quiet
        self.agg = TrafficAggregator(config.PORT_CHANNELS)
        self.stats_tx = udpbus.BusSender(config.PORT_STATS)
        self._seq = 0

    def _handler_for(self, port: int):
        def on_datagram(data: bytes, addr: tuple) -> None:
            self.agg.record(port, data, time.time())
        return on_datagram

    async def run(self) -> None:
        transports = [await udpbus.open_rx(port, self._handler_for(port))
                      for port in config.PORT_CHANNELS]
        log.info("listening on %s", sorted(config.PORT_CHANNELS))
        period = 1.0 / config.STATS_HZ
        try:
            while True:
                await asyncio.sleep(period)
                now = time.time()
                snapshot = self.agg.snapshot(now)
                built = msg.make_stats(self._seq, now,
                                       channels=snapshot["channels"],
                                       malformed=snapshot["malformed"])
                self.stats_tx.send(msg.encode(built))
                self._seq += 1
                if not self.quiet:
                    sys.stdout.write(render(snapshot))
                    sys.stdout.flush()
        finally:
            for tr in transports:
                tr.close()
            self.stats_tx.close()

def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="airkal UDP traffic statistics")
    ap.add_argument("--quiet", action="store_true",
                    help="no CLI table; only publish on the stats channel")
    args = ap.parse_args(argv)
    logging.basicConfig(level="WARNING")
    try:
        asyncio.run(NetStats(args.quiet).run())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
