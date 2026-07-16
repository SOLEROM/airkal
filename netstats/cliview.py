"""Terminal rendering of a traffic snapshot: one aligned table, refreshed in
place with ANSI home+clear."""

_HEADER = ("CHANNEL", "SENDER", "MSG/S", "BYTES/S", "B/MSG", "EMA B/S",
           "TOT MSGS", "TOT KB", "LOSS%")
_WIDTHS = (10, 7, 7, 9, 7, 9, 9, 9, 6)

def _row(cells) -> str:
    return "  ".join(str(c).rjust(w) if i else str(c).ljust(w)
                     for i, (c, w) in enumerate(zip(cells, _WIDTHS)))

def render(snapshot: dict, clear: bool = True) -> str:
    lines = []
    if clear:
        lines.append("\x1b[H\x1b[2J")
    lines.append("airkal netstats — UDP control-plane traffic")
    lines.append(_row(_HEADER))
    lines.append("-" * (sum(_WIDTHS) + 2 * (len(_WIDTHS) - 1)))
    for channel, chan in snapshot.get("channels", {}).items():
        for sender_id, s in chan["senders"].items():
            label = "??" if sender_id == "-1" else sender_id
            lines.append(_row((
                channel, label, s["msgs_1s"], s["bytes_1s"], s["mean_size"],
                s["ema_bytes_s"], s["total_msgs"],
                round(s["total_bytes"] / 1024, 1), s["loss_pct"])))
        tot = chan["total"]
        lines.append(_row((
            channel, "ALL", tot["msgs_1s"], tot["bytes_1s"], "",
            "", tot["total_msgs"], round(tot["total_bytes"] / 1024, 1), "")))
    malformed = snapshot.get("malformed", 0)
    if malformed:
        lines.append(f"malformed packets: {malformed}")
    return "\n".join(lines) + "\n"
