import Foundation

/// A saved place: a named circle and the members who get arrival or departure alerts for it.
struct SavedPlace: Identifiable {
    var id: String
    var name: String
    var lat: Double
    var lon: Double
    var radius: Double
    var recordId: String
    var alerts: Wire.Object
    var data: Wire.Object
}
