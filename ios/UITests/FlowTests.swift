import XCTest

/// Walks through the app against a running unplugged.ai test server.
/// Environment (TEST_RUNNER_ prefix when run with xcodebuild): UITEST_HOST, UITEST_USER, UITEST_PASS, UITEST_NEARBY (service name).
final class FlowTests: XCTestCase {
    let env = ProcessInfo.processInfo.environment

    func shot(_ app: XCUIApplication, _ name: String) {
        let a = XCTAttachment(screenshot: app.screenshot())
        a.name = name
        a.lifetime = .keepAlways
        add(a)
    }

    func launchFresh() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-reset"]
        app.launch()
        for _ in 0..<4 {
            let next = app.buttons["onboarding.next"]
            XCTAssertTrue(next.waitForExistence(timeout: 5))
            next.tap()
        }
        XCTAssertTrue(app.buttons["servers.add"].waitForExistence(timeout: 5), "settings did not open on Servers")
        return app
    }

    func signIn(_ app: XCUIApplication) {
        let name = app.textFields["signin.name"]
        XCTAssertTrue(name.waitForExistence(timeout: 20), "no sign-in sheet")
        name.tap(); name.typeText(env["UITEST_USER"] ?? "")
        let pw = app.secureTextFields["signin.password"]
        pw.tap(); pw.typeText(env["UITEST_PASS"] ?? "")
        shot(app, "sign-in")
        app.buttons["signin.go"].tap()
    }

    func askPong(_ app: XCUIApplication, _ label: String) {
        let input = app.textFields["chat.input"]
        XCTAssertTrue(input.waitForExistence(timeout: 20), "no composer")
        shot(app, "\(label)-empty")
        input.tap()
        input.typeText("Reply with only the word pong, in lowercase.")
        app.buttons["chat.send"].tap()
        let pong = app.staticTexts.matching(NSPredicate(format: "label ==[c] 'pong' OR label ==[c] 'pong.'")).firstMatch
        XCTAssertTrue(pong.waitForExistence(timeout: 240), "no answer arrived")
        sleep(2)
        shot(app, "\(label)-answer")
    }

    func testAddressSignInChatAndSections() throws {
        let app = launchFresh()
        sleep(3)
        shot(app, "servers")
        app.buttons["servers.add"].tap()
        let field = app.textFields["editor.address"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        field.tap()
        field.typeText(env["UITEST_HOST"] ?? "127.0.0.1:8020")
        app.buttons["Test connection"].tap()
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH 'Found unplugged.ai'")).firstMatch.waitForExistence(timeout: 10))
        shot(app, "add-server")
        app.buttons["editor.save"].tap()
        signIn(app)
        askPong(app, "chat")

        app.buttons["top.model"].tap()
        sleep(1)
        shot(app, "model-menu")
        app.tap()   // closes the menu
        sleep(1)

        app.buttons["top.menu"].tap()
        sleep(1)
        shot(app, "sidebar")
        for s in ["music", "pictures", "library", "console"] {
            if !app.buttons["side.\(s)"].isHittable { app.buttons["top.menu"].tap(); sleep(1) }
            app.buttons["side.\(s)"].tap()
            sleep(3)
            shot(app, s)
            app.buttons["top.menu"].tap()
            sleep(1)
        }
        app.buttons["side.settings"].tap()
        sleep(2)
        shot(app, "settings-general")
        for p in ["personal", "memory", "projects", "models", "help"] {
            app.buttons["pane.\(p)"].tap()
            sleep(2)
            shot(app, "settings-\(p)")
        }
    }

    func testNearbyConnection() throws {
        guard let nearby = env["UITEST_NEARBY"] else { throw XCTSkip("UITEST_NEARBY not set") }
        let app = launchFresh()
        let row = app.staticTexts[nearby.replacingOccurrences(of: "unplugged.ai on ", with: "")]
        XCTAssertTrue(row.waitForExistence(timeout: 15), "nearby Mac not found")
        shot(app, "nearby-found")
        row.tap()
        signIn(app)
        askPong(app, "nearby")
    }
}
