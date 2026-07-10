//
//  PowerstationApp.swift
//  Powerstation
//

import SwiftUI

@main
struct PowerstationApp: App {
    @StateObject private var viewModel = PowerstationViewModel()
    @State private var showSplash = true

    var body: some Scene {
        WindowGroup {
            ZStack {
                ContentView()
                    .environmentObject(viewModel)

                if showSplash {
                    SplashScreenView()
                        .transition(.opacity)
                        .task {
                            try? await Task.sleep(nanoseconds: 700_000_000)
                            withAnimation(.easeOut(duration: 0.25)) {
                                showSplash = false
                            }
                        }
                }
            }
        }
    }
}
