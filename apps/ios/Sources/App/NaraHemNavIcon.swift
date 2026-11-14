import Foundation
import SwiftUI

/// Tab bar icon drawn from 24x24 paths. Android's NaraHemTabIcon uses the same paths.
struct NaraHemNavIcon: View {
    let kind: Int
    let color: Color

    var body: some View {
        SymbolPath(kind: kind)
            .stroke(color, style: StrokeStyle(lineWidth: 2.0, lineCap: .round, lineJoin: .round))
            .frame(width: 24, height: 24)
            .accessibilityHidden(true)
    }

    /// The outline of one icon.
    private struct SymbolPath: Shape {
        let kind: Int

        /// Returns the icon path scaled to rect.
        func path(in rect: CGRect) -> Path {
            var p = Path()
            let s = min(rect.width, rect.height) / 24
            func point(_ x: CGFloat, _ y: CGFloat) -> CGPoint {
                CGPoint(x: rect.minX + x * s, y: rect.minY + y * s)
            }
            switch kind {
            case 0:
                p.move(to: point(2, 6)); p.addLine(to: point(9, 3)); p.addLine(to: point(15, 6))
                p.addLine(to: point(22, 3)); p.addLine(to: point(22, 18));
                p.addLine(to: point(15, 21))
                p.addLine(to: point(9, 18)); p.addLine(to: point(2, 21)); p.closeSubpath()
                p.move(to: point(9, 3)); p.addLine(to: point(9, 18))
                p.move(to: point(15, 6)); p.addLine(to: point(15, 21))
            case 1:
                p.move(to: point(4, 15)); p.addLine(to: point(6, 9))
                p.addQuadCurve(to: point(8, 7), control: point(6.5, 7))
                p.addLine(to: point(16, 7));
                p.addQuadCurve(to: point(18, 9), control: point(17.5, 7))
                p.addLine(to: point(20, 15)); p.addLine(to: point(20, 19))
                p.addLine(to: point(17, 19)); p.addLine(to: point(17, 17))
                p.addLine(to: point(7, 17)); p.addLine(to: point(7, 19))
                p.addLine(to: point(4, 19)); p.closeSubpath()
                p.move(to: point(5, 13)); p.addLine(to: point(19, 13))
                p.addEllipse(
                    in: CGRect(
                        x: rect.minX + 6 * s, y: rect.minY + 14 * s, width: 2 * s, height: 2 * s))
                p.addEllipse(
                    in: CGRect(
                        x: rect.minX + 16 * s, y: rect.minY + 14 * s, width: 2 * s, height: 2 * s))
            case 2:
                p.move(to: point(12, 22))
                p.addCurve(to: point(4.5, 9), control1: point(9, 18), control2: point(4.5, 12))
                p.addCurve(to: point(12, 2), control1: point(4.5, 5), control2: point(7.5, 2))
                p.addCurve(to: point(19.5, 9), control1: point(16.5, 2), control2: point(19.5, 5))
                p.addCurve(to: point(12, 22), control1: point(19.5, 12), control2: point(15, 18))
                p.closeSubpath()
                p.addEllipse(
                    in: CGRect(
                        x: rect.minX + 9 * s, y: rect.minY + 6 * s, width: 6 * s, height: 6 * s))
            default:
                p.addEllipse(
                    in: CGRect(
                        x: rect.minX + 5 * s, y: rect.minY + 5 * s, width: 14 * s, height: 14 * s))
                p.addEllipse(
                    in: CGRect(
                        x: rect.minX + 9 * s, y: rect.minY + 9 * s, width: 6 * s, height: 6 * s))
                for i in 0..<8 {
                    let a = Double(i) * Double.pi / 4
                    let dx = CGFloat(cos(a)), dy = CGFloat(sin(a))
                    p.move(to: point(12 + dx * 9, 12 + dy * 9))
                    p.addLine(to: point(12 + dx * 11, 12 + dy * 11))
                }
            }
            return p
        }
    }
}
