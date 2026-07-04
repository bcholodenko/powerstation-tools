If you found this project useful and want to support it and future projects: [<img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" width="150">](https://buymeacoffee.com/bcholodenko)

# powerstation-tools

Local control for a WiFi-connected Vanpowers Power Station Pro 1500/2000 and Zendure SuperBase Pro 1500/2000 power stations, over
its own TCP socket - no cloud account, no MQTT, no internet required.

<img width="885" height="1178" alt="image" src="https://github.com/user-attachments/assets/1630e9fb-fc61-4892-9272-ebc6f2102038" />

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

Turn the device on. Press the WiFi button to turn it on then off. Hold it until it beeps then join the device SSID.

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

This is featrure is not yet functional and may depend on cloud connectivity.


## Disclaimer

Unofficial and not affiliated with or endorsed by
the device manufacturer. Use at your own risk - incorrect commands are
unlikely to damage the unit, but a few of the experimental ones are
explicitly untested for side effects.
