import CoreLocation
import Foundation
import Observation
import UIKit

/// Collects this iPhone's location with Core Location, records trips, queues encrypted fixes and
/// uploads them in batches. Also tracks the diagnostics shown in Settings.
@MainActor
@Observable
final class LocationTracker: NSObject, CLLocationManagerDelegate {
    var lastFix: LocalLocation?
    var queuedCount = 0
    var trackingEnabled = false
    var locationPermission: CLAuthorizationStatus = .notDetermined
    var preciseLocationAllowed = false
    var lastGPSReceivedAt: Date?
    var lastGPSUploadedAt: Date?
    var gpsDeliveryError = ""
    var tripDeliveryError = ""
    var lastTripUploadedAt: Date?
    var gpsPowerMode = "Active · precise"

    /// Fixes are held this long, then uploaded together.
    let batchWindowSeconds: Double = 15
    var gpsFixesLastHour = 0
    var gpsUploadsLastHour = 0
    var drainPercentPerHour: Double?

    var tripRecordingStatus: String {
        recorder.currentId == nil ? "Stationary / idle" : "Recording a trip"
    }

    var pendingTripSummaries: Int { recorder.pending.count }

    /// Returns true when signed in, the device is trusted and sharing is on.
    @ObservationIgnored var canShare: @MainActor () -> Bool = { false }

    /// Returns the signed-in account's ID.
    @ObservationIgnored var accountId: @MainActor () -> String? = { nil }

    /// Returns the saved places, for trip detection.
    @ObservationIgnored var places: @MainActor () -> [SavedPlace] = { [] }

    /// Called when a location or trip upload fails.
    @ObservationIgnored var onSyncProblem: @MainActor () -> Void = {}

    /// Called with a message to show the user.
    @ObservationIgnored var onMessage: @MainActor (String) -> Void = { _ in }

    /// Called after each upload, possibly in the background. Used to poll for Find My Phone.
    @ObservationIgnored var afterDelivery: @MainActor () async -> Void = {}

    /// Called when the location permission changes.
    @ObservationIgnored var onPermissionsChanged: @MainActor () -> Void = {}
    private let manager = CLLocationManager()
    private let queue = EncryptedLocationQueue()
    private let recorder = TripRecorder()
    private let household: HouseholdService
    private let settings: AppSettings
    private let stationaryCheckInsEnabled = true
    @ObservationIgnored private var draining = false
    @ObservationIgnored private var deliveryRunning = false
    @ObservationIgnored private var lastQueuedAt: Date = .distantPast
    @ObservationIgnored private var lastQueuedLocation: CLLocation?
    @ObservationIgnored private var lastBatchAttempt: Date = .distantPast
    @ObservationIgnored private var scheduledBatch: Task<Void, Never>?
    @ObservationIgnored private var lowPowerGPS = false
    @ObservationIgnored private var preciseWakeUntil: Date = .distantPast
    @ObservationIgnored private var gpsFixTimes: [Date] = []
    @ObservationIgnored private var gpsSendTimes: [Date] = []
    @ObservationIgnored private var dischargeSamples: [(Date, Int)] = []
    @ObservationIgnored private var parkedCheckIn: Task<Void, Never>?

    /// When set, the next fix is uploaded immediately even while parked. Set when the app opens.
    @ObservationIgnored private var checkInNow = false

    /// Configures Core Location and restores queued fixes.
    init(household: HouseholdService, settings: AppSettings) {
        self.household = household
        self.settings = settings
        super.init()
        UIDevice.current.isBatteryMonitoringEnabled = true
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyNearestTenMeters
        manager.distanceFilter = StationaryCheckInPolicy.distanceFilter(
            enabled: stationaryCheckInsEnabled)
        // Automatic pausing stays off so updates continue with the screen off; distanceFilter
        // limits them instead.
        manager.pausesLocationUpdatesAutomatically = false
        manager.activityType = .otherNavigation
        locationPermission = manager.authorizationStatus
        preciseLocationAllowed = manager.accuracyAuthorization == .fullAccuracy
        lastFix = queue.latest
        queuedCount = queue.count
        lastGPSReceivedAt = settings.lastGPSReceivedAt
        lastGPSUploadedAt = settings.lastGPSUploadedAt
        trackingEnabled = settings.trackingEnabled
        if trackingEnabled && locationPermission == .authorizedAlways {
            manager.allowsBackgroundLocationUpdates = true
            manager.startMonitoringSignificantLocationChanges()
        }
    }

    /// Requests When In Use location permission.
    func requestForegroundLocation() { manager.requestWhenInUseAuthorization() }

    /// Requests Always location permission.
    func requestBackgroundLocation() { manager.requestAlwaysAuthorization() }

    /// Requests Always permission once, after the first sign-in with When In Use permission.
    func askForAlwaysAfterSignIn() {
        guard locationPermission == .authorizedWhenInUse, !settings.askedForAlwaysLocation
        else { return }
        settings.askedForAlwaysLocation = true
        requestBackgroundLocation()
    }

    /// Requests location permission once, on the first launch.
    func askForLocationOnFirstLaunch() {
        guard locationPermission == .notDetermined, !settings.askedForLocation else { return }
        settings.askedForLocation = true
        requestForegroundLocation()
    }

    /// Enables or disables background collection. Returns false without changing anything if
    /// enabling needs Always permission first.
    func setTracking(_ enabled: Bool) -> Bool {
        guard !enabled || locationPermission == .authorizedAlways else { return false }
        trackingEnabled = enabled
        settings.trackingEnabled = enabled
        updateMonitoring()
        if !enabled {
            queue.clear()
            queuedCount = 0
        }
        return true
    }

    /// Stops collecting and deletes everything not yet uploaded.
    func signOut() {
        stopMonitoring()
        trackingEnabled = false
        settings.trackingEnabled = false
        queue.clear()
        recorder.discard()
    }

    /// Stops collecting after sharing is disabled and deletes queued fixes.
    func pauseSharing() {
        queue.clear()
        queuedCount = 0
        recorder.discard()
        stopMonitoring()
    }

    /// Deletes queued fixes.
    func clearLocalLocations() {
        queue.clear()
        recorder.discard()
        lastFix = nil
        queuedCount = 0
    }

    /// Uploads a fresh fix when the app comes to the foreground and completes any trip that ended
    /// while the app was suspended.
    func appBecameActive() {
        checkInSoon()
        finalizeStationaryTripIfNeeded()
    }

    /// Uploads the next fix straight away, e.g. so a member who just joined sees this phone.
    func checkInSoon() {
        checkInNow = true
        if lowPowerGPS { manager.distanceFilter = kCLDistanceFilterNone }
    }

    /// Stops all location updates.
    func stopMonitoring() {
        manager.stopUpdatingLocation()
        manager.stopMonitoringSignificantLocationChanges()
        manager.allowsBackgroundLocationUpdates = false
    }

    /// Starts or stops location updates to match the tracking setting, permission and sharing
    /// state.
    func updateMonitoring() {
        guard trackingEnabled, locationPermission == .authorizedAlways else {
            stopMonitoring()
            return
        }
        // Significant-change monitoring lets iOS relaunch the app after it exits, so keep it on
        // even before sign-in is restored.
        manager.startMonitoringSignificantLocationChanges()
        manager.distanceFilter = StationaryCheckInPolicy.distanceFilter(enabled: true)
        guard canShare(), household.identity != nil else {
            manager.stopUpdatingLocation()
            return
        }
        manager.allowsBackgroundLocationUpdates = true
        manager.showsBackgroundLocationIndicator = true
        manager.startUpdatingLocation()
        flushDelivery()
    }

    /// Completes the current trip if the phone has been stationary long enough. Returns true if a
    /// trip was completed.
    @discardableResult
    func finalizeStationaryTripIfNeeded() -> Bool {
        guard let accountId = accountId(), let device = household.identity else { return false }
        let wasActive = recorder.currentId != nil
        recorder.completeIfStationaryLongEnough(
            now: Date(), accountId: accountId, deviceId: device.id)
        if wasActive && recorder.currentId == nil {
            updateGPSPowerMode()
            return true
        }
        return false
    }

    /// Uploads queued fixes and trips inside a background task so iOS gives it time to finish.
    func flushDelivery() {
        guard !deliveryRunning else { return }
        deliveryRunning = true
        var taskID: UIBackgroundTaskIdentifier = .invalid
        taskID = UIApplication.shared.beginBackgroundTask(
            withName: "NaraHem GPS upload",
            expirationHandler: { [weak self] in
                Task { @MainActor [weak self] in
                    if taskID != .invalid {
                        UIApplication.shared.endBackgroundTask(taskID)
                        taskID = .invalid
                    }
                    self?.deliveryRunning = false
                }
            })
        Task {
            await drainPending()
            await afterDelivery()
            if taskID != .invalid {
                UIApplication.shared.endBackgroundTask(taskID)
                taskID = .invalid
            }
            deliveryRunning = false
        }
    }

    /// Uploads queued fixes in batches, then pending trip summaries, until done or an upload fails.
    func drainPending() async {
        guard !draining, canShare() else { return }
        finalizeStationaryTripIfNeeded()
        draining = true
        defer { draining = false }
        let pending = queue.pending(limit: 8)
        var uploadedBatch = false
        if pending.count > 1 {
            do {
                try await household.publishLocations(pending)
                for fix in pending { queue.acknowledge(fix.id) }
                queuedCount = queue.count
                lastGPSUploadedAt = Date()
                noteUpload(pending.count)
                uploadedBatch = true
            } catch {
            }
        }
        for record in (uploadedBatch ? [] : pending) {
            if !canShare() { break }
            do {
                try await household.publishLocation(record)
                queue.acknowledge(record.id)
                queuedCount = queue.count
                lastGPSUploadedAt = Date()
                noteUpload()
                settings.lastGPSUploadedAt = Date()
                gpsDeliveryError = ""
            } catch NaraHemProtocolError.http(let status, let reason)
                where status == 422 && reason.contains("retention window")
            {
                queue.acknowledge(record.id)
                queuedCount = queue.count
            } catch {
                onSyncProblem()
                gpsDeliveryError = "Upload pending: \(error.localizedDescription)"
                break
            }
        }
        for summary in recorder.pending.prefix(3) {
            if !canShare() { break }
            do {
                try await household.publishTrip(summary)
                recorder.acknowledge(summary.id)
                lastTripUploadedAt = Date()
                tripDeliveryError = ""
            } catch {
                // Never drop a trip that wasn't sent.
                onSyncProblem()
                tripDeliveryError = "Trip summary pending: \(error.localizedDescription)"
                break
            }
        }
    }

    /// Updates the permission state and location monitoring.
    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        locationPermission = manager.authorizationStatus
        preciseLocationAllowed = manager.accuracyAuthorization == .fullAccuracy
        updateMonitoring()
        onPermissionsChanged()
    }

    /// Handles new fixes: updates diagnostics, the map position and trip recording, queues fixes
    /// and schedules an upload.
    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        // Only the time is stored here. Coordinates only go into the encrypted queue.
        lastGPSReceivedAt = Date()
        settings.lastGPSReceivedAt = Date()
        if lowPowerGPS && manager.distanceFilter != StationaryCheckInPolicy.parkedDistanceFilter {
            manager.distanceFilter = StationaryCheckInPolicy.parkedDistanceFilter
        }
        guard trackingEnabled && canShare() && household.identity != nil else { return }
        noteGPS(locations)
        wakeIfMoving(locations)
        showNewest(locations)
        for location in locations { record(location) }
        queuedCount = queue.count
        updateGPSPowerMode()
        scheduleDelivery()
    }

    /// In low-power mode, switches to precise GPS for two minutes if a fix shows speed or a
    /// credible jump from the parked position. This doesn't start a trip by itself.
    private func wakeIfMoving(_ locations: [CLLocation]) {
        guard lowPowerGPS,
            locations.contains(where: {
                ($0.speed.isFinite && $0.speed >= 0.8 && $0.speed <= 65
                    && $0.horizontalAccuracy >= 0 && $0.horizontalAccuracy <= 200)
                    || recorder.shouldWakeForDisplacement($0)
            })
        else { return }
        preciseWakeUntil = Date().addingTimeInterval(120)
        updateGPSPowerMode()
    }

    /// Updates the local map position with the newest accurate fix. This never triggers an upload.
    private func showNewest(_ locations: [CLLocation]) {
        if let newest = locations.filter({
            $0.horizontalAccuracy >= 0 && $0.horizontalAccuracy <= 75
                && $0.timestamp.timeIntervalSinceNow >= -45
                && $0.timestamp.timeIntervalSinceNow <= 10
                && CLLocationCoordinate2DIsValid($0.coordinate)
        }).max(by: { $0.timestamp < $1.timestamp }),
            lastFix == nil || newest.timestamp > lastFix!.capturedAt
        {
            lastFix = LocalLocation(newest)
        }
    }

    /// Passes a fix to the trip recorder and queues it if the sampling interval allows.
    private func record(_ location: CLLocation) {
        let stationary = location.speed >= 0 && location.speed < 0.7
        if stationaryCheckInsEnabled && recorder.currentId == nil && stationary
            && !StationaryCheckInPolicy.isUsable(location)
        {
            return
        }
        if let accountId = accountId(), let device = household.identity {
            recorder.observe(location, accountId: accountId, deviceId: device.id, places: places())
            if let tripId = recorder.currentId {
                for startingFix in recorder.takeConfirmedStartFixes() {
                    queue.append(startingFix, tripId: tripId, batteryPct: nil, charging: nil)
                }
            }
        }
        let seconds = StationaryCheckInPolicy.minimumSampleInterval(
            activeTrip: recorder.currentId != nil,
            stationaryCheckIns: stationaryCheckInsEnabled, speed: location.speed)
        guard
            checkInNow || isTurn(location)
                || location.timestamp.timeIntervalSince(lastQueuedAt) >= seconds
        else { return }
        let battery = UIDevice.current.batteryLevel
        let batteryPct: Int? = battery >= 0 ? Int(battery * 100) : nil
        let state = UIDevice.current.batteryState
        let charging: Bool? = state == .unknown ? nil : (state == .charging || state == .full)
        checkInNow = false
        lastQueuedAt = location.timestamp
        lastQueuedLocation = location
        queue.append(
            location, tripId: recorder.currentId,
            batteryPct: batteryPct, charging: charging)
    }

    /// Returns true for a heading change of 35 degrees or more since the last queued fix, using
    /// only accurate course readings and real movement.
    private func isTurn(_ location: CLLocation) -> Bool {
        guard let previous = lastQueuedLocation,
            location.speed >= 2.24, location.course >= 0,
            previous.course >= 0, location.courseAccuracy >= 0,
            location.courseAccuracy <= 20,
            previous.courseAccuracy >= 0, previous.courseAccuracy <= 20,
            location.distance(from: previous) >= 18,
            location.timestamp.timeIntervalSince(previous.timestamp) >= 2
        else { return false }
        let delta = abs(location.course - previous.course).truncatingRemainder(dividingBy: 360)
        return min(delta, 360 - delta) >= 35
    }

    /// Uploads now if the queue is large or the batch window has passed; otherwise schedules an
    /// upload at the end of the window.
    private func scheduleDelivery() {
        if queue.count >= 8 || Date().timeIntervalSince(lastBatchAttempt) >= batchWindowSeconds
            || !recorder.pending.isEmpty
        {
            scheduledBatch?.cancel()
            scheduledBatch = nil
            lastBatchAttempt = Date()
            flushDelivery()
        } else if scheduledBatch == nil {
            scheduledBatch = Task { @MainActor [weak self] in
                try? await Task.sleep(for: .seconds(self?.batchWindowSeconds ?? 15))
                guard let self else { return }
                self.scheduledBatch = nil
                self.lastBatchAttempt = Date()
                self.flushDelivery()
            }
        }
    }

    /// Shows a Core Location error.
    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        gpsDeliveryError = "Core Location: \(error.localizedDescription)"
        onMessage("iPhone GPS unavailable. Check Location Services and background permission.")
    }

    /// Updates the fixes-per-hour count and the battery drain estimate.
    private func noteGPS(_ locations: [CLLocation]) {
        let now = Date()
        gpsFixTimes.append(
            contentsOf: locations.map(\.timestamp).filter {
                abs($0.timeIntervalSince(now)) <= 120
            })
        gpsFixTimes.removeAll { now.timeIntervalSince($0) > 3_600 }
        gpsFixesLastHour = gpsFixTimes.count
        if UIDevice.current.batteryState == .unplugged,
            UIDevice.current.batteryLevel >= 0
        {
            dischargeSamples.append((now, Int(UIDevice.current.batteryLevel * 100)))
            dischargeSamples.removeAll { now.timeIntervalSince($0.0) > 3_600 }
            if let first = dischargeSamples.first,
                now.timeIntervalSince(first.0) >= 900
            {
                drainPercentPerHour =
                    max(0, Double(first.1 - Int(UIDevice.current.batteryLevel * 100)))
                    * 3_600 / now.timeIntervalSince(first.0)
            }
        } else {
            dischargeSamples.removeAll()
            drainPercentPerHour = nil
        }
    }

    /// Updates the uploads-per-hour count.
    private func noteUpload(_ count: Int = 1) {
        let now = Date()
        gpsSendTimes.append(contentsOf: Array(repeating: now, count: count))
        gpsSendTimes.removeAll { now.timeIntervalSince($0) > 3_600 }
        gpsUploadsLastHour = gpsSendTimes.count
    }

    /// Switches between precise GPS and low-power parked mode.
    private func updateGPSPowerMode() {
        let savePower = recorder.lowPowerEligible && Date() >= preciseWakeUntil
        guard savePower != lowPowerGPS else { return }
        lowPowerGPS = savePower
        gpsPowerMode = savePower ? "Stationary · power saving" : "Active · precise"
        manager.desiredAccuracy =
            savePower ? kCLLocationAccuracyHundredMeters : kCLLocationAccuracyNearestTenMeters
        manager.distanceFilter =
            savePower
            ? StationaryCheckInPolicy.parkedDistanceFilter
            : StationaryCheckInPolicy.distanceFilter(enabled: true)
        parkedCheckIn?.cancel()
        parkedCheckIn = nil
        if savePower {
            parkedCheckIn = Task { @MainActor [weak self] in
                while !Task.isCancelled {
                    try? await Task.sleep(
                        for: .seconds(StationaryCheckInPolicy.parkedCheckInSeconds))
                    guard !Task.isCancelled, let self, self.lowPowerGPS else { return }
                    self.manager.distanceFilter = kCLDistanceFilterNone
                }
            }
        }
        // Keep standard updates running: significant-change alone can miss a short walk.
        manager.pausesLocationUpdatesAutomatically = false
    }
}
