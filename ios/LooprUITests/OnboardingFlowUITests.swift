import XCTest

/// Drives the real app against the real backend (started by CI on 127.0.0.1:8000) and saves a screenshot per step.
/// Screenshots go to /tmp/loopr-shots (uploaded by CI) and are also attached to the .xcresult.
final class OnboardingFlowUITests: XCTestCase {
    var app: XCUIApplication!
    private var shotIndex = 0
    private let shotDir = "/tmp/loopr-shots"

    override func setUpWithError() throws {
        continueAfterFailure = false
        try? FileManager.default.createDirectory(atPath: shotDir, withIntermediateDirectories: true)
        app = XCUIApplication()
        app.launchArguments += ["-uitest"]
        app.launchEnvironment["LOOPR_API_BASE_URL"] = "http://127.0.0.1:8000"
        app.launch()
    }

    override func tearDownWithError() throws {
        shot("zz-final-state")   // always capture where we ended, including on failure
    }

    private func shot(_ name: String) {
        shotIndex += 1
        let s = XCUIScreen.main.screenshot()
        let a = XCTAttachment(screenshot: s)
        a.name = name; a.lifetime = .keepAlways
        add(a)
        let file = String(format: "%@/%02d-%@.png", shotDir, shotIndex, name)
        try? s.pngRepresentation.write(to: URL(fileURLWithPath: file))
    }

    private func dismissKeyboard() {
        app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.1)).tap()
    }

    private func type(_ id: String, _ text: String, file: StaticString = #filePath, line: UInt = #line) {
        let f = app.textFields[id]
        XCTAssertTrue(f.waitForExistence(timeout: 20), "Field '\(id)' not found", file: file, line: line)
        f.tap()
        f.typeText(text)
    }

    private func tapButton(_ label: String, file: StaticString = #filePath, line: UInt = #line) {
        let b = app.buttons[label]
        XCTAssertTrue(b.waitForExistence(timeout: 20), "Button '\(label)' not found", file: file, line: line)
        b.tap()
    }

    func testFullOnboardingToHome() throws {
        // 1. Phone & OTP
        type("phoneField", "9876543210")
        shot("phone-number")
        dismissKeyboard()
        tapButton("Send OTP")
        type("otpField", "123456")
        shot("otp")
        dismissKeyboard()
        tapButton("Verify")

        // 2. Society
        let lotus = app.staticTexts["Lotus Boulevard"]
        XCTAssertTrue(lotus.waitForExistence(timeout: 20), "Society list did not load")
        shot("society-selection")
        lotus.tap()

        // 3. Flat & parking
        type("Flat no.", "B-1204")
        tapButton("B2")
        type("Slot number · required", "B2-047")
        dismissKeyboard()
        shot("flat-and-parking")
        tapButton("Next")

        // 4. Vehicle
        type("Vehicle name", "Honda City")
        dismissKeyboard()
        shot("add-vehicle")
        tapButton("Next")

        // 5. Plan
        let planContinue = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Continue'")).firstMatch
        XCTAssertTrue(planContinue.waitForExistence(timeout: 20), "Plan screen did not load a quote")
        shot("plan-selection")
        planContinue.tap()

        // 6. Clean window
        XCTAssertTrue(app.buttons["Skip for now"].waitForExistence(timeout: 20))
        shot("clean-window")
        tapButton("Continue")

        // 7. Summary & pay (Debug build simulates the gateway through the webhook path)
        XCTAssertTrue(app.buttons["Set up UPI Autopay"].waitForExistence(timeout: 20))
        shot("summary")
        tapButton("Set up UPI Autopay")

        // 8. Home: subscription must be confirmed active by the backend
        XCTAssertTrue(app.staticTexts["Scheduled"].waitForExistence(timeout: 30), "Dashboard did not reach 'Scheduled'")
        shot("home-dashboard")

        app.tabBars.buttons["Vehicles"].tap()
        XCTAssertTrue(app.staticTexts["Active"].waitForExistence(timeout: 20), "Vehicle not shown as Active")
        shot("vehicles")
    }
}
