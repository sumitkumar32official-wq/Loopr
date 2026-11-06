import SwiftUI

@MainActor
final class VehiclesViewModel: ObservableObject {
    @Published var state: LoadState<[Vehicle]> = .idle
    @Published var pendingDelete: Vehicle?
    @Published var actionError: String?
    private let api: APIClientProtocol

    init(api: APIClientProtocol) { self.api = api }

    func load() async {
        if case .loaded = state {} else { state = .loading }
        do {
            let v: [Vehicle] = try await api.get("vehicles")
            state = v.isEmpty ? .empty : .loaded(v)
        } catch { state = .failed(error.localizedDescription) }
    }

    func confirmDelete() async {
        guard let v = pendingDelete else { return }
        pendingDelete = nil
        do { try await api.delete("vehicles/\(v.id)", query: ["confirm": "true"]); await load() }
        catch { actionError = error.localizedDescription }
    }
}

enum VehicleStatusStyle {
    static func style(_ s: String?) -> (String, Color) {
        switch s {
        case "active": return ("Active", Theme.success)
        case "paused": return ("Paused", Theme.warning)
        case "payment_due": return ("Payment due", Theme.danger)
        case "pending_activation": return ("Pending activation", Theme.warning)
        case "cancelling": return ("Ending soon", Theme.warning)
        default: return ("Expired", Theme.danger)
        }
    }
}

struct VehiclesView: View {
    @StateObject var vm: VehiclesViewModel

    var body: some View {
        NavigationStack {
            ZStack {
                Theme.bg.ignoresSafeArea()
                ScrollView {
                    StateView(state: vm.state, emptyText: "No vehicles yet", retry: { Task { await vm.load() } }) { vehicles in
                        VStack(spacing: Theme.Space.m) {
                            ForEach(vehicles) { v in VehicleRow(vehicle: v) { vm.pendingDelete = v } }
                        }.padding(Theme.Space.l)
                    }
                }
                .refreshable { await vm.load() }
            }
            .navigationTitle("My Vehicles")
            .task { await vm.load() }
            .confirmationDialog("Delete this vehicle?", isPresented: Binding(
                get: { vm.pendingDelete != nil }, set: { if !$0 { vm.pendingDelete = nil } }), titleVisibility: .visible) {
                Button("Delete", role: .destructive) { Task { await vm.confirmDelete() } }
            }
            .alert("Couldn't complete that", isPresented: Binding(
                get: { vm.actionError != nil }, set: { if !$0 { vm.actionError = nil } })) {
                Button("OK", role: .cancel) {}
            } message: { Text(vm.actionError ?? "") }
        }
    }
}

struct VehicleRow: View {
    let vehicle: Vehicle
    let onDelete: () -> Void

    var body: some View {
        let (label, color) = VehicleStatusStyle.style(vehicle.subscription?.status)
        Card {
            VStack(alignment: .leading, spacing: Theme.Space.s) {
                HStack {
                    Image(systemName: vehicle.kind == "bike" ? "bicycle" : "car.fill").foregroundColor(Theme.teal)
                    Text(vehicle.displayName).font(.loHeadline).foregroundColor(.white)
                    Spacer()
                    Menu {
                        Button("Delete", role: .destructive, action: onDelete)
                    } label: { Image(systemName: "ellipsis").foregroundColor(Theme.textSecondary) }
                }
                Text([vehicle.registration ?? "Registration pending", vehicle.kind == "car" ? "\(vehicle.seats) seater" : "Two-wheeler"]
                    .joined(separator: " · ")).font(.loCaption).foregroundColor(Theme.textSecondary)
                HStack {
                    StatusPill(text: label, color: color)
                    if vehicle.subscription?.bundle == true { StatusPill(text: "Bundle", color: .white) }
                    if let p = vehicle.subscription?.pendingPlanKey { StatusPill(text: "Pending change: \(p)", color: Theme.warning) }
                }
            }
        }
    }
}
