import SwiftUI

@main
struct LooprApp: App {
    @StateObject private var session = SessionStore()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(session)
                .preferredColorScheme(.dark)
        }
    }
}

/// Holds auth state and the shared API client (injected into view models).
@MainActor
final class SessionStore: ObservableObject {
    enum Phase { case launching, signedOut, onboarding, ready }
    @Published var phase: Phase = .launching
    let api = APIClient()

    init() {
        api.onUnauthorized = { [weak self] in Task { @MainActor in self?.signOut() } }
        Task {
            try? await Task.sleep(nanoseconds: 900_000_000) // splash
            await restore()
        }
    }

    func restore() async {
        guard Keychain.load(key: APIClient.tokenKey) != nil else { phase = .signedOut; return }
        struct Me: Decodable { let societyId: Int?; let flatNo: String }
        if let me: Me = try? await api.get("me") {
            phase = (me.societyId != nil && !me.flatNo.isEmpty) ? .ready : .onboarding
        } else {
            phase = .signedOut
        }
    }

    func signedIn(_ r: AuthResponse) {
        Keychain.save(r.token, key: APIClient.tokenKey)
        phase = r.onboarded ? .ready : .onboarding
    }

    func finishOnboarding() { phase = .ready }

    func signOut() {
        Keychain.delete(key: APIClient.tokenKey)
        phase = .signedOut
    }
}

struct RootView: View {
    @EnvironmentObject var session: SessionStore

    var body: some View {
        switch session.phase {
        case .launching: SplashView()
        case .signedOut: PhoneOTPView(vm: AuthViewModel(api: session.api))
        case .onboarding: OnboardingView(vm: OnboardingViewModel(api: session.api))
        case .ready: MainTabView()
        }
    }
}

struct MainTabView: View {
    @EnvironmentObject var session: SessionStore
    var body: some View {
        TabView {
            DashboardView(vm: DashboardViewModel(api: session.api)).tabItem { Label("Home", systemImage: "house") }
            VehiclesView(vm: VehiclesViewModel(api: session.api)).tabItem { Label("Vehicles", systemImage: "car") }
            ComingSoon(title: "Plans").tabItem { Label("Plans", systemImage: "checklist") }
            ComingSoon(title: "History").tabItem { Label("History", systemImage: "clock") }
            ComingSoon(title: "More").tabItem { Label("More", systemImage: "ellipsis") }
        }
        .tint(Theme.teal)
    }
}

/// Honest placeholders: these screens are not built yet (see docs/STATUS.md).
struct ComingSoon: View {
    let title: String
    var body: some View {
        ZStack { Theme.bg.ignoresSafeArea(); Text("\(title) - not implemented yet").foregroundColor(Theme.textSecondary) }
    }
}
