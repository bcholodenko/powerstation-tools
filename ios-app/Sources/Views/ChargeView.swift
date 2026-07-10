//
//  ChargeView.swift
//  Powerstation
//

import SwiftUI

struct ChargeView: View {
    @EnvironmentObject var vm: PowerstationViewModel
    @State private var chargeLimit: Int = 100
    @State private var chargeSpeed: Int = 1800
    private let limits = [70, 80, 90, 100]
    private let speeds = [300, 500, 800, 1200, 1800]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: PSTheme.sectionSpacing) {
                    if !vm.isConnected {
                        VStack(spacing: 8) {
                            Image(systemName: "wifi.slash")
                                .font(.title2)
                                .foregroundStyle(.secondary)
                            Text("Connect to the power station on the Status tab first.")
                                .foregroundStyle(.secondary)
                                .multilineTextAlignment(.center)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.top, 60)
                    } else {
                        if let status = vm.status {
                            readingsCard(status)
                        }

                        cardSection(title: "Charge Limit", icon: "battery.75", color: .green) {
                            ChipRow(items: limits, selection: $chargeLimit, label: { "\($0)%" }) { newValue in
                                vm.setChargeLimit(newValue)
                            }
                        }

                        cardSection(title: "Max AC Charge Speed", icon: "bolt.fill", color: .orange,
                                    footer: "Blocked while Sleep Mode is on — turn that off first if this doesn't take effect.") {
                            ChipRow(items: speeds, selection: $chargeSpeed, label: { "\($0)W" }) { newValue in
                                vm.setChargeSpeed(newValue)
                            }
                        }
                    }
                }
                .padding()
            }
            .navigationTitle("Charging")
            .background(.background)
            .onAppear {
                if let status = vm.status, let watts = status.chargeSpeedWatts {
                    chargeSpeed = watts
                }
            }
            .onChange(of: vm.status) { _, newStatus in
                // Reconcile the displayed selection with what the device
                // actually reports, not just what was last tapped — if a
                // change was rejected (e.g. blocked by Sleep Mode), this
                // corrects the chip back within one status-push interval
                // instead of leaving it showing a value that never took.
                if let watts = newStatus?.chargeSpeedWatts {
                    chargeSpeed = watts
                }
            }
        }
    }

    // MARK: - Building blocks

    private func readingsCard(_ status: PowerstationStatus) -> some View {
        VStack(spacing: 0) {
            readingRow(icon: "battery.100", label: "Battery", value: "\(status.batteryPercent ?? 0)%", color: .green)
            if let watts = status.chargeSpeedWatts {
                Divider().padding(.leading, 54)
                readingRow(icon: "bolt.fill", label: "Reported Charge Speed", value: "\(watts) W", color: .orange)
            }
            if let mins = status.remainingInputMinutes {
                Divider().padding(.leading, 54)
                readingRow(icon: "hourglass", label: "Time to Full", value: "\(mins) min", color: .blue)
            }
            if let mins = status.remainingOutputMinutes {
                Divider().padding(.leading, 54)
                readingRow(icon: "hourglass.bottomhalf.fill", label: "Time Remaining", value: "\(mins) min", color: .purple)
            }
        }
        .padding(.vertical, 6)
        .psCard()
    }

    private func readingRow(icon: String, label: String, value: String, color: Color) -> some View {
        HStack(spacing: 12) {
            IconBadge(systemName: icon, color: color)
            Text(label)
            Spacer()
            Text(value)
                .font(.callout.monospacedDigit())
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, PSTheme.cardPadding)
        .padding(.vertical, 12)
    }

    private func cardSection<Content: View>(
        title: String, icon: String, color: Color, footer: String? = nil,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                IconBadge(systemName: icon, color: color)
                Text(title)
                    .font(.headline)
            }
            content()
            if let footer {
                Text(footer)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(PSTheme.cardPadding)
        .psCard()
    }
}

#Preview {
    ChargeView().environmentObject(PowerstationViewModel())
}
