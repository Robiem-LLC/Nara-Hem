import CoreLocation

/// Spreads out member avatars that overlap on the map, in screen points only. Members within 35 m,
/// or within 100 m in the same saved place, form a group drawn as a row of slightly overlapping
/// avatars. Same rules as Android and the web map.
enum AvatarFan {
    /// Returns each member's offset for avatars `size` points wide.
    static func layout(
        _ people: [HouseholdMember], places: [SavedPlace], size: Double
    ) -> [String: Offset] {
        let members = people.compactMap { person -> (HouseholdMember, CLLocation)? in
            guard let lat = person.lat, let lon = person.lon else { return nil }
            return (person, CLLocation(latitude: lat, longitude: lon))
        }
        let place = members.map { member, at in
            places.first {
                at.distance(from: CLLocation(latitude: $0.lat, longitude: $0.lon))
                    <= $0.radius + min(50, max(15, member.accuracy ?? 25))
            }?.id
        }
        var parent = Array(members.indices)
        /// Returns the group representative for member i (union-find with path compression).
        func root(_ i: Int) -> Int {
            var x = i
            while parent[x] != x { parent[x] = parent[parent[x]]; x = parent[x] }
            return x
        }
        for i in members.indices {
            for j in members.indices where j > i {
                let distance = members[i].1.distance(from: members[j].1)
                if distance <= 35 || (place[i] != nil && place[i] == place[j] && distance <= 100) {
                    parent[root(j)] = root(i)
                }
            }
        }
        let step = size * 42 / 46, rise = size * 36 / 46
        var offsets: [String: Offset] = [:]
        for group in Dictionary(grouping: members.indices, by: root).values where group.count > 1 {
            let ordered = group.sorted { members[$0].0.id < members[$1].0.id }
            let cols = min(4, ordered.count)
            for (slot, index) in ordered.enumerated() {
                let row = slot / cols, inRow = slot % cols
                let count = min(cols, ordered.count - row * cols)
                offsets[members[index].0.id] = Offset(
                    dx: (Double(inRow) - Double(count - 1) / 2) * step,
                    dy: -Double(row) * rise, groupSize: ordered.count)
            }
        }
        return offsets
    }

    /// Screen offset for one avatar.
    struct Offset: Equatable {
        var dx: Double = 0
        var dy: Double = 0
        var groupSize = 1
    }
}
