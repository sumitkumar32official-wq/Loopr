import Foundation

// Mirrors the FastAPI contract. Keys are snake_case on the wire (decoder converts).

struct OTPRequestBody: Encodable { let phone: String }
struct OTPRequestResponse: Decodable { let sent: Bool; let resendSeconds: Int }
struct OTPVerifyBody: Encodable { let phone: String; let code: String; var referralCode: String? = nil }
struct AuthResponse: Decodable { let token: String; let newUser: Bool; let onboarded: Bool }

struct VehicleSubscription: Decodable, Hashable {
    let id: Int
    let status: String
    let planKey: String
    let bundle: Bool
    let monthlyPrice: Int
    let pendingPlanKey: String?
}

struct Vehicle: Decodable, Identifiable, Hashable {
    let id: Int
    let kind: String
    let name: String
    let nickname: String
    let seats: Int
    let registration: String?
    let parkingLevel: String
    let parkingSlot: String
    let subscription: VehicleSubscription?

    var displayName: String { nickname.isEmpty ? name : nickname }
}

struct DashboardVehicleRef: Decodable, Identifiable, Hashable { let id: Int; let name: String }

/// One of: scheduled, cleaned, paused, payment_due, no_active_subscription, missed,
/// cleaner_assigned, cleaning_in_progress
struct DashboardState: Decodable {
    let vehicleId: Int
    let vehicleName: String
    let state: String
    let nextAt: Date?
    let scheduledAt: Date?
    let cleaner: String?
    let lastPhotoUrl: String?
    let makeupOffered: Bool?
    let until: Date?
}

struct Dashboard: Decodable {
    let greetingName: String
    let vehicles: [DashboardVehicleRef]
    let selected: DashboardState?
}
