import SwiftUI
import UIKit

// Theme: every colour in the iOS app. Change a value here and it changes everywhere.
// Same names and order as the web (style.css) and Android (NaraHemColors.kt) theme files.

let accent = Color(hex: 0xFFC35A)
let accentText = Color(hex: 0xFFD27A)
let onAccent = Color(hex: 0x2A1A05)

/// Text.
let cream = Color(hex: 0xF6EFE3)
let textLabel = Color(hex: 0xC4CEE8)

/// Text subdued.
let subdued = Color(hex: 0xAEBBDD)

/// Background.
let midnight = Color(hex: 0x06143A)
let glowTop = Color(hex: 0x143C95)
let glowMiddle = Color(hex: 0x0A2160)

/// The lower background, kept a step lighter than the bottom bar (`midnight`) all the way down.
let glowLow = Color(hex: 0x0B2160)
let glowBottom = Color(hex: 0x0A1C52)
let panel = Color(hex: 0x0C1D4D)
let panelRaised = Color(hex: 0x0F2459)
let panelSunken = Color(hex: 0x081639)
let chip = Color(hex: 0x1A3170)
let chipHover = Color(hex: 0x24407F)
let line = Color(hex: 0x1E3A7A)
let lineStrong = Color(hex: 0x2D4C8F)
let white = Color.white
let placeColor = Color(hex: 0xFFC35A)
let routeColor = Color(hex: 0xFFC35A)
let routeCasing = Color(hex: 0x081639)
let tripStart = Color(hex: 0x22C55E)
let tripEnd = Color(hex: 0xEF4444)
let ok = Color(hex: 0x247D41)
let accentContainer = Color(hex: 0x3D2C0E)
let warn = Color(hex: 0xFFA726)
let danger = Color(hex: 0xDB5359)
let dangerText = Color(hex: 0xFFB8BA)

/// iOS only: this iPhone's own position on the map.
let myLocation = Color(hex: 0x0A84FF)

/// UIKit copies for map and image drawing.
let accentUIColor = UIColor(accent)
let placeUIColor = UIColor(placeColor)
let routeUIColor = UIColor(routeColor)

extension Color {
    /// A colour from a 0xRRGGBB value.
    init(hex: UInt32) {
        self.init(
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255)
    }
}
