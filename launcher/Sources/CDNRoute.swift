import Foundation
import CFNetwork

// Retry a failing CDN route without changing the asset URL or system DNS.
// These sessions carry public downloads only; installed content still requires
// the manifest's exact full-file CRC before the transaction can commit.
enum CDNRoute {
    static let host = "versionak.us.wizard101.com"
    static let endpoint = URL(string: "https://cloudflare-dns.com/dns-query?name=versionak.us.wizard101.com&type=A")!

    static func publicIPv4(_ text: String) -> Bool {
        let parts = text.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 4 else { return false }
        let numbers = parts.compactMap { part -> Int? in
            guard part.allSatisfy({ $0.isASCII && $0.isNumber }), let value = Int(part),
                  value >= 0, value <= 255, String(value) == part else { return nil }
            return value
        }
        guard numbers.count == 4 else { return false }
        let a = numbers[0], b = numbers[1], c = numbers[2]
        return a > 0 && a < 224 && a != 10 && a != 127
            && !(a == 100 && (64...127).contains(b))
            && !(a == 169 && b == 254) && !(a == 172 && (16...31).contains(b))
            && !(a == 192 && (b == 168 || (b == 0 && (c == 0 || c == 2))))
            && !(a == 198 && (b == 18 || b == 19 || (b == 51 && c == 100)))
            && !(a == 203 && b == 0 && c == 113)
    }

    static func proxyActive(_ settings: [String: Any]) -> Bool {
        let flags = ["HTTPEnable", "HTTPSEnable", "SOCKSEnable", "ProxyAutoConfigEnable", "ProxyAutoDiscoveryEnable"]
        if flags.contains(where: { (settings[$0] as? NSNumber)?.boolValue == true }) { return true }
        for value in settings.values {
            if let nested = value as? [String: Any], proxyActive(nested) { return true }
        }
        return false
    }

    static func permitted(_ url: URL, settings: [String: Any]?, environment: [String: String]) -> Bool {
        guard url.scheme == "http", url.host == host, url.port == nil,
              (try? PatchManifest.safeURL(url.absoluteString)) == url, let settings,
              !proxyActive(settings) else { return false }
        return !["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]
            .contains { !(environment[$0] ?? "").isEmpty }
    }

    static func available(_ url: URL) -> Bool {
        let settings = CFNetworkCopySystemProxySettings()?.takeRetainedValue() as? [String: Any]
        return permitted(url, settings: settings, environment: ProcessInfo.processInfo.environment)
    }

    static func parse(_ data: Data) throws -> [String] {
        func invalid() -> LauncherError { .message("An alternate official download route is unavailable.") }
        func name(_ value: Any?) -> String? {
            guard var text = (value as? String)?.lowercased() else { return nil }
            if text.hasSuffix(".") { text.removeLast() }
            guard !text.isEmpty, text.count <= 253,
                  text.split(separator: ".", omittingEmptySubsequences: false).allSatisfy({ label in
                      !label.isEmpty && label.count <= 63 && label.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-") }
                  }) else { return nil }
            return text
        }
        guard data.count <= 65536, let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              (root["Status"] as? Int) == 0, (root["TC"] as? Bool) == false,
              let questions = root["Question"] as? [[String: Any]], questions.count == 1,
              name(questions[0]["name"]) == host,
              questions[0]["type"] as? Int == 1,
              let answers = root["Answer"] as? [[String: Any]], answers.count <= 64 else { throw invalid() }
        var current = host, visited = Set<String>(), addresses = [String]()
        for _ in 0..<8 {
            guard visited.insert(current).inserted else { throw invalid() }
            let records = answers.filter { name($0["name"]) == current && ($0["TTL"] as? Int ?? 0) > 0 }
            for record in records where record["type"] as? Int == 1 {
                guard let address = record["data"] as? String, publicIPv4(address) else { throw invalid() }
                if !addresses.contains(address) { addresses.append(address) }
            }
            if !addresses.isEmpty { return Array(addresses.prefix(2)) }
            let aliases = records.filter { $0["type"] as? Int == 5 }
            guard aliases.count == 1, let next = name(aliases[0]["data"]), !next.isEmpty else { throw invalid() }
            current = next
        }
        throw invalid()
    }

    static func addresses(token: CancellationToken, testConfiguration: URLSessionConfiguration? = nil) throws -> [String] {
        try parse(DNSRouteRequest(token: token, testConfiguration: testConfiguration).run())
    }
}

private final class DNSRouteRequest: NSObject, URLSessionDataDelegate {
    let token: CancellationToken
    let testConfiguration: URLSessionConfiguration?
    var bytes = Data(), failure: Error?, accepted = false
    let complete = DispatchSemaphore(value: 0)
    init(token: CancellationToken, testConfiguration: URLSessionConfiguration?) {
        self.token = token; self.testConfiguration = testConfiguration
    }
    func run() throws -> Data {
        try token.check()
        let configuration = testConfiguration?.copy() as? URLSessionConfiguration ?? URLSessionConfiguration.ephemeral
        configuration.urlCache = nil; configuration.httpCookieStorage = nil; configuration.urlCredentialStorage = nil
        configuration.timeoutIntervalForRequest = 10; configuration.timeoutIntervalForResource = 15
        let queue = OperationQueue(); queue.maxConcurrentOperationCount = 1
        let session = URLSession(configuration: configuration, delegate: self, delegateQueue: queue)
        defer { session.invalidateAndCancel() }
        var request = URLRequest(url: CDNRoute.endpoint)
        request.setValue("application/dns-json", forHTTPHeaderField: "Accept")
        let task = session.dataTask(with: request); task.resume()
        while complete.wait(timeout: .now() + 0.1) == .timedOut { if token.isCancelled { task.cancel() } }
        try token.check()
        if let failure { throw failure }
        guard accepted else { throw LauncherError.message("An alternate official download route is unavailable.") }
        return bytes
    }
    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        guard let http = response as? HTTPURLResponse, http.statusCode == 200,
              response.url == CDNRoute.endpoint, response.expectedContentLength <= 65536 else {
            failure = LauncherError.message("Invalid download route response."); completionHandler(.cancel); return
        }
        accepted = true; completionHandler(.allow)
    }
    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        if token.isCancelled || data.count > 65536 - bytes.count {
            failure = LauncherError.message("Download route response exceeded its limit."); dataTask.cancel()
        } else { bytes.append(data) }
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if failure == nil { failure = error }; complete.signal()
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        failure = LauncherError.message("Download route lookup was redirected."); completionHandler(nil)
    }
}
