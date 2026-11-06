import Foundation
import Security

// MARK: - Keychain
enum Keychain {
    static func save(_ value: String, key: String) {
        let data = Data(value.utf8)
        let base: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrAccount as String: key]
        SecItemDelete(base as CFDictionary)
        var add = base
        add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(add as CFDictionary, nil)
    }

    static func load(key: String) -> String? {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrAccount as String: key,
                                kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data else { return nil }
        return String(data: d, encoding: .utf8)
    }

    static func delete(key: String) {
        SecItemDelete([kSecClass as String: kSecClassGenericPassword, kSecAttrAccount as String: key] as CFDictionary)
    }
}

// MARK: - Errors
enum APIError: LocalizedError {
    case server(status: Int, message: String)
    case unauthorized
    case offline
    case decoding

    var errorDescription: String? {
        switch self {
        case .server(_, let m): return m
        case .unauthorized: return "Your session expired. Please sign in again."
        case .offline: return "You appear to be offline. Check your connection and try again."
        case .decoding: return "Unexpected response from the server."
        }
    }
}

// MARK: - Client
protocol APIClientProtocol {
    func get<T: Decodable>(_ path: String, query: [String: String]) async throws -> T
    func post<T: Decodable, B: Encodable>(_ path: String, body: B) async throws -> T
    func patch<T: Decodable, B: Encodable>(_ path: String, body: B) async throws -> T
    func delete(_ path: String, query: [String: String]) async throws
}

extension APIClientProtocol {
    func delete(_ path: String) async throws { try await delete(path, query: [:]) }
    func get<T: Decodable>(_ path: String) async throws -> T { try await get(path, query: [:]) }
}

struct Empty: Codable {}

final class APIClient: APIClientProtocol {
    static let tokenKey = "loopr.token"
    private let base: URL
    private let session: URLSession
    var onUnauthorized: (() -> Void)?

    init(session: URLSession = .shared) {
        let s = Bundle.main.object(forInfoDictionaryKey: "LOOPR_API_BASE_URL") as? String ?? "http://127.0.0.1:8000"
        self.base = URL(string: s)!
        self.session = session
    }

    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        // Server sends IST-naive timestamps such as 2026-11-07T05:00:00 or with microseconds.
        d.dateDecodingStrategy = .custom { dec in
            let s = try dec.singleValueContainer().decode(String.self)
            for fmt in ["yyyy-MM-dd'T'HH:mm:ss.SSSSSS", "yyyy-MM-dd'T'HH:mm:ss"] {
                let f = DateFormatter()
                f.locale = Locale(identifier: "en_US_POSIX")
                f.timeZone = TimeZone(identifier: "Asia/Kolkata")
                f.dateFormat = fmt
                if let date = f.date(from: s) { return date }
            }
            throw DecodingError.dataCorrupted(.init(codingPath: dec.codingPath, debugDescription: "Bad date \(s)"))
        }
        return d
    }()

    private static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        e.dateEncodingStrategy = .custom { date, enc in
            let f = DateFormatter()
            f.locale = Locale(identifier: "en_US_POSIX")
            f.timeZone = TimeZone(identifier: "Asia/Kolkata")
            f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
            var c = enc.singleValueContainer()
            try c.encode(f.string(from: date))
        }
        return e
    }()

    private func request(_ method: String, _ path: String, query: [String: String] = [:], body: Data? = nil) async throws -> Data {
        var comps = URLComponents(url: base.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { comps.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) } }
        var req = URLRequest(url: comps.url!)
        req.httpMethod = method
        req.timeoutInterval = 20
        if let body { req.httpBody = body; req.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        if let t = Keychain.load(key: Self.tokenKey) { req.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization") }
        do {
            let (data, resp) = try await session.data(for: req)
            let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
            if status == 401 { onUnauthorized?(); throw APIError.unauthorized }
            guard (200..<300).contains(status) else {
                let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"]
                let msg = (detail as? String) ?? "Something went wrong (\(status))."
                throw APIError.server(status: status, message: msg)
            }
            return data
        } catch let e as URLError where [.notConnectedToInternet, .networkConnectionLost, .timedOut].contains(e.code) {
            throw APIError.offline
        }
    }

    private func decode<T: Decodable>(_ data: Data) throws -> T {
        if T.self == Empty.self { return Empty() as! T }
        do { return try Self.decoder.decode(T.self, from: data) } catch { throw APIError.decoding }
    }

    func get<T: Decodable>(_ path: String, query: [String: String]) async throws -> T {
        try decode(try await request("GET", path, query: query))
    }
    func post<T: Decodable, B: Encodable>(_ path: String, body: B) async throws -> T {
        try decode(try await request("POST", path, body: try Self.encoder.encode(body)))
    }
    func patch<T: Decodable, B: Encodable>(_ path: String, body: B) async throws -> T {
        try decode(try await request("PATCH", path, body: try Self.encoder.encode(body)))
    }
    func delete(_ path: String, query: [String: String]) async throws { _ = try await request("DELETE", path, query: query) }
}
