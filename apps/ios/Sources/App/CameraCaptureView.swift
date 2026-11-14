import CoreLocation
import MapKit
import PhotosUI
import SwiftUI
import UIKit

/// Presents the system camera for taking a profile photo.
struct CameraCaptureView: UIViewControllerRepresentable {
    let onCapture: (UIImage) -> Void
    let onCancel: () -> Void

    /// Creates the delegate that forwards the result to the callbacks.
    func makeCoordinator() -> Coordinator { Coordinator(onCapture: onCapture, onCancel: onCancel) }

    /// Required by UIViewControllerRepresentable. The picker has no state to update.
    func updateUIViewController(_ controller: UIImagePickerController, context: Context) {}

    /// Creates an image picker using the camera.
    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.delegate = context.coordinator
        return picker
    }

    /// Image picker delegate that calls onCapture or onCancel.
    final class Coordinator: NSObject, UINavigationControllerDelegate,
        UIImagePickerControllerDelegate
    {
        let onCapture: (UIImage) -> Void
        let onCancel: () -> Void

        /// Creates a delegate with the result callbacks.
        init(onCapture: @escaping (UIImage) -> Void, onCancel: @escaping () -> Void) {
            self.onCapture = onCapture
            self.onCancel = onCancel
        }

        /// Calls onCancel when the user closes the camera.
        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) { onCancel() }

        /// Calls onCapture with the photo taken.
        func imagePickerController(
            _ picker: UIImagePickerController,
            didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]
        ) {
            if let photo = info[.originalImage] as? UIImage { onCapture(photo) } else { onCancel() }
        }
    }
}
