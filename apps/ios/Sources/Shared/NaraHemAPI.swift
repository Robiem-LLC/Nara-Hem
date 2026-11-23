import Foundation

/// Session delegate that refuses redirects, so credentials are never sent to another host.
private final class NoRedirects: NSObject, URLSessionTaskDelegate {
    /// Rejects every redirect.
    func urlSession(
        _ session: URLSession, task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void
    ) {
        completionHandler(nil)
    }
}

/// HTTPS client for the household server. Holds the access token in memory and the refresh token in
/// the keychain.
@MainActor
final class NaraHemAPI {
    private let session: URLSession
    private(set) var origin: URL?
    private(set) var token: String?
    private var refreshGrant: String?
    private var rotation: Task<String, Error>?

    /// Creates the client. Tests pass a configuration that answers requests without a server.
    init(configuration: URLSessionConfiguration = NaraHemAPI.configuration()) {
        session = URLSession(
            configuration: configuration, delegate: NoRedirects(), delegateQueue: nil)
    }

    /// Session settings for the household server: no cookies and a 25-second request timeout.
    nonisolated static func configuration() -> URLSessionConfiguration {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 25
        config.httpCookieStorage = nil
        config.httpShouldSetCookies = false
        return config
    }

    /// Parses a typed server address into an HTTPS URL. Throws a user-facing error if it is
    /// invalid.
    static func serverURL(_ entered: String) throws -> URL {
        let input = entered.trimmingCharacters(in: .whitespacesAndNewlines)
        guard
            var pieces = URLComponents(string: input.contains("://") ? input : "https://" + input),
            pieces.scheme?.lowercased() == "https", !(pieces.host ?? "").isEmpty,
            pieces.user == nil, pieces.password == nil, pieces.query == nil,
            pieces.fragment == nil, pieces.path.isEmpty || pieces.path == "/"
        else {
            throw NaraHemProtocolError.rejected(
                "Enter your household's HTTPS server address without a path.")
        }
        pieces.path = ""
        guard let url = pieces.url else {
            throw NaraHemProtocolError.rejected("Invalid server URL")
        }
        return url
    }

    /// Sets the server for later requests.
    func setServer(_ server: String) throws {
        origin = try Self.serverURL(server)
    }

    /// Returns the full URL for an API path.
    private func endpoint(_ path: String) throws -> URL {
        guard path.hasPrefix("/api/"), let origin,
            let url = URL(string: path, relativeTo: origin)?.absoluteURL,
            url.host == origin.host, url.scheme == origin.scheme
        else {
            throw NaraHemProtocolError.rejected("Invalid API endpoint")
        }
        return url
    }

    /// Sends a JSON request and returns the response, converting failures into readable errors.
    private func send(
        _ path: String, method: String = "GET", payload: Wire.Object? = nil, bearer: String? = nil,
        headers: [String: String] = [:]
    ) async throws -> Wire.Object {
        var request = URLRequest(url: try endpoint(path))
        request.httpMethod = method
        request.setValue("native", forHTTPHeaderField: "X-NaraHem-Client")
        if let bearer { request.setValue("Bearer " + bearer, forHTTPHeaderField: "Authorization") }
        headers.forEach { request.setValue($0.value, forHTTPHeaderField: $0.key) }
        if method != "GET" {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try Wire.encode(payload ?? [:])
        }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw NaraHemProtocolError.rejected("Invalid server response")
        }
        let json = (try? Wire.decode(data)) ?? [:]
        guard (200...299).contains(http.statusCode) else {
            let message =
                (json["detail"] as? String) ?? "Server rejected request (\(http.statusCode))"
            throw NaraHemProtocolError.http(http.statusCode, message)
        }
        return json
    }

    /// Sends an unauthenticated request.
    func publicRequest(_ path: String, payload: Wire.Object) async throws -> Wire.Object {
        try await send(path, method: "POST", payload: payload)
    }

    /// Signs in with email and password and stores the refresh token.
    func signIn(
        server: String, identifier: String, password: String
    ) async throws -> NaraHemAccount {
        try setServer(server)
        guard !identifier.trimmingCharacters(in: .whitespaces).isEmpty && !password.isEmpty else {
            throw NaraHemProtocolError.rejected("Enter your email or phone number and password.")
        }
        let response = try await send(
            "/api/login", method: "POST",
            payload: [
                "email": identifier.trimmingCharacters(in: .whitespacesAndNewlines),
                "password": password, "native": true,
            ])
        let access = try Wire.string(response, "access_token")
        let account = try await accountDetails(bearer: access)
        token = access
        refreshGrant = response["refresh_token"] as? String
        if let grant = refreshGrant, let origin {
            let record: Wire.Object = ["server": origin.absoluteString, "refresh_token": grant]
            SecureVault.put(try Wire.encode(record), key: "ios-native-session")
        }
        return account
    }

    /// Loads the account and household name with the given access token.
    private func accountDetails(bearer: String) async throws -> NaraHemAccount {
        let session = try await send("/api/session", bearer: bearer)
        let household = try await send("/api/household", bearer: bearer)
        return NaraHemAccount(
            id: try Wire.string(session, "id"),
            name: (session["username"] as? String)
                ?? ((session["role"] as? String) == "admin" ? "Admin" : "Member"),
            household: try Wire.string(household, "id"),
            role: (session["role"] as? String) ?? "member",
            verified: (session["verified"] as? Bool) ?? false)
    }

    /// Restores the session from the stored refresh token, or returns nil.
    func restore(server: String) async throws -> NaraHemAccount? {
        try setServer(server)
        guard let stored = SecureVault.get("ios-native-session"),
            let record = try? Wire.decode(stored),
            record["server"] as? String == origin?.absoluteString,
            let grant = record["refresh_token"] as? String
        else { return nil }
        refreshGrant = grant
        _ = try await rotate()
        guard let token else { return nil }
        return try await accountDetails(bearer: token)
    }

    /// Exchanges the refresh token for new tokens. Concurrent callers share one exchange.
    private func rotate() async throws -> String {
        if let rotation { return try await rotation.value }
        guard let grant = refreshGrant else {
            throw NaraHemProtocolError.rejected("Sign in again to continue.")
        }
        let task = Task<String, Error> {
            let result = try await send(
                "/api/native/session/refresh", method: "POST",
                payload: ["refresh_token": grant])
            let newAccess = try Wire.string(result, "access_token")
            let newRefresh = try Wire.string(result, "refresh_token")
            guard let origin else { throw NaraHemProtocolError.rejected("Server unavailable") }
            SecureVault.put(
                try Wire.encode(["server": origin.absoluteString, "refresh_token": newRefresh]),
                key: "ios-native-session")
            refreshGrant = newRefresh
            token = newAccess
            return newAccess
        }
        rotation = task
        defer { rotation = nil }
        do { return try await task.value } catch {
            // Keep the refresh token after a network failure; only a rejected token needs a new
            // sign-in.
            throw error
        }
    }

    /// Sends a request as the signed-in account, rotating the refresh token and retrying once on
    /// HTTP 401.
    func accountRequest(
        _ path: String, payload: Wire.Object? = nil, method: String = "GET"
    ) async throws -> Wire.Object {
        guard let token else { throw NaraHemProtocolError.rejected("Sign in required") }
        do { return try await send(path, method: method, payload: payload, bearer: token) } catch {
            guard refreshGrant != nil else { throw error }
            // Only rotate on HTTP 401, so network errors and 409s never spend the refresh token.
            guard case NaraHemProtocolError.http(let status, _) = error, status == 401 else {
                throw error
            }
            return try await send(
                path, method: method, payload: payload, bearer: try await rotate())
        }
    }

    /// Changes the display name.
    func updateUsername(_ name: String) async throws -> String {
        let proposed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard
            proposed.range(of: #"^[A-Za-z0-9_.-]{3,64}$"#, options: .regularExpression) != nil
        else {
            throw NaraHemProtocolError.rejected(
                "Use 3–64 letters, numbers, periods, dashes or underscores.")
        }
        let result = try await accountRequest(
            "/api/account/username",
            payload: ["username": proposed], method: "PUT")
        return try Wire.string(result, "username")
    }

    /// Sends a request with the device credential.
    func deviceRequest(
        _ path: String, credential: String, payload: Wire.Object? = nil,
        method: String = "GET", headers: [String: String] = [:]
    ) async throws -> Wire.Object {
        try await send(path, method: method, payload: payload, bearer: credential, headers: headers)
    }

    /// Revokes the session on the server when reachable and always clears it locally.
    func signOut() async {
        let grant = refreshGrant
        let previous = token
        SecureVault.delete("ios-native-session")
        SecureVault.delete("account-access-token")
        SecureVault.delete("account-refresh-token")
        token = nil
        refreshGrant = nil
        if let grant {
            _ = try? await send(
                "/api/native/session/revoke", method: "POST", payload: ["refresh_token": grant])
        }
        if let previous {
            _ = try? await send("/api/logout", method: "POST", payload: [:], bearer: previous)
        }
    }

    /// Asks the server for a new invitation link by email, or a code by text.
    func requestInvite(server: String, contact: String) async throws -> String {
        try setServer(server)
        let result = try await publicRequest("/api/enrollment/request", payload: ["email": contact])
        return (result["message"] as? String) ?? "Check your invitation"
    }

    /// Completes an invitation by setting the username and password. Takes the six-digit code
    /// texted to the contact, or the email link or its token.
    func verifyInvite(
        server: String, contact: String, code: String, username: String, password: String
    ) async throws {
        try setServer(server)
        let entered = code.trimmingCharacters(in: .whitespacesAndNewlines)
        var payload: [String: Any] = [
            "username": username.isEmpty ? NSNull() : username as Any,
            "password": password.isEmpty ? NSNull() : password as Any,
        ]
        if entered.count == 6, entered.allSatisfy(\.isASCII), entered.allSatisfy(\.isNumber) {
            payload["email"] = contact
            payload["code"] = entered
        } else {
            let link = entered.components(separatedBy: "#verify=").last ?? entered
            payload["token"] = link.components(separatedBy: "&").first ?? link
        }
        _ = try await publicRequest("/api/enrollment/verify", payload: payload)
    }

    /// Sends a request for the admin to invite this person.
    func requestAccess(
        server: String, contact: String, name: String, relationship: String
    ) async throws -> String {
        try setServer(server)
        let result = try await publicRequest(
            "/api/invitation-requests",
            payload: ["email": contact, "name": name, "relationship": relationship])
        return (result["message"] as? String) ?? "Request submitted"
    }
}
