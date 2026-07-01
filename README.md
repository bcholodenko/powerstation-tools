# powerstation-tools

Local control for a WiFi-connected Vanpowers Power Station Pro 1500/2000 and Zendure SuperBase Pro 1500/2000 power stations, over
its own TCP socket - no cloud account, no MQTT, no internet required.

<img width="858" height="1154" alt="image" src="https://github.com/user-attachments/assets/99684f48-543b-4d75-9556-30526ed12eaf" />

## Why

These devices normally rely on a vendor mobile client that talks to them
over MQTT via the cloud, even when you're standing right next to the
unit on the same network. This project talks to the device directly
over its local TCP socket (`192.168.4.1:5000` on the device's own
hotspot, or its LAN IP once joined to your WiFi), reverse-engineered
from the vendor client's protocol.

## Contents

- **`powerstation_control.py`** - the protocol client and a CLI. Can be
  used standalone (`python3 powerstation_control.py --status`) or
  imported as a library (`PowerstationClient`).
- **`powerstation_bridge.py`** - a small local HTTP/JSON server that
  wraps the client, so a browser can control the device. Serves the
  dashboard at `/`.
- **`powerstation_dashboard.html`** - a dark-mode web dashboard: live
  status, master/AC/DC/ambient-light/beep/AmpUp/sleep switches, LED
  color and brightness, charge limit and charge speed, AC frequency,
  and WiFi provisioning.

## Quick start

```
python3 powerstation_bridge.py
```

Then open `http://localhost:8090`.

The bridge listens on `0.0.0.0:8090` with no authentication - keep it
on a trusted network. Anyone who can reach that port can control the
device.

## Standalone CLI

```
python3 powerstation_control.py --status
python3 powerstation_control.py --ac-output on
python3 powerstation_control.py --dc-output off
python3 powerstation_control.py --master-switch on
python3 powerstation_control.py --beep off
python3 powerstation_control.py --sleep-mode enable
python3 powerstation_control.py --amp-up on
python3 powerstation_control.py --charge-limit 90
python3 powerstation_control.py --charge-speed 1200
python3 powerstation_control.py --led-brightness 60
python3 powerstation_control.py --led-color 7
python3 powerstation_control.py --ambient-light on
python3 powerstation_control.py --wifi-ssid "MyNetwork" --wifi-pass 'secret123'
```

Run with `--help` for the full list, including a few experimental
commands found by probing that aren't confirmed safe.

## WiFi provisioning

Join the device to your home network:

1. Connect your computer to the device's own WiFi hotspot.
2. Run the `--wifi-ssid`/`--wifi-pass` command above, or use the WiFi
   section of the dashboard.
3. Reconnect to your normal network - the device will now be reachable
   on your LAN. Use `--scan` (or the dashboard's subnet scan) to find
   its new IP if needed.


## Disclaimer

Unofficial and not affiliated with or endorsed by
the device manufacturer. Use at your own risk - incorrect commands are
unlikely to damage the unit, but a few of the experimental ones are
explicitly untested for side effects.
