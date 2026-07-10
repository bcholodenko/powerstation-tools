//
//  ContentView.swift
//  Powerstation
//

import SwiftUI

struct ContentView: View {
    @EnvironmentObject var vm: PowerstationViewModel

    var body: some View {
        TabView {
            DashboardView()
                .tabItem { Label("Status", systemImage: "bolt.fill") }

            LEDView()
                .tabItem { Label("LED", systemImage: "lightbulb.fill") }

            ChargeView()
                .tabItem { Label("Charging", systemImage: "battery.100.bolt") }

            SettingsView()
                .tabItem { Label("Settings", systemImage: "gearshape.fill") }
        }
        .tint(PSTheme.accentSolid)
        .overlay(alignment: .top) {
            if vm.isApplyingSetting {
                applyingSettingToast
                    .padding(.top, 8)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(.spring(response: 0.35, dampingFraction: 0.8), value: vm.isApplyingSetting)
    }

    private var applyingSettingToast: some View {
        HStack(spacing: 8) {
            ProgressView()
                .controlSize(.small)
            Text("Applying Setting…")
                .font(.subheadline.weight(.medium))
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .psGlassCapsule()
    }
}

#Preview {
    ContentView().environmentObject(PowerstationViewModel())
}
