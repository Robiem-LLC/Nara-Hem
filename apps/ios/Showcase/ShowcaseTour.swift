import XCTest

/// Films a tour of the app for the showcase site, against the fictional household that
/// tools/showcase/run.py serves. Not part of the app's test suite: ci/remote/build.py adds
/// it to a separate scheme only for showcase builds.
///
/// run.py talks to this test through files in SHOWCASE_CONTROL: the test writes `ready`
/// (start recording), `code-wanted` and chapter marks; run.py answers with `code`.
final class ShowcaseTour: XCTestCase {
    private let env = ProcessInfo.processInfo.environment
    private let app = XCUIApplication()
    private let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")

    private var control: URL {
        URL(fileURLWithPath: env["SHOWCASE_CONTROL"] ?? NSTemporaryDirectory())
    }

    override func setUp() {
        continueAfterFailure = false
    }

    func testShowcaseTour() throws {
        signal("ready")
        pause(2)
        app.launch()
        mark("signin")
        caption("Open Nära Hem and enter your server's address, your email and password.")

        // Pasted, not typed: the URL keyboard autocompletes domains while typing.
        paste(env["SHOWCASE_SERVER"] ?? "", into: textField("Server address"))
        type(env["SHOWCASE_EMAIL"] ?? "", into: textField("Email or phone number"))
        tap(app.buttons["Continue"])
        type(env["SHOWCASE_PASSWORD"] ?? "", into: secureField("Password"), secure: true)
        tap(app.buttons["Sign in"])
        caption("Register this iPhone. Your server emails you a six-digit code.")

        let register = app.buttons["Register this iPhone"]
        let emailCode = app.buttons["Send my six-digit code"]
        waitForAny([register, emailCode], timeout: 60)
        if register.exists { tap(register) }
        wait(emailCode, timeout: 60)
        tap(emailCode)
        signal("code-wanted")
        caption("Enter the code from the email, then allow location and notifications.")
        type(waitForFile("code", timeout: 90), into: textField("Six-digit code"))
        tap(app.buttons["Verify and register this iPhone"])

        let mapTab = app.buttons["Map"]
        wait(mapTab, timeout: 90)
        caption("")
        mark("map")
        pause(14)

        let alex = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Alex"))
            .firstMatch
        if alex.waitForExistence(timeout: 5) {
            mark("member")
            alex.tap()
            pause(8)
            let household = app.buttons["Household"]
            if household.exists { household.tap() }
            pause(2)
        }

        mark("trips")
        tap(app.buttons["Trips"])
        pause(2)
        let alexTrips = app.buttons["Alex"]
        if alexTrips.waitForExistence(timeout: 5) { alexTrips.tap() }
        pause(4)
        let trip = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "mph peak"))
            .firstMatch
        if trip.waitForExistence(timeout: 15) {
            mark("trip")
            trip.tap()
            pause(7)
            let done = app.buttons["Done"]
            if done.exists { done.tap() }
            pause(1)
        }

        mark("places")
        tap(app.buttons["Places"])
        pause(7)

        mark("live")
        tap(mapTab)
        pause(16)
        mark("end")
        signal("done")
    }

    // MARK: - Helpers

    private func textField(_ title: String) -> XCUIElement {
        app.textFields.matching(
            NSPredicate(
                format: "placeholderValue == %@ OR label == %@ OR identifier == %@",
                title, title, title)
        ).firstMatch
    }

    private func secureField(_ title: String) -> XCUIElement {
        app.secureTextFields.matching(
            NSPredicate(
                format: "placeholderValue == %@ OR label == %@ OR identifier == %@",
                title, title, title)
        ).firstMatch
    }

    /// Types and checks: the simulator keyboard can drop characters when typing fast,
    /// so a mismatch is cleared and typed again one character at a time.
    private func type(_ text: String, into element: XCUIElement, secure: Bool = false) {
        wait(element)
        element.tap()
        element.typeText(text)
        for _ in 0..<3 {
            let value = element.value as? String ?? ""
            if secure ? value.count == text.count : value == text { return }
            element.tap()
            element.typeText(
                String(
                    repeating: XCUIKeyboardKey.delete.rawValue,
                    count: max(value.count, text.count) + 2))
            for character in text {
                element.typeText(String(character))
                Thread.sleep(forTimeInterval: 0.05)
            }
        }
        let value = element.value as? String ?? ""
        signal(
            "typed",
            """
            expected \(secure ? String(repeating: "•", count: text.count) : text)\ngot      \
            \(value)
            """
        )
    }

    private func paste(_ text: String, into element: XCUIElement) {
        wait(element)
        UIPasteboard.general.string = text
        for _ in 0..<3 {
            element.tap()
            element.press(forDuration: 1.2)
            let selectAll = app.menuItems["Select All"]
            if selectAll.waitForExistence(timeout: 2) { selectAll.tap() }
            let pasteItem = app.menuItems["Paste"]
            if pasteItem.waitForExistence(timeout: 3) { pasteItem.tap() }
            pause(0.5)
            if (element.value as? String) == text { return }
        }
        type(text, into: element)
    }

    private func tap(_ element: XCUIElement) {
        wait(element)
        element.tap()
    }

    @discardableResult
    private func wait(
        _ element: XCUIElement, timeout: TimeInterval = 30,
        file: StaticString = #filePath, line: UInt = #line
    ) -> XCUIElement {
        let deadline = Date().addingTimeInterval(timeout)
        while !element.exists && Date() < deadline {
            dismissAlerts()
            _ = element.waitForExistence(timeout: 1)
        }
        if !element.exists { signal("screen", app.debugDescription) }
        XCTAssertTrue(element.exists, "Not found: \(element)", file: file, line: line)
        return element
    }

    private func waitForAny(_ elements: [XCUIElement], timeout: TimeInterval) {
        let deadline = Date().addingTimeInterval(timeout)
        while !elements.contains(where: \.exists) && Date() < deadline {
            dismissAlerts()
            Thread.sleep(forTimeInterval: 0.5)
        }
        if !elements.contains(where: \.exists) { signal("screen", app.debugDescription) }
        XCTAssertTrue(elements.contains(where: \.exists), "None found: \(elements)")
    }

    /// Location and notification prompts belong to SpringBoard, not the app.
    private func dismissAlerts() {
        // iOS offers to save the password after signing in; the tour doesn't need it.
        let notNow = app.buttons["Not Now"]
        if notNow.exists { notNow.tap() }
        let alert = springboard.alerts.firstMatch
        guard alert.exists else { return }
        for label in ["Allow While Using App", "Change to Always Allow", "Allow", "OK"] {
            let button = alert.buttons[label]
            if button.exists { button.tap(); return }
        }
    }

    private func pause(_ seconds: TimeInterval) {
        let end = Date().addingTimeInterval(seconds)
        while Date() < end {
            dismissAlerts()
            Thread.sleep(forTimeInterval: min(0.5, max(0, end.timeIntervalSinceNow)))
        }
    }

    private func signal(_ name: String, _ text: String = "") {
        try? text.write(to: control.appendingPathComponent(name), atomically: true, encoding: .utf8)
    }

    private func mark(_ chapter: String) {
        let url = control.appendingPathComponent("chapters.txt")
        let previous = (try? String(contentsOf: url, encoding: .utf8)) ?? ""
        try? (previous + "\(chapter) \(Date().timeIntervalSince1970)\n").write(
            to: url, atomically: true, encoding: .utf8)
    }

    /// Notes a caption for the setup clip (an empty text ends it); clips.py burns it in.
    private func caption(_ text: String) {
        let url = control.appendingPathComponent("captions.txt")
        let previous = (try? String(contentsOf: url, encoding: .utf8)) ?? ""
        try? (previous + "\(Date().timeIntervalSince1970)\t\(text)\n").write(
            to: url, atomically: true, encoding: .utf8)
    }

    private func waitForFile(_ name: String, timeout: TimeInterval) -> String {
        let url = control.appendingPathComponent(name)
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if let text = try? String(contentsOf: url, encoding: .utf8), !text.isEmpty {
                return text.trimmingCharacters(in: .whitespacesAndNewlines)
            }
            pause(0.5)
        }
        XCTFail("run.py did not provide \(name)")
        return ""
    }
}
