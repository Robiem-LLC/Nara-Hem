import Foundation
import SwiftUI

/// Build date and commit from Info.plist, shown in Settings.
enum NaraHemBuild {
    static let dateString: String = {
        guard
            let string = Bundle.main.object(forInfoDictionaryKey: "NARAHEM_BUILD_UTC") as? String,
            !string.isEmpty, !string.contains("$("),
            let date = ISO8601DateFormatter().date(from: string)
        else { return "Local build" }
        return date.formatted(date: .abbreviated, time: .shortened)
    }()

    static let commit: String = {
        guard
            let value = Bundle.main.object(forInfoDictionaryKey: "NARAHEM_BUILD_COMMIT")
                as? String,
            !value.isEmpty, !value.contains("$(")
        else { return "local" }
        return String(value.prefix(10))
    }()
}
