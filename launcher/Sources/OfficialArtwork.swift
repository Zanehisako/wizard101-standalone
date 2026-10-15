import AppKit
import CryptoKit
import SwiftUI

// Official website art is fetched separately from the open-source distribution.
// A verified local cache keeps it available offline without delaying setup.
@MainActor
final class OfficialArtwork: ObservableObject {
    @Published private(set) var city: NSImage?
    @Published private(set) var logo: NSImage?
    private let cache: URL
    private var loaded = false

    init(cache: URL) { self.cache = cache }

    func load() async {
        guard !loaded else { return }
        loaded = true
        async let background = image(name: "wizard-city.webp",
            url: "https://akamai.strapi.kingsisle.com/uploads/Worlds_Slide_Wizard_City_LG_Background_01a29d23a3.webp",
            digest: "8ccd770ae8c32a45a5e5df0fe0c5ef0ba3ea66590325249f9966e16c1fc2a70e")
        async let brand = image(name: "wizard101-logo.png",
            url: "https://akamai.wizard101.com/image/free/Wizard/Landing-Pages/Networks/ExplorePlay_logo.png",
            digest: "c2cdac530d857d5024dc3537120065a8bcd1eb308f0c295f7ea9fcd1379d2056")
        city = await background
        logo = await brand
    }

    private func image(name: String, url: String, digest: String) async -> NSImage? {
        let file = cache.appendingPathComponent(name)
        if let data = try? Data(contentsOf: file), let result = Self.verified(data, digest: digest) { return result }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpShouldSetCookies = false
        configuration.urlCredentialStorage = nil
        configuration.timeoutIntervalForResource = 20
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        do {
            let (data, response) = try await session.data(from: URL(string: url)!)
            guard let response = response as? HTTPURLResponse, response.statusCode == 200,
                  response.url?.scheme == "https", let result = Self.verified(data, digest: digest) else { return nil }
            try? FileManager.default.createDirectory(at: cache, withIntermediateDirectories: true)
            try? data.write(to: file, options: .atomic)
            return result
        } catch { return nil }
    }

    private static func verified(_ data: Data, digest: String) -> NSImage? {
        guard !data.isEmpty, data.count <= 4 * 1024 * 1024,
              SHA256.hash(data: data).map({ String(format: "%02x", $0) }).joined() == digest,
              let image = NSImage(data: data), image.size.width > 0, image.size.height > 0,
              image.size.width <= 4096, image.size.height <= 4096 else { return nil }
        return image
    }
}

struct ArtworkScene: View {
    let image: NSImage
    let animated: Bool
    var body: some View {
        GeometryReader { geometry in
            ZStack {
                Image(nsImage: image).resizable().scaledToFill()
                    .frame(width: geometry.size.width, height: geometry.size.height).clipped()
                LinearGradient(stops: [.init(color: .black.opacity(0.75), location: 0),
                    .init(color: .clear, location: 0.38), .init(color: .clear, location: 0.68),
                    .init(color: Color(red: 0.10, green: 0.055, blue: 0.19), location: 1)],
                    startPoint: .top, endPoint: .bottom)
                if animated {
                    TimelineView(.animation(minimumInterval: 1.0 / 24.0)) { timeline in
                        Canvas { context, size in
                            let time = timeline.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 3600)
                            for i in 0..<30 {
                                let x = Double((i * 137 + 41) % 997) / 997 * size.width
                                let y = (Double(i) * 53 + time * (8 + Double(i % 3) * 3)).truncatingRemainder(dividingBy: size.height)
                                let radius = i % 5 == 0 ? 2.0 : 1.0
                                let opacity = 0.3 + 0.35 * (1 + sin(time + Double(i))) / 2
                                var glow = context; glow.addFilter(.blur(radius: 3))
                                let dot = Path(ellipseIn: CGRect(x: x, y: size.height - y, width: radius * 2, height: radius * 2))
                                glow.fill(dot, with: .color(.yellow.opacity(opacity)))
                                context.fill(dot, with: .color(Color(red: 1, green: 0.91, blue: 0.66).opacity(opacity)))
                            }
                        }
                    }
                }
            }
        }
    }
}
