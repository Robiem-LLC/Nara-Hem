import SwiftUI
import UIKit

/// A member's profile photo in a circle, or a placeholder if they have none.
struct ProfileAvatar: View {
    let member: HouseholdMember

    var body: some View {
        if let image = ProfilePhoto.image(member.photo) {
            Image(uiImage: image).resizable().scaledToFill().clipShape(Circle())
        } else {
            Image(systemName: "person.crop.circle.fill").resizable().scaledToFit()
                .foregroundStyle(accent)
        }
    }
}
