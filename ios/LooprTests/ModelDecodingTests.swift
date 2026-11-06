import XCTest
@testable import Loopr

final class ModelDecodingTests: XCTestCase {
    func testDashboardDecodesNaiveISTDates() throws {
        let json = """
        {"greeting_name":"Priya","vehicles":[{"id":1,"name":"Honda City"}],
         "selected":{"vehicle_id":1,"vehicle_name":"Honda City","state":"scheduled","next_at":"2026-11-07T05:00:00"}}
        """.data(using: .utf8)!
        // Uses the same decoder configuration as APIClient.
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        d.dateDecodingStrategy = .custom { dec in
            let s = try dec.singleValueContainer().decode(String.self)
            let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX")
            f.timeZone = TimeZone(identifier: "Asia/Kolkata"); f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
            return f.date(from: s)!
        }
        let dash = try d.decode(Dashboard.self, from: json)
        XCTAssertEqual(dash.selected?.state, "scheduled")
        XCTAssertNotNil(dash.selected?.nextAt)
    }
}
