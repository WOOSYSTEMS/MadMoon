import SwiftUI

enum Theme {
    // MARK: - Colors
    static let roseGold = Color(red: 0.718, green: 0.431, blue: 0.475)
    static let softPink = Color(red: 1.0, green: 0.941, blue: 0.961)
    static let warmWhite = Color(red: 0.996, green: 0.98, blue: 0.98)
    static let deepRose = Color(red: 0.557, green: 0.286, blue: 0.341)
    static let lightRoseGold = Color(red: 0.855, green: 0.698, blue: 0.725)
    static let cardBackground = Color.white
    static let textPrimary = Color(red: 0.2, green: 0.15, blue: 0.16)
    static let textSecondary = Color(red: 0.5, green: 0.42, blue: 0.44)
    static let surfaceBackground = Color(red: 0.98, green: 0.96, blue: 0.965)

    // MARK: - Fonts
    static func serifHeading(_ size: CGFloat) -> Font {
        .system(size: size, weight: .semibold, design: .serif)
    }

    static func serifTitle(_ size: CGFloat) -> Font {
        .system(size: size, weight: .bold, design: .serif)
    }

    static func body(_ size: CGFloat = 15) -> Font {
        .system(size: size, weight: .regular, design: .default)
    }

    static func bodyMedium(_ size: CGFloat = 15) -> Font {
        .system(size: size, weight: .medium, design: .default)
    }

    static func bodySemibold(_ size: CGFloat = 15) -> Font {
        .system(size: size, weight: .semibold, design: .default)
    }

    // MARK: - Shadows
    static let cardShadow: some View = Color.black.opacity(0.06)
    static let cardShadowRadius: CGFloat = 8
    static let cardCornerRadius: CGFloat = 16
}
