import Foundation

/// Messages between the watch app and the iPhone app (WatchConnectivity). The watch never talks to the server
/// itself: the iPhone does the network request and sends the result back.
enum WatchMessage {
    static let kind = "kind"

    // watch -> phone
    static let status = "status"          // reply: serverName, connected, signedIn
    static let ask = "ask"                // text, id; reply: accepted or error. The answer follows as an `answer` message.

    // phone -> watch
    static let answer = "answer"          // id, question, text, error

    static let text = "text"
    static let id = "id"
    static let question = "question"
    static let error = "error"
    static let accepted = "accepted"
    static let serverName = "serverName"
    static let connected = "connected"
    static let signedIn = "signedIn"
}
