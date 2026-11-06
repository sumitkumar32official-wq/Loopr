import Foundation
import CoreLocation

// MARK: - Wire models
struct Society: Decodable, Identifiable, Hashable {
    let id: Int
    let name: String
    let sector: String
    let city: String
    let units: Int
    let live: Bool
    let hasBasement: Bool
    let towers: [String]
    let distanceKm: Double?
}

struct Quote: Decodable {
    let planKey: String
    let label: String
    let monthly: Int
    let perMonth: Int
    let chargeNow: Int
    let gst: Int
    let annualSavings: Int
}

struct PaymentOrder: Decodable { let orderId: String; let amount: Int; let gst: Int }
struct SubscriptionStub: Decodable { let id: Int; let status: String }
struct SubscriptionCreated: Decodable { let subscription: SubscriptionStub; let payment: PaymentOrder }
struct SubscriptionList: Decodable { let subscriptions: [SubscriptionStub] }
struct MeResponse: Decodable { let phone: String; let name: String }

struct ProfilePatch: Encodable { var name: String?; var societyId: Int?; var tower: String?; var flatNo: String? }
struct VehicleCreate: Encodable {
    var kind = "car"; var name: String; var nickname = ""; var seats: Int?; var registration: String?
    var parkingLevel: String; var parkingSlot: String; var landmark: String; var cleanWindow: String
}
struct VehicleEdit: Encodable {
    var name: String; var nickname: String; var seats: Int?; var registration: String?
    var parkingLevel: String; var parkingSlot: String; var landmark: String; var cleanWindow: String
}
struct QuoteBody: Encodable { let vehicleId: Int; let cycle: String; let bundle: Bool }
struct WaitlistBody: Encodable { let phone: String; var societyId: Int?; var societyName = "" }
struct Flag: Decodable { let waitlisted: Bool? }

// MARK: - Location (nearest-first societies)
final class LocationProvider: NSObject, CLLocationManagerDelegate {
    private let mgr = CLLocationManager()
    private var cont: CheckedContinuation<CLLocation?, Never>?

    func current() async -> CLLocation? {
        mgr.delegate = self
        switch mgr.authorizationStatus {
        case .denied, .restricted: return nil
        case .notDetermined: mgr.requestWhenInUseAuthorization()
        default: break
        }
        return await withCheckedContinuation { c in
            cont = c
            mgr.requestLocation()
        }
    }
    func locationManager(_ m: CLLocationManager, didUpdateLocations l: [CLLocation]) { cont?.resume(returning: l.first); cont = nil }
    func locationManager(_ m: CLLocationManager, didFailWithError e: Error) { cont?.resume(returning: nil); cont = nil }
}

// MARK: - View model
@MainActor
final class OnboardingViewModel: ObservableObject {
    enum Step: Int, CaseIterable { case society = 1, flat, vehicle, plan, window, summary }

    @Published var step: Step = .society
    @Published var isLoading = false
    @Published var error: String?
    @Published var finished = false

    // Society
    @Published var query = ""
    @Published var societies: LoadState<[Society]> = .idle
    @Published var society: Society?
    @Published var waitlistMessage: String?
    // Flat & parking
    @Published var tower = ""
    @Published var flatNo = ""
    @Published var parkingLevel = ""
    @Published var slot = ""
    @Published var landmark = ""
    // Vehicle
    @Published var vehicleName = ""
    @Published var seats = 5
    @Published var seatsTouched = false
    @Published var registration = ""
    @Published var nickname = ""
    @Published var hasBike = false
    // Plan / window
    @Published var annual = false
    @Published var addBundle = false
    @Published var quote: Quote?
    @Published var window = "early_morning"

    private let api: APIClientProtocol
    private let location = LocationProvider()
    private var coords: CLLocation?
    private var vehicleId: Int?
    private var phone = ""

    init(api: APIClientProtocol) { self.api = api }

    static let windows: [(key: String, title: String, time: String)] = [
        ("early_morning", "Early Morning", "5:00 - 8:00 AM"), ("morning", "Morning", "8:00 - 10:00 AM"),
        ("mid_morning", "Mid-Morning", "10:00 AM - 12:00 PM"), ("evening", "Evening", "4 - 7 PM"),
        ("night", "Night", "7 - 10 PM")]

    // Derived
    var floor: String? {
        let digits = flatNo.filter(\.isNumber)
        guard digits.count >= 3, let n = Int(digits.dropLast(2)) else { return nil }
        return "Floor \(n) - auto-derived"
    }
    var parkingOptions: [String] {
        (society?.hasBasement ?? true) ? ["B1", "B2", "B3", "Open", "Covered", "Podium"] : ["Open", "Covered", "Podium"]
    }
    var flatValid: Bool { !tower.isEmpty && !flatNo.trimmingCharacters(in: .whitespaces).isEmpty && !parkingLevel.isEmpty && !slot.trimmingCharacters(in: .whitespaces).isEmpty }
    var vehicleValid: Bool { vehicleName.trimmingCharacters(in: .whitespaces).count >= 2 }

    // MARK: Society
    func start() async {
        if let me: MeResponse = try? await api.get("me") { phone = me.phone }
        coords = await location.current()
        await searchSocieties()
    }

    func searchSocieties() async {
        societies = .loading
        var q: [String: String] = [:]
        let text = query.trimmingCharacters(in: .whitespaces)
        if !text.isEmpty { q["q"] = text }
        else if let c = coords { q["lat"] = String(c.coordinate.latitude); q["lng"] = String(c.coordinate.longitude) }
        do {
            let r: [Society] = try await api.get("societies", query: q)
            societies = r.isEmpty ? .empty : .loaded(r)
        } catch { societies = .failed(error.localizedDescription) }
    }

    func pick(_ s: Society) {
        guard s.live else { return }
        society = s
        tower = s.towers.first ?? ""
        if !s.hasBasement { parkingLevel = "Open" }
        step = .flat
    }

    func joinWaitlist(_ s: Society?) async {
        do {
            let _: Flag = try await api.post("societies/waitlist",
                body: WaitlistBody(phone: phone, societyId: s?.id, societyName: s == nil ? query : ""))
            waitlistMessage = "You're on the list. We'll notify you when we launch there."
        } catch { self.error = error.localizedDescription }
    }

    // MARK: Flat -> vehicle
    func saveFlat() async {
        guard let s = society else { return }
        await run {
            let _: MeResponse = try await self.api.patch("me", body: ProfilePatch(societyId: s.id, tower: self.tower, flatNo: self.flatNo))
            self.step = .vehicle
        }
    }

    func saveVehicle() async {
        await run {
            let reg = self.registration.trimmingCharacters(in: .whitespaces)
            let seatsToSend: Int? = self.seatsTouched ? self.seats : nil
            let v: Vehicle
            if let id = self.vehicleId {
                v = try await self.api.patch("vehicles/\(id)", body: VehicleEdit(
                    name: self.vehicleName, nickname: self.nickname, seats: self.seats,
                    registration: reg.isEmpty ? nil : reg, parkingLevel: self.parkingLevel,
                    parkingSlot: self.slot, landmark: self.landmark, cleanWindow: self.window))
            } else {
                v = try await self.api.post("vehicles", body: VehicleCreate(
                    name: self.vehicleName, nickname: self.nickname, seats: seatsToSend,
                    registration: reg.isEmpty ? nil : reg, parkingLevel: self.parkingLevel,
                    parkingSlot: self.slot, landmark: self.landmark, cleanWindow: self.window))
            }
            self.vehicleId = v.id
            self.seats = v.seats       // server auto-detects size from the model name
            try await self.refreshQuote()
            self.step = .plan
        }
    }

    // MARK: Plan
    func refreshQuote() async throws {
        guard let id = vehicleId else { return }
        quote = try await api.post("subscriptions/quote", body: QuoteBody(vehicleId: id, cycle: annual ? "annual" : "monthly", bundle: addBundle))
    }

    func planChanged() async { await run { try await self.refreshQuote() } }

    // MARK: Window -> summary
    func saveWindow() async {
        guard let id = vehicleId else { return }
        await run {
            let _: Vehicle = try await self.api.patch("vehicles/\(id)", body: VehicleEdit(
                name: self.vehicleName, nickname: self.nickname, seats: self.seats,
                registration: self.registration.isEmpty ? nil : self.registration, parkingLevel: self.parkingLevel,
                parkingSlot: self.slot, landmark: self.landmark, cleanWindow: self.window))
            self.step = .summary
        }
    }

    // MARK: Pay (Debug builds simulate the gateway; Release must integrate Razorpay checkout)
    func payAndActivate() async {
        guard let id = vehicleId else { return }
        await run {
            let created: SubscriptionCreated = try await self.api.post("subscriptions", body: QuoteBody(vehicleId: id, cycle: self.annual ? "annual" : "monthly", bundle: self.addBundle))
            #if DEBUG
            let _: Empty = try await self.api.post("dev/simulate-payment/\(created.payment.orderId)", body: Empty())
            #else
            throw APIError.server(status: 0, message: "Payment gateway is not configured in this build.")
            #endif
            // Never trust the client: confirm activation from the backend.
            let list: SubscriptionList = try await self.api.get("subscriptions")
            guard list.subscriptions.contains(where: { $0.id == created.subscription.id && $0.status == "active" }) else {
                throw APIError.server(status: 0, message: "Payment not confirmed yet. Please wait a moment and try again.")
            }
            self.finished = true
        }
    }

    func back() {
        if let prev = Step(rawValue: step.rawValue - 1) { step = prev; error = nil }
    }

    private func run(_ work: @escaping () async throws -> Void) async {
        isLoading = true; error = nil
        defer { isLoading = false }
        do { try await work() } catch { self.error = error.localizedDescription }
    }
}
