import Foundation

/// Members and saved places from one refresh.
struct HouseholdSnapshot {
    var members: [HouseholdMember]
    var places: [SavedPlace]
}
