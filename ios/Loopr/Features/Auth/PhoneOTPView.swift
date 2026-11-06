import SwiftUI

@MainActor
final class AuthViewModel: ObservableObject {
    enum Step { case phone, otp }
    @Published var step: Step = .phone
    @Published var digits = ""          // 10-digit national number
    @Published var code = ""
    @Published var isLoading = false
    @Published var error: String?
    @Published var resendIn = 0
    @Published var shake = 0

    private let api: APIClientProtocol
    private var timer: Timer?
    var onAuthenticated: ((AuthResponse) -> Void)?

    init(api: APIClientProtocol) { self.api = api }

    var phone: String { "+91" + digits }
    var phoneValid: Bool { digits.count == 10 && "6789".contains(digits.first!) }
    var codeValid: Bool { code.count == 6 }

    func sendOTP() async {
        guard phoneValid else { error = "Enter a valid 10-digit mobile number"; return }
        isLoading = true; error = nil
        defer { isLoading = false }
        do {
            let r: OTPRequestResponse = try await api.post("auth/otp/request", body: OTPRequestBody(phone: phone))
            step = .otp
            startResend(r.resendSeconds)
        } catch { self.error = error.localizedDescription }
    }

    func verify() async -> AuthResponse? {
        guard codeValid else { return nil }
        isLoading = true; error = nil
        defer { isLoading = false }
        do {
            return try await api.post("auth/otp/verify", body: OTPVerifyBody(phone: phone, code: code))
        } catch {
            self.error = error.localizedDescription
            self.code = ""
            self.shake += 1
            return nil
        }
    }

    private func startResend(_ s: Int) {
        resendIn = s
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] t in
            Task { @MainActor in
                guard let self else { return }
                self.resendIn -= 1
                if self.resendIn <= 0 { t.invalidate() }
            }
        }
    }
}

struct PhoneOTPView: View {
    @StateObject var vm: AuthViewModel
    @EnvironmentObject var session: SessionStore
    @FocusState private var focused: Bool

    var body: some View {
        ZStack {
            Theme.bg.ignoresSafeArea()
            VStack(alignment: .leading, spacing: Theme.Space.l) {
                LooprLogo(height: 34).padding(.bottom, Theme.Space.xl)
                switch vm.step {
                case .phone: phoneStep
                case .otp: otpStep
                }
                if let e = vm.error { Text(e).font(.loCaption).foregroundColor(Theme.danger) }
                #if DEBUG
                DevServerBox()
                #endif
                Spacer()
                Text("By continuing you agree to the Terms & Privacy Policy.")
                    .font(.loCaption).foregroundColor(Theme.textSecondary)
            }
            .padding(Theme.Space.l)
        }
        .onAppear { focused = true }
    }

    private var phoneStep: some View {
        VStack(alignment: .leading, spacing: Theme.Space.m) {
            Text("Enter your mobile number").font(.loTitle).foregroundColor(.white)
            Text("We'll text you a 6-digit code to verify it's you.").font(.loBody).foregroundColor(Theme.textSecondary)
            HStack {
                Text("+91").foregroundColor(Theme.textSecondary)
                TextField("98765 43210", text: $vm.digits)
                    .keyboardType(.numberPad).textContentType(.telephoneNumber).focused($focused)
                    .accessibilityIdentifier("phoneField")
                    .onChange(of: vm.digits) { _, v in vm.digits = String(v.filter(\.isNumber).prefix(10)) }
            }
            .padding().background(Theme.surface)
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(Theme.teal))
            PrimaryButton(title: "Send OTP", isLoading: vm.isLoading, isEnabled: vm.phoneValid) {
                Task { await vm.sendOTP() }
            }
        }
    }

    private var otpStep: some View {
        VStack(alignment: .leading, spacing: Theme.Space.m) {
            Text("Verify your number").font(.loTitle).foregroundColor(.white)
            Text("Code sent to +91 \(vm.digits)").font(.loBody).foregroundColor(Theme.textSecondary)
            TextField("6-digit code", text: $vm.code)
                .keyboardType(.numberPad).textContentType(.oneTimeCode).focused($focused)
                .accessibilityIdentifier("otpField")
                .padding().background(Theme.surface)
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(vm.error == nil ? Theme.teal : Theme.danger))
                .modifier(Shake(animatableData: CGFloat(vm.shake)))
                .animation(.default, value: vm.shake)
                .onChange(of: vm.code) { _, v in vm.code = String(v.filter(\.isNumber).prefix(6)) }
            PrimaryButton(title: "Verify", isLoading: vm.isLoading, isEnabled: vm.codeValid) {
                Task { if let r = await vm.verify() { session.signedIn(r) } }
            }
            Button(vm.resendIn > 0 ? "Resend in \(vm.resendIn)s" : "Resend code") { Task { await vm.sendOTP() } }
                .disabled(vm.resendIn > 0).font(.loBody).foregroundColor(Theme.teal)
            Button("Change number") { vm.step = .phone; vm.code = ""; vm.error = nil }
                .font(.loCaption).foregroundColor(Theme.textSecondary)
        }
    }
}

#if DEBUG
/// Debug builds only: point the app at any backend (e.g. a tunnel URL) without rebuilding.
struct DevServerBox: View {
    @State private var url = UserDefaults.standard.string(forKey: APIClient.devURLKey) ?? ""
    @State private var saved = false
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            FieldLabel(text: "Dev server URL (debug builds only)")
            HStack {
                TextField("https://your-tunnel.trycloudflare.com", text: $url)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                    .keyboardType(.URL).foregroundColor(.white)
                    .accessibilityIdentifier("devServerField")
                Button(saved ? "Saved" : "Save") {
                    UserDefaults.standard.set(url.trimmingCharacters(in: .whitespacesAndNewlines), forKey: APIClient.devURLKey)
                    saved = true
                }.foregroundColor(Theme.teal)
            }
            .padding(10).background(Theme.surface).clipShape(RoundedRectangle(cornerRadius: 10))
            .onChange(of: url) { _, _ in saved = false }
        }
    }
}
#endif

struct Shake: GeometryEffect {
    var animatableData: CGFloat
    func effectValue(size: CGSize) -> ProjectionTransform {
        ProjectionTransform(CGAffineTransform(translationX: 8 * sin(animatableData * .pi * 3), y: 0))
    }
}
