//
//  SplashScreenView.swift
//  Powerstation
//
//  Optional, purely cosmetic in-app splash overlay shown for a moment
//  after the app's actual (required) launch screen hands off to
//  SwiftUI. This is NOT what satisfies Apple's ITMS-90870 launch-screen
//  requirement — that's the native UILaunchScreen entry in Info.plist,
//  which renders instantly before any of this code runs. Delete
//  `SplashScreenView` and the `.overlay` wiring in PowerstationApp.swift
//  if you'd rather go straight to ContentView, which is also perfectly
//  fine and what Apple's HIG generally recommends.
//

import SwiftUI

struct SplashScreenView: View {
    var body: some View {
        ZStack {
            Rectangle()
                .fill(.background)
                .ignoresSafeArea()
            VStack(spacing: 18) {
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .fill(PSTheme.accent)
                    .frame(width: 88, height: 88)
                    .overlay(
                        Image(systemName: "bolt.fill")
                            .font(.system(size: 40, weight: .semibold))
                            .foregroundStyle(.white)
                    )
                    .shadow(color: PSTheme.accentSolid.opacity(0.4), radius: 20, x: 0, y: 8)
                Text("Powerstation")
                    .font(.title2.weight(.semibold))
            }
        }
    }
}

#Preview {
    SplashScreenView()
}
