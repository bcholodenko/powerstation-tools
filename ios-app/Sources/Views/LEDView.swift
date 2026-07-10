//
//  LEDView.swift
//  Powerstation
//

import SwiftUI

/// Predefined color IDs 1-10, matching the vendor palette.
enum LEDPalette {
    /// Full known device color-ID → name/color mapping, covering every
    /// ID the protocol supports (1-10). Used to correctly interpret
    /// whatever color the device currently reports, even an ID that
    /// isn't offered below as a pickable swatch.
    static let allColors: [(id: Int, name: String, color: Color)] = [
        (1, "White", .white),
        (2, "Pink", Color(red: 1.0, green: 0.45, blue: 0.65)),
        (3, "Purple", Color(red: 0.55, green: 0.25, blue: 0.85)),
        (4, "Blue", .blue),
        (5, "Light Blue", Color(red: 0.45, green: 0.75, blue: 1.0)),
        (6, "Cyan", .cyan),
        (7, "Orange", Color(red: 1.0, green: 0.6, blue: 0.15)),
        (8, "Yellow-Green", Color(red: 0.7, green: 0.85, blue: 0.2)),
        (9, "Orange", Color(red: 1.0, green: 0.6, blue: 0.15)),
        (10, "Red", .red),
    ]

    /// Selectable swatches shown in the picker grid — excludes id 7,
    /// which is visually identical to id 9 ("Orange") and was
    /// confusing as a separate option. If the device happens to
    /// currently be set to id 7, `allColors` above still resolves it
    /// correctly to a matching name and color instead of falling back
    /// to two different, inconsistent defaults.
    static let colors: [(id: Int, name: String, color: Color)] = allColors.filter { $0.id != 7 }

    static func entry(for id: Int) -> (id: Int, name: String, color: Color)? {
        allColors.first(where: { $0.id == id })
    }
}

struct LEDView: View {
    @EnvironmentObject var vm: PowerstationViewModel
    @State private var selectedColorId: Int = 1
    @State private var brightness: Double = 50

    private let columns = [GridItem(.adaptive(minimum: 68), spacing: 14)]

    private var selectedColor: Color {
        LEDPalette.entry(for: selectedColorId)?.color ?? PSTheme.accentSolid
    }

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
                        previewCard

                        VStack(alignment: .leading, spacing: 14) {
                            Text("Color")
                                .font(.headline)
                            LazyVGrid(columns: columns, spacing: 14) {
                                ForEach(LEDPalette.colors, id: \.id) { entry in
                                    swatch(entry)
                                }
                            }
                        }
                        .padding(PSTheme.cardPadding)
                        .psCard()

                        VStack(alignment: .leading, spacing: 12) {
                            HStack {
                                Text("Brightness")
                                    .font(.headline)
                                Spacer()
                                Text("\(Int(brightness))%")
                                    .font(.subheadline.monospacedDigit())
                                    .foregroundStyle(.secondary)
                            }
                            Slider(value: $brightness, in: 0...100, step: 1)
                                .tint(selectedColor == .white ? PSTheme.accentSolid : selectedColor)
                        }
                        .padding(PSTheme.cardPadding)
                        .psCard()

                        Button {
                            vm.applyLED(colorId: selectedColorId, brightness: Int(brightness))
                        } label: {
                            Text("Apply")
                                .fontWeight(.semibold)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 4)
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(PSTheme.accentSolid)
                    }
                }
                .padding()
                .animation(.easeInOut(duration: 0.2), value: selectedColorId)
            }
            .navigationTitle("Ambient Light")
            .background(.background)
            .onAppear {
                if let status = vm.status {
                    selectedColorId = status.ambientColor.flatMap { $0 == 0 ? nil : $0 } ?? selectedColorId
                    brightness = Double(status.ambientLightness ?? Int(brightness))
                }
            }
        }
    }

    private var previewCard: some View {
        HStack(spacing: 16) {
            Circle()
                .fill(selectedColor)
                .overlay(Circle().strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
                .frame(width: 44, height: 44)
                .shadow(color: selectedColor.opacity(0.5 * (brightness / 100)), radius: 12)

            VStack(alignment: .leading, spacing: 2) {
                Text(LEDPalette.entry(for: selectedColorId)?.name ?? "White")
                    .font(.subheadline.weight(.semibold))
                Text("\(Int(brightness))% brightness")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(PSTheme.cardPadding)
        .psCard()
    }

    private func swatch(_ entry: (id: Int, name: String, color: Color)) -> some View {
        let selected = entry.id == selectedColorId
        return VStack(spacing: 6) {
            ZStack {
                Circle()
                    .fill(entry.color)
                    .frame(width: 44, height: 44)
                    .overlay(
                        Circle().strokeBorder(Color.primary.opacity(0.08), lineWidth: 1)
                    )
                    .shadow(color: selected ? entry.color.opacity(0.55) : .clear, radius: 8)

                if selected {
                    Image(systemName: "checkmark")
                        .font(.system(size: 15, weight: .bold))
                        .foregroundStyle(entry.color == .white ? .black : .white)
                }
            }
            .scaleEffect(selected ? 1.08 : 1.0)

            Text(entry.name)
                .font(.caption2)
                .foregroundStyle(selected ? .primary : .secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
        }
        .contentShape(Rectangle())
        .onTapGesture {
            withAnimation(.spring(response: 0.3, dampingFraction: 0.7)) {
                selectedColorId = entry.id
            }
        }
    }
}

#Preview {
    LEDView().environmentObject(PowerstationViewModel())
}
