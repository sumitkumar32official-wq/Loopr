import SwiftUI

@MainActor
final class DashboardViewModel: ObservableObject {
    @Published var state: LoadState<Dashboard> = .idle
    @Published var selectedVehicleId: Int?
    private let api: APIClientProtocol
    private var poll: Task<Void, Never>?

    init(api: APIClientProtocol) { self.api = api }

    func load() async {
        if case .loaded = state {} else { state = .loading }
        do {
            var q: [String: String] = [:]
            if let id = selectedVehicleId { q["vehicle_id"] = String(id) }
            let d: Dashboard = try await api.get("dashboard", query: q)
            state = d.vehicles.isEmpty ? .empty : .loaded(d)
            selectedVehicleId = d.selected?.vehicleId
        } catch { state = .failed(error.localizedDescription) }
    }

    /// Status changes server-side (cleaner arrives, photo uploaded): refresh every 30s while visible.
    func startPolling() {
        poll?.cancel()
        poll = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 30_000_000_000)
                await self?.load()
            }
        }
    }
    func stopPolling() { poll?.cancel() }
}

struct DashboardView: View {
    @StateObject var vm: DashboardViewModel

    var body: some View {
        ZStack {
            Theme.bg.ignoresSafeArea()
            ScrollView {
                StateView(state: vm.state, emptyText: "Add your first vehicle to get started",
                          retry: { Task { await vm.load() } }) { d in
                    VStack(alignment: .leading, spacing: Theme.Space.l) {
                        Text("Hello, \(d.greetingName.isEmpty ? "there" : d.greetingName)").font(.loTitle).foregroundColor(.white)
                        if d.vehicles.count > 1 { vehicleTabs(d) }
                        if let s = d.selected { StatusCard(state: s) }
                        quickActions
                    }.padding(Theme.Space.l)
                }
            }
            .refreshable { await vm.load() }
        }
        .task { await vm.load(); vm.startPolling() }
        .onDisappear { vm.stopPolling() }
    }

    private func vehicleTabs(_ d: Dashboard) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack {
                ForEach(d.vehicles) { v in
                    Button(v.name) { vm.selectedVehicleId = v.id; Task { await vm.load() } }
                        .font(.loBody).padding(.horizontal, 14).padding(.vertical, 6)
                        .foregroundColor(v.id == vm.selectedVehicleId ? Theme.teal : .white)
                        .overlay(Capsule().stroke(v.id == vm.selectedVehicleId ? Theme.teal : Theme.border))
                }
            }
        }
    }

    private var quickActions: some View {
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: Theme.Space.m) {
            ForEach(["Book a Clean", "Service History", "My Plan", "Refer & Earn"], id: \.self) { t in
                // Navigation targets are wired once the destination screens exist.
                Card { Text(t).font(.loBody).foregroundColor(.white).frame(maxWidth: .infinity) }
            }
        }
    }
}

/// Renders all 8 dashboard states from the backend `state` field.
struct StatusCard: View {
    let state: DashboardState

    private var info: (title: String, subtitle: String, color: Color) {
        let time = (state.scheduledAt ?? state.nextAt)?.formatted(date: .abbreviated, time: .shortened) ?? ""
        switch state.state {
        case "scheduled": return ("Scheduled", time.isEmpty ? "Next clean being planned" : time, Theme.teal)
        case "cleaner_assigned": return ("Cleaner assigned", state.cleaner ?? "On the way", Theme.teal)
        case "cleaning_in_progress": return ("Cleaning in progress", state.cleaner ?? "", Theme.teal)
        case "cleaned": return ("Cleaned today", "Proof-of-clean photo is ready", Theme.success)
        case "missed": return ("Missed clean", state.makeupOffered == true ? "Free makeup clean available" : "", Theme.danger)
        case "paused": return ("Subscription paused", state.until.map { "Until \($0.formatted(date: .abbreviated, time: .omitted))" } ?? "", Theme.warning)
        case "payment_due": return ("Payment due", "Tap to fix your payment", Theme.danger)
        default: return ("No active subscription", "Subscribe to start daily cleans", Theme.textSecondary)
        }
    }

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: Theme.Space.s) {
                StatusPill(text: state.vehicleName, color: Theme.textSecondary)
                Text(info.title).font(.loHeadline).foregroundColor(info.color)
                if !info.subtitle.isEmpty { Text(info.subtitle).font(.loBody).foregroundColor(Theme.textSecondary) }
                if state.state == "cleaned", let url = state.lastPhotoUrl, let u = URL(string: url) {
                    AsyncImage(url: u) { $0.resizable().scaledToFill() } placeholder: { ProgressView() }
                        .frame(height: 140).clipShape(RoundedRectangle(cornerRadius: 10))
                }
            }
        }
        .accessibilityElement(children: .combine)
    }
}
