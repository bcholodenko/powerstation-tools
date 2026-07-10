# Powerstation — iOS app (Swift/SwiftUI)

A native iPhone app that talks directly to the power station's local
TCP control socket (default `192.168.4.1:5000`) using
`Network.framework` — no Python bridge, no cloud account. It's a
straight port of `powerstation_control.py`'s protocol logic
(CRC16 framing, handshake, status parsing, every command) into Swift.

## What's included

```
Sources/
  Protocol/PowerstationProtocol.swift   CRC16, frame build/parse
  Models/PowerstationStatus.swift       '93' status payload parser
  Networking/PowerstationClient.swift   TCP client (NWConnection), all commands
  ViewModels/PowerstationViewModel.swift  bridges the async client to SwiftUI
  Views/Theme.swift                     shared colors, card style, icon badge
  Views/*.swift                         Status, LED, Charging, Settings tabs
  App/PowerstationApp.swift             @main entry point
Assets.xcassets/AppIcon.appiconset/     app icon (single 1024x1024, matches app theme)
```

## Setting it up in Xcode

1. In Xcode: **File → New → Project → iOS → App**. Name it
   "Powerstation", interface **SwiftUI**, language **Swift**.
2. **Set the deployment target to iOS 17 or later** (target →
   General → Minimum Deployments). The Charging tab uses the
   two-parameter `.onChange(of:) { old, new in }` API, which is iOS
   17+; everything else here needs iOS 16+ for `NavigationStack`. If
   you need to support older iOS, tell me and I'll swap those two spots
   for the older single-parameter form.
3. Delete the auto-generated `ContentView.swift` and
   `PowerstationApp.swift` (or whatever your project's default names
   are) that Xcode created.
4. Drag the `Sources` folder from this download into your project
   navigator (check "Copy items if needed" and add to your app
   target).
4b. Drag in `Assets.xcassets` the same way. If your project already
   has its own `Assets.xcassets` (every new Xcode project creates one
   with an empty `AppIcon` set and an `AccentColor` set inside),
   either delete the project's and use this one instead, or drag this
   project's `AppIcon.appiconset` and `AccentColor.colorset` folders
   into your existing `Assets.xcassets` to replace the empty ones —
   don't end up with two `Assets.xcassets` in the same target, which
   causes a build error over the duplicate catalog. `AccentColor` is
   referenced by an Xcode build setting even though nothing in the
   code reads it directly, so leaving it out entirely causes an
   "Accent color 'AccentColor' is not present in any asset catalogs"
   warning.
5. Add a Local Network usage description: select your target →
   **Info** tab → add row `Privacy - Local Network Usage Description`
   (`NSLocalNetworkUsageDescription`) with a value like *"Used to
   connect to your power station over Wi-Fi."* iOS shows a one-time
   permission prompt for local-network connections (including plain
   TCP to a private IP, not just Bonjour), so this is worth adding
   even though the app doesn't do any device discovery.
6. Build and run on a physical iPhone (the simulator has no real Wi-Fi
   radio, so it can't reach the device).

## Using it

- The device needs to already be on your home Wi-Fi (join it the way
  you normally would — the vendor app, or whatever method you used
  before) before this app can talk to it. This app doesn't include a
  Wi-Fi provisioning flow.
- In **Settings**, enter the device's LAN IP (find it via your
  router's client list, or the device's own screen if it has one),
  then **Connect** from the **Status** tab.
- Everything else — toggles, LED color/brightness, charge limit/speed,
  standby, and power controls — mirrors what
  `powerstation_control.py` and the dashboard already exposed.

## Visual design

- `Sources/Views/Theme.swift` centralizes the look: a warm amber→ember
  accent gradient, a shared card style (`psCard()`), a Settings-style
  colored icon badge (`IconBadge`), and a Liquid Glass capsule modifier
  (`psGlassCapsule()`, iOS 26+ with a material fallback below that).
- The 8 switch/control icons (Master Power, AC Output, DC Output,
  Beep, Ambient Light, AmpUp Mode, Keep Powered On, Sleep Mode) are
  extracted directly from `powerstation_dashboard.html`'s actual icon
  markup — not SF Symbol approximations — so they match the same
  iconography as the web dashboard and, per that markup, the physical
  device itself. `IconBadge` supports both `assetName:` (these) and
  `systemName:` (SF Symbols, used where there's no device-specific
  icon — power flow readouts, charge/LED/settings panels). See
  `Assets.xcassets/icon-*.imageset` for the source images.
- The Status tab's icon badges are intentionally low-color — one
  accent color for almost everything, with red reserved for Master
  Power since it's the one genuinely critical toggle. Earlier drafts
  used a different color per row, which was more decorative than
  informative.
- Whenever a setting changes (any toggle, LED apply, charge
  limit/speed, standby, or power control), a small
  "Applying Setting…" pill floats in from the top using Liquid Glass
  and disappears once the device responds — implemented as a counter
  (`PowerstationViewModel.isApplyingSetting`) so overlapping commands
  don't cause the toast to disappear early.
- The battery ring, LED color/brightness preview, and Charging tab's
  chip-style pickers are new; Settings stays a native `Form` (right
  tool for text fields) but with matching section-header icons.
- The app icon (`Assets.xcassets/AppIcon.appiconset`) and the optional
  splash overlay share the same gradient + bolt motif for a consistent
  first impression.
- To change the accent color, edit the two colors in `PSTheme.accent`
  and `PSTheme.accentSolid` in `Theme.swift` — everything else derives
  from those two values.

## Launch screen (required for iOS 27 / ITMS-90870) — and a note on UIScene

Apple's iOS 27 SDK enforces **ITMS-90870**: any app built with it must
declare a launch screen, or it's rejected at submission / fails to
launch. This is Apple's *launch screen* — an instant, static screen
shown before your code runs — not a branded splash screen with a
delay (which the HIG generally discourages).

This app is built entirely on SwiftUI's `App`/`Scene` lifecycle
(`WindowGroup` in `PowerstationApp.swift`) — there's no `AppDelegate`
or `SceneDelegate` here at all, because it never needed one. That's
already the scene-based lifecycle Apple's TN3187 requires; Xcode
generates the `UIApplicationSceneManifest` entry for you automatically
for this kind of app. Nothing to change for that part.

For the launch screen itself, a template `Info.plist` is included at
the root of this download with the required `UILaunchScreen` key
(plus the local-network usage description from earlier). **Merge
these two keys into your project's Info.plist — don't replace the
whole file with this one.** A full replace risks silently dropping the
`UIApplicationSceneManifest` entry (or anything else) Xcode's own
template already put there, which would reintroduce the exact
scene-lifecycle crash described above. Two ways to merge:

- **If your project has no physical Info.plist** (the default for new
  Xcode 15+ SwiftUI projects — check target → Build Settings → search
  "Generate Info.plist File"): open target → **Info** tab and add the
  two keys there directly — `UILaunchScreen` (Dictionary, with
  `UIColorName` / `UIImageName` sub-keys if you want a background
  color and logo, or leave it empty for a plain default) and
  `NSLocalNetworkUsageDescription` (String). Check first whether
  `UILaunchScreen` (or `UILaunchStoryboardName`/`UILaunchStoryboards`/
  `UILaunchScreens`) is already present — recent Xcode templates often
  already include one, in which case there's nothing to add.
- **If your project has a physical Info.plist**, open both files
  side by side and copy just the `UILaunchScreen` and
  `NSLocalNetworkUsageDescription` entries into your existing one.

If you use the `UIColorName`/`UIImageName` keys, add a color set named
`LaunchBackground` and an image set named `LaunchLogo` to
`Assets.xcassets` — otherwise just delete those two lines and keep
`UILaunchScreen` as an empty dictionary.

Separately, `Sources/Views/SplashScreenView.swift` is an **optional,
purely cosmetic** in-app splash overlay (shown for ~0.7s over
`ContentView` on launch) wired in via `PowerstationApp.swift`. It has
nothing to do with the ITMS-90870 requirement — delete it and the
overlay wiring in `PowerstationApp.swift` if you'd rather go straight
to `ContentView`, which is equally valid.

## Liquid Glass (iOS 27)

This app doesn't set `UIDesignRequiresCompatibility` and doesn't use
custom `UINavigationBarAppearance`/`UITabBarAppearance` styling — it's
plain SwiftUI (`TabView`, `NavigationStack`, `Form`, `.tint`), which is
exactly the profile Apple says adopts the new design language
cleanly. The one spot worth an actual look on the iOS 27 simulator:
the `.regularMaterial` card backgrounds in `DashboardView` and
`LEDView` are custom translucent panels that now sit under a system
chrome that's also translucent/floating — nothing in the code fights
that, but a static review can't tell you whether it looks good
stacked. Worth eyeballing before you ship.

## Bug fixes from the last review pass

- **Charging tab**: opening it used to be able to silently re-send the
  device's own current charge speed back to it (because syncing
  `chargeSpeed` from status in `onAppear` re-triggered the `onChange`
  meant for user selections) — and would surface a spurious error if
  Sleep Mode happened to be on. Fixed with a sync-guard flag.
- **Stale error banners**: toggle/LED/charge/experimental commands
  never cleared `lastError` on success, so an old error could linger
  on screen indefinitely after later commands actually succeeded.
  Fixed — `lastError` now clears before each new command and on
  success.
- **Hex formatting**: three command builders formatted a plain `Int`
  with `%02X`/`%04X`/`%X` instead of a fixed-width type. Harmless in
  practice on Apple platforms for the small values involved, but
  pinned to `UInt8`/`UInt16` throughout to remove any ambiguity.

## Notes / caveats

- Same protocol caveats as the Python client: master/AC/DC/ambient
  light/beep route through the legacy bitmask command, not the
  documented single-purpose ones, because this device's firmware
  gates those behind a flag it doesn't set.
- Charge limit and standby (Keep Powered On / Screen Timeout) are
  **write-only** on this firmware — the short status push the app
  polls doesn't include them, so (like the original Python tool and
  the web dashboard) the app can't read back what's currently set.
  These reflect whatever was last set in the app itself, not
  necessarily the device's actual current setting, until you touch
  them again.
- Screen Timeout's labels (10s/30s/1m/5m/30m/Never) and Keep Powered
  On's behavior (`machine=6` when on, `1` when off, alongside whatever
  the current screen timeout is) match `powerstation_dashboard.html`
  exactly — there's no separate granular whole-unit standby duration
  exposed anywhere, on the web or here; Keep Powered On is a binary
  toggle in both.
- AC Output Frequency was removed — testing showed the command has no
  effect on this device.
- Settings' Power Controls section (AmpUp trigger, Power Off) isn't
  gated as "experimental" anymore, but worth knowing: "Turn AmpUp Mode
  On" sends the raw command directly and can reset Sleep Mode and
  Charge Speed as a side effect (it writes the whole shared byte, not
  just one bit). The AmpUp toggle on the Status tab goes through the
  proper read-modify-write path and doesn't have that side effect —
  prefer it for normal use. "Power Off Unit" doesn't have this problem
  — it's implemented as Master Power off through the same safe
  read-modify-write path as the Status tab's Master toggle. An earlier
  version sent the raw '12'/'00' command instead, which zeroed the
  *entire* switch register (AC, DC, Beep, and Ambient Light along with
  Master) rather than just the master bit — fixed.
