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
hotspot, or its LAN IP once joined to your WiFi), using the same
protocol as the vendor's own mobile client.

## Contents

- **`powerstation_control.py`** - the protocol client and a CLI. Can be
  used standalone (`python3 powerstation_control.py --status`) or
  imported as a library (`PowerstationClient`).
- **`powerstation_bridge.py`** - a small local HTTP/JSON server that
  wraps the client, so a browser can control the device. Serves the
  dashboard at `/`.
- **`powerstation_dashboard.html`** - a dark-mode web dashboard: live
  status, master/AC/DC/ambient-light/beep/AmpUp/sleep switches, LED
  color and brightness, charge limit and charge speed.
- **`ios-app/`** - a native SwiftUI iPhone app with the same local,
  cloud-free control: live status, all the switches, LED color and
  brightness, charge limit and speed, and standby/screen-timeout
  settings. Talks directly to the device's TCP socket - no bridge
  server required. See setup instructions below.

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
```

Run with `--help` for the full list, including a few experimental
commands found by probing that aren't confirmed safe.

## iOS App

A native SwiftUI iPhone app in [`ios-app/`](ios-app/), built directly
on top of the same protocol - it's its own TCP client (via
`Network.framework`), not a wrapper around the bridge server, so it
works with nothing else running.

**Status tab** - live battery, AC/DC input and output watts, and
toggles for master/AC/DC/ambient light/beep/sleep/AmpUp.
**LED tab** - color and brightness, with a live preview before
applying.
**Charging tab** - charge limit (70/80/90/100%) and max AC charge
speed (300/500/800/1200/1800W).
**Settings tab** - connection host/port, Keep Powered On, Screen
Timeout (10s/30s/1m/5m/30m/Never - matches the web dashboard exactly),
and power controls (AmpUp trigger, Power Off).

It's source you build yourself in Xcode, not an App Store download - a
free Apple ID is enough to run it on your own phone.

### Setup

1. In Xcode: **File → New → Project → iOS → App**. Name it
   "Powerstation", interface **SwiftUI**. Set the deployment target to
   iOS 17 or later (target → General → Minimum Deployments).
2. Delete the auto-generated `ContentView.swift` and app-entry file
   Xcode created, then drag in `ios-app/Sources` and
   `ios-app/Assets.xcassets` (check "Copy items if needed," and make
   sure both are added to the app target).
3. Add two keys under target → **Info**: `NSLocalNetworkUsageDescription`
   (String, e.g. "Used to connect to your power station over Wi-Fi")
   and `UILaunchScreen` (Dictionary, can be left empty) - iOS requires
   both for a local-network app built with the iOS 27 SDK.
4. Under target → **Signing & Capabilities**, pick a Team (your Apple
   ID). A free account works for installing on your own phone; it just
   needs re-running from Xcode every 7 days to stay signed.
5. Plug in your iPhone, select it as the run destination, and hit
   **Run**. The simulator has no real Wi-Fi radio, so this only works
   on a physical device. First run may prompt you to enable Developer
   Mode (**Settings → Privacy & Security → Developer Mode** on the
   phone, then restart) and to trust the developer certificate
   (**Settings → General → VPN & Device Management**).
6. In the app: get the device on the same Wi-Fi network first or join the power station hotspot, then open **Settings**, enter
   its address (`192.168.4.1:5000` on its own hotspot, or its LAN IP
   once it's joined your Wi-Fi), and tap **Connect** on the **Status**
   tab.

## Disclaimer

Unofficial and not affiliated with or endorsed by
the device manufacturer. Use at your own risk - incorrect commands are
unlikely to damage the unit, but a few of the experimental ones are
explicitly untested for side effects.
