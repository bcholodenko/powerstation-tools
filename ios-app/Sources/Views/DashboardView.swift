//
//  DashboardView.swift
//  Powerstation
//

import SwiftUI

struct DashboardView: View {
    @EnvironmentObject var vm: PowerstationViewModel

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: PSTheme.sectionSpacing) {
                    connectionCard

                    if vm.isConnected {
                        if let status = vm.status {
                            batteryCard(status)
                            powerFlowCard(status)
                            switchesCard(status)
                        } else {
                            VStack(spacing: 10) {
                                ProgressView()
                                Text("Waiting for status…")
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.top, 48)
                        }
                    }
                }
                .padding()
                .animation(.easeInOut(duration: 0.25), value: vm.isConnected)
                .animation(.easeInOut(duration: 0.25), value: vm.status)
            }
            .navigationTitle("Power Station")
            .background(.background)
        }
    }

    // MARK: - Connection

    private var connectionCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                Circle()
                    .fill(vm.isConnected ? Color.green : Color.secondary.opacity(0.35))
                    .frame(width: 9, height: 9)
                    .shadow(color: vm.isConnected ? .green.opacity(0.6) : .clear, radius: 4)

                Text(vm.isConnected ? "Connected" : (vm.isConnecting ? "Connecting…" : "Not connected"))
                    .font(.headline)

                Spacer()

                Text("\(vm.host):\(vm.port)")
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }

            if let error = vm.lastError {
                HStack(alignment: .top, spacing: 6) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(.caption)
                    Text(error)
                        .font(.footnote)
                }
                .foregroundStyle(.red)
            }

            Group {
                if !vm.isConnected {
                    Button {
                        vm.connect()
                    } label: {
                        HStack {
                            Spacer()
                            if vm.isConnecting {
                                ProgressView().tint(.white)
                            } else {
                                Text("Connect").fontWeight(.semibold)
                            }
                            Spacer()
                        }
                        .padding(.vertical, 4)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(PSTheme.accentSolid)
                    .disabled(vm.isConnecting)
                } else {
                    Button(role: .destructive) {
                        vm.disconnect()
                    } label: {
                        Text("Disconnect")
                            .fontWeight(.semibold)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 4)
                    }
                    .buttonStyle(.bordered)
                }
            }
        }
        .padding(PSTheme.cardPadding)
        .psCard()
    }

    // MARK: - Battery

    private func batteryCard(_ status: PowerstationStatus) -> some View {
        let isCharging = (status.acInputWatts ?? 0) > 0 || (status.dcInputWatts ?? 0) > 0
        let color = batteryColor(status.batteryPercent)

        return VStack(spacing: 8) {
            ZStack {
                Circle()
                    .stroke(Color.secondary.opacity(0.12), lineWidth: 14)
                Circle()
                    .trim(from: 0, to: CGFloat(status.batteryPercent ?? 0) / 100)
                    .stroke(color, style: StrokeStyle(lineWidth: 14, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                    .shadow(color: color.opacity(0.45), radius: 6)

                VStack(spacing: 2) {
                    HStack(spacing: 4) {
                        Text("\(status.batteryPercent ?? 0)")
                            .font(.system(size: 36, weight: .bold, design: .rounded))
                        Text("%")
                            .font(.system(size: 18, weight: .semibold, design: .rounded))
                            .foregroundStyle(.secondary)
                            .offset(y: 3)
                    }
                    if isCharging {
                        Label("Charging", systemImage: "bolt.fill")
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(PSTheme.accentSolid)
                    } else if let temp = status.temperatureC {
                        Text(String(format: "%.1f°C", temp))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .frame(width: 148, height: 148)
            .padding(.vertical, 8)
        }
        .frame(maxWidth: .infinity)
        .padding(PSTheme.cardPadding)
        .psCard()
    }

    private func batteryColor(_ pct: Int?) -> Color {
        guard let pct else { return .gray }
        if pct <= 20 { return .red }
        if pct <= 50 { return .yellow }
        return .green
    }

    // MARK: - Power flow

    private func powerFlowCard(_ status: PowerstationStatus) -> some View {
        VStack(spacing: 0) {
            powerRow(icon: "arrow.down.circle.fill", label: "AC Input", watts: status.acInputWatts)
            Divider().padding(.leading, 54)
            powerRow(icon: "sun.max.fill", label: "DC Input", watts: status.dcInputWatts)
            Divider().padding(.leading, 54)
            powerRow(icon: "arrow.up.circle.fill", label: "AC Output", watts: status.acOutputWatts)
            Divider().padding(.leading, 54)
            powerRow(icon: "cable.connector", label: "DC Output", watts: status.dcOutputWatts)
        }
        .padding(.vertical, 6)
        .psCard()
    }

    private func powerRow(icon: String, label: String, watts: Int?) -> some View {
        HStack(spacing: 12) {
            IconBadge(systemName: icon, color: PSTheme.accentSolid)
            Text(label)
            Spacer()
            Text(watts != nil ? "\(watts!) W" : "—")
                .font(.callout.monospacedDigit())
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, PSTheme.cardPadding)
        .padding(.vertical, 12)
    }

    // MARK: - Switches

    private func switchesCard(_ status: PowerstationStatus) -> some View {
        VStack(spacing: 0) {
            toggleRow("Master Power", asset: "icon-master", color: .red, isOn: status.switches?["master"] ?? false) { vm.setMaster($0) }
            Divider().padding(.leading, 54)
            toggleRow("AC Output", asset: "icon-ac", color: PSTheme.accentSolid, isOn: status.switches?["ac"] ?? false) { vm.setAC($0) }
            Divider().padding(.leading, 54)
            toggleRow("DC Output", asset: "icon-dc", color: PSTheme.accentSolid, isOn: status.switches?["dc"] ?? false) { vm.setDC($0) }
            Divider().padding(.leading, 54)
            toggleRow("Ambient Light", asset: "icon-ambient", color: PSTheme.accentSolid, isOn: status.switches?["ambient_light"] ?? false) { vm.setAmbientLight($0) }
            Divider().padding(.leading, 54)
            toggleRow("Beep", asset: "icon-beep", color: PSTheme.accentSolid, isOn: status.switches?["buzzer"] ?? false) { vm.setBuzzer($0) }
            Divider().padding(.leading, 54)
            toggleRow("Sleep Mode", asset: "icon-sleep", color: PSTheme.accentSolid, isOn: status.sleepMode ?? false) { vm.setSleepMode($0) }
            Divider().padding(.leading, 54)
            toggleRow("AmpUp Mode", asset: "icon-ampup", color: PSTheme.accentSolid, isOn: status.ampUp ?? false) { vm.setAmpUp($0) }
        }
        .padding(.vertical, 6)
        .psCard()
    }

    private func toggleRow(_ title: String, asset: String, color: Color, isOn: Bool, action: @escaping (Bool) -> Void) -> some View {
        Toggle(isOn: Binding(get: { isOn }, set: { action($0) })) {
            HStack(spacing: 12) {
                IconBadge(assetName: asset, color: color)
                Text(title)
            }
        }
        .tint(PSTheme.accentSolid)
        .padding(.horizontal, PSTheme.cardPadding)
        .padding(.vertical, 10)
    }
}

#Preview {
    DashboardView().environmentObject(PowerstationViewModel())
}
