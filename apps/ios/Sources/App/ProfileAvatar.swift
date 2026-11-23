import SwiftUI
import UIKit

/// A member's profile photo in a circle, or their initials ("JD") if they have none.
struct ProfileAvatar: View {
    let member: HouseholdMember

    var body: some View {
        if let image = ProfilePhoto.image(member.photo) {
            Image(uiImage: image).resizable().scaledToFill().clipShape(Circle())
        } else {
            GeometryReader { box in
                let side = min(box.size.width, box.size.height)
                Circle().fill(accent)
                    .overlay(
                        Text(Initials.of(member.name))
                            .font(.system(size: side * 0.38, weight: .bold))
                            .foregroundStyle(.black)
                            .minimumScaleFactor(0.5)
                            .lineLimit(1)
                    )
                    .frame(width: side, height: side)
            }
            .aspectRatio(1, contentMode: .fit)
        }
    }
}
