//
//  SettingsView.swift
//  Powerstation
//

import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var vm: PowerstationViewModel
    @State private var keepPoweredOn = false
    @State private var screenTimeout: Int = 3

    @State private var showPowerOffConfirm = false

    // Matches the web dashboard's screen-timeout labels exactly.
    private let screenTimeoutLevels = [1, 2, 3, 4, 5, 6]
    private let screenTimeoutLabels: [Int: String] = [
        1: "10s", 2: "30s", 3: "1m", 4: "5m", 5: "30m", 6: "Never",
    ]

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Host or IP", text: $vm.host)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    TextField("Port", text: $vm.port)
                        .keyboardType(.numberPad)
                } header: {
                    Label("Connection", systemImage: "network")
                } footer: {
                    Text("Default is 192.168.4.1:5000 (the device's own hotspot). Once it's joined your home Wi-Fi, use its LAN IP instead.")
                }

                if vm.isConnected {
                    Section {
                        Toggle(isOn: $keepPoweredOn) {
                            HStack(spacing: 12) {
                                IconBadge(assetName: "icon-keepon", color: PSTheme.accentSolid)
                                Text("Keep Powered On")
                            }
                        }
                        .tint(PSTheme.accentSolid)
                        .onChange(of: keepPoweredOn) { _, newValue in
                            vm.setKeepPoweredOn(newValue, screenLevel: screenTimeout)
                        }

                        VStack(alignment: .leading, spacing: 10) {
                            Text("Screen Timeout")
                            ChipRow(items: screenTimeoutLevels, selection: $screenTimeout,
                                    label: { screenTimeoutLabels[$0] ?? "" }) { newValue in
                                vm.setScreenTimeout(newValue, keepPoweredOn: keepPoweredOn)
                            }
                        }
                        .padding(.vertical, 4)
                    } header: {
                        Label("Standby", systemImage: "moon.zzz.fill")
                    } footer: {
                        Text("These share a single byte on the device and can't be read back, so this reflects what you last set here rather than a live readout.")
                    }

                    Section {
                        Button("Turn AmpUp Mode On") { vm.triggerAmpUpOn() }
                        Button("Power Off Unit", role: .destructive) { showPowerOffConfirm = true }
                    } header: {
                        Label("Power Controls", systemImage: "power")
                    } footer: {
                        Text("Turn AmpUp Mode On here sets it directly and can reset Sleep Mode and Charge Speed as a side effect — the AmpUp toggle on the Status tab is the safer everyday control. Power Off requires the physical button to turn the unit back on.")
                    }
                }
            }
            .navigationTitle("Settings")
            .alert("Power off the unit?", isPresented: $showPowerOffConfirm) {
                Button("Cancel", role: .cancel) {}
                Button("Power Off", role: .destructive) { vm.triggerPowerOff() }
            } message: {
                Text("Only the physical power button is confirmed to bring it back on.")
            }
        }
    }
}

#Preview {
    SettingsView().environmentObject(PowerstationViewModel())
}
