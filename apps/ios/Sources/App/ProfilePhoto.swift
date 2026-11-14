import UIKit

/// Decodes profile photo data URIs into images and caches the results.
enum ProfilePhoto {
    private static let prefix = "data:image/jpeg;base64,"
    private static let cache = NSCache<NSString, UIImage>()

    /// Returns the decoded photo, or nil if the URI is missing or not a JPEG data URI.
    static func image(_ uri: String?) -> UIImage? {
        guard let uri, uri.hasPrefix(prefix) else { return nil }
        if let cached = cache.object(forKey: uri as NSString) { return cached }
        guard let raw = Data(base64Encoded: String(uri.dropFirst(prefix.count))),
            let image = UIImage(data: raw)
        else { return nil }
        cache.setObject(image, forKey: uri as NSString)
        return image
    }
}
