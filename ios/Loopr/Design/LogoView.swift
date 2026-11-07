import SwiftUI

/// A running wheel: tyre ring, rim, hub and five spokes. `rotation` animates it.
struct WheelShape: View {
    var color: Color = Theme.teal
    var rotation: Angle = .zero

    var body: some View {
        GeometryReader { geo in
            let d = min(geo.size.width, geo.size.height)
            ZStack {
                Circle().stroke(color, lineWidth: d * 0.14)
                Circle().stroke(color.opacity(0.55), lineWidth: d * 0.03).padding(d * 0.2)
                ForEach(0..<5, id: \.self) { i in
                    Capsule().fill(color)
                        .frame(width: d * 0.07, height: d * 0.32)
                        .offset(y: -d * 0.16)
                        .rotationEffect(.degrees(Double(i) * 72))
                }
                Circle().fill(color).frame(width: d * 0.16, height: d * 0.16)
            }
            .rotationEffect(rotation)
            .frame(width: d, height: d)
            .position(x: geo.size.width / 2, y: geo.size.height / 2)
        }
        .aspectRatio(1, contentMode: .fit)
    }
}

/// L + (wheel)(wheel) + PR. The two O's are interlocked wheels (overlapping 18%) - not text.
struct LooprLogo: View {
    var height: CGFloat = 36
    var textColor: Color = .white
    var wheelColor: Color = Theme.teal
    var animated = false
    @State private var spin = false

    var body: some View {
        HStack(spacing: height * 0.04) {
            Text("L").font(.system(size: height, weight: .heavy, design: .rounded)).foregroundColor(textColor)
            HStack(spacing: -height * 0.18) {
                WheelShape(color: wheelColor, rotation: .degrees(spin ? 360 : 0))
                    .frame(width: height * 0.82, height: height * 0.82)
                WheelShape(color: wheelColor.opacity(0.85), rotation: .degrees(spin ? -360 : 0))
                    .frame(width: height * 0.82, height: height * 0.82)
            }
            HStack(alignment: .lastTextBaseline, spacing: height * 0.02) {
                Text("P").font(.system(size: height, weight: .heavy, design: .rounded))
                Text("R").font(.system(size: height * 0.68, weight: .heavy, design: .rounded))   // small "R"
            }
            .foregroundColor(textColor)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Loopr")
        .onAppear {
            guard animated, !ProcessInfo.processInfo.arguments.contains("-uitest") else { return }   // endless animation stalls XCUITest idle checks
            withAnimation(.linear(duration: 6).repeatForever(autoreverses: false)) { spin = true }
        }
    }
}

/// Launch/splash screen.
struct SplashView: View {
    var body: some View {
        ZStack {
            Theme.bg.ignoresSafeArea()
            VStack(spacing: 12) {
                LooprLogo(height: 52, animated: true)
                Text("Effortless car care").font(.loCaption).foregroundColor(Theme.textSecondary)
            }
        }
    }
}

/// App-icon source: render via ImageRenderer in a build script, or export as SVG asset.
struct AppIconView: View {
    var body: some View {
        ZStack {
            Theme.bg
            HStack(spacing: -34) {
                WheelShape().frame(width: 360, height: 360)
                WheelShape(color: .white).frame(width: 360, height: 360)
            }
        }
        .frame(width: 1024, height: 1024)
    }
}

#Preview { LooprLogo(height: 48).padding().background(Theme.bg) }
