import SwiftUI

enum Theme {
    static let bg = Color(red: 0.06, green: 0.08, blue: 0.16)        // deep navy
    static let surface = Color(red: 0.11, green: 0.12, blue: 0.15)   // graphite
    static let card = Color(red: 0.13, green: 0.15, blue: 0.18)
    static let border = Color.white.opacity(0.08)
    static let teal = Color(red: 0.24, green: 0.75, blue: 0.70)
    static let textPrimary = Color.white
    static let textSecondary = Color.white.opacity(0.62)
    static let success = Color(red: 0.25, green: 0.78, blue: 0.50)
    static let warning = Color(red: 0.96, green: 0.70, blue: 0.20)
    static let danger = Color(red: 0.93, green: 0.30, blue: 0.30)

    enum Space { static let xs: CGFloat = 4, s: CGFloat = 8, m: CGFloat = 12, l: CGFloat = 16, xl: CGFloat = 24 }
    static let radius: CGFloat = 14
}

extension Font {
    static let loTitle = Font.system(size: 24, weight: .bold)
    static let loHeadline = Font.system(size: 17, weight: .semibold)
    static let loBody = Font.system(size: 15)
    static let loCaption = Font.system(size: 12)
}
