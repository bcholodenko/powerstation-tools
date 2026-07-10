//
//  Theme.swift
//  Powerstation
//
//  Small shared design system so every screen draws from the same
//  palette, spacing, and card treatment instead of ad-hoc styling.
//

import SwiftUI

enum PSTheme {
    static let cornerRadius: CGFloat = 20
    static let cardPadding: CGFloat = 16
    static let sectionSpacing: CGFloat = 14

    /// Warm amber → ember gradient used for the brand accent (battery
    /// ring, primary buttons, icon badges) — evokes "power/energy"
    /// without just being flat system orange.
    static let accent = LinearGradient(
        colors: [Color(red: 1.00, green: 0.70, blue: 0.20),
                 Color(red: 0.96, green: 0.42, blue: 0.16)],
        startPoint: .topLeading, endPoint: .bottomTrailing
    )

    /// A representative solid color for places that need one value
    /// rather than a gradient (tab tint, plain icons).
    static let accentSolid = Color(red: 0.98, green: 0.55, blue: 0.18)
}

/// Consistent elevated-card look: material fill, faint border, soft
/// shadow. Used for every content block across Dashboard/LED/Charging.
private struct CardBackground: ViewModifier {
    func body(content: Content) -> some View {
        content
            .background(
                RoundedRectangle(cornerRadius: PSTheme.cornerRadius, style: .continuous)
                    .fill(.regularMaterial)
            )
            .overlay(
                RoundedRectangle(cornerRadius: PSTheme.cornerRadius, style: .continuous)
                    .strokeBorder(Color.primary.opacity(0.06), lineWidth: 1)
            )
            .shadow(color: .black.opacity(0.10), radius: 14, x: 0, y: 6)
    }
}

extension View {
    func psCard() -> some View {
        modifier(CardBackground())
    }
}

/// A colored rounded-square badge behind an icon, matching the
/// familiar Settings-app icon language — reads as more "designed" than
/// a bare tinted symbol floating in a row. Supports either an SF
/// Symbol or a custom asset (e.g. the icons extracted from
/// powerstation_dashboard.html, which match the actual device).
struct IconBadge: View {
    private enum Source {
        case system(String)
        case asset(String)
    }
    private let source: Source
    let color: Color

    init(systemName: String, color: Color) {
        self.source = .system(systemName)
        self.color = color
    }

    /// `assetName` should be a template-rendering image in the asset
    /// catalog (the icon-* sets already have template rendering set).
    init(assetName: String, color: Color) {
        self.source = .asset(assetName)
        self.color = color
    }

    var body: some View {
        RoundedRectangle(cornerRadius: 7, style: .continuous)
            .fill(color.gradient)
            .frame(width: 28, height: 28)
            .overlay(
                Group {
                    switch source {
                    case .system(let name):
                        Image(systemName: name)
                            .font(.system(size: 14, weight: .semibold))
                    case .asset(let name):
                        Image(name)
                            .renderingMode(.template)
                            .resizable()
                            .scaledToFit()
                            .frame(width: 15, height: 15)
                    }
                }
                .foregroundStyle(.white)
            )
    }
}

extension View {
    /// Liquid Glass on iOS 26+ (where it's available), falling back to
    /// a translucent material capsule with a hairline border on earlier
    /// versions — same shape and footprint either way.
    @ViewBuilder
    func psGlassCapsule() -> some View {
        if #available(iOS 26.0, *) {
            self.glassEffect(.regular, in: .capsule)
        } else {
            self
                .background(.ultraThinMaterial, in: Capsule())
                .overlay(Capsule().strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
                .shadow(color: .black.opacity(0.15), radius: 10, x: 0, y: 4)
        }
    }
}

/// A horizontally-scrolling row of capsule chips for picking one value
/// from a small fixed set — used anywhere a segmented control would
/// otherwise be too cramped for the label lengths involved (charge
/// limit/speed, screen timeout). Selecting a chip updates the binding
/// immediately and calls `onSelect` once, so callers can distinguish a
/// user tap from any other programmatic assignment to the same binding.
struct ChipRow<Item: Hashable>: View {
    let items: [Item]
    @Binding var selection: Item
    let label: (Item) -> String
    let onSelect: (Item) -> Void

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(items, id: \.self) { item in
                    let selected = item == selection
                    Text(label(item))
                        .font(.subheadline.weight(selected ? .semibold : .regular))
                        .foregroundStyle(selected ? .white : .primary)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 9)
                        .background(
                            Group {
                                if selected {
                                    Capsule().fill(PSTheme.accent)
                                } else {
                                    Capsule().fill(Color.primary.opacity(0.06))
                                }
                            }
                        )
                        .contentShape(Capsule())
                        .onTapGesture {
                            withAnimation(.spring(response: 0.3, dampingFraction: 0.75)) {
                                selection = item
                            }
                            onSelect(item)
                        }
                }
            }
        }
    }
}
