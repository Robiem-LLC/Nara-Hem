package com.robiem.narahem

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.annotation.VisibleForTesting
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.robiem.narahem.data.account.initialServer
import com.robiem.narahem.data.account.serverOrigin
import com.robiem.narahem.findphone.FindPhonePlayer
import com.robiem.narahem.notifications.NaraHemNotificationChannels
import com.robiem.narahem.ui.AppState
import com.robiem.narahem.ui.AppViewModel
import com.robiem.narahem.ui.PhoneSettings
import com.robiem.narahem.ui.components.AdaptiveLayout
import com.robiem.narahem.ui.components.AdaptiveNavigation
import com.robiem.narahem.ui.components.AudienceDialog
import com.robiem.narahem.ui.components.BrandHeader
import com.robiem.narahem.ui.components.InviteServerDialog
import com.robiem.narahem.ui.components.LocationConsentDialog
import com.robiem.narahem.ui.joinedMessage
import com.robiem.narahem.ui.map.MapScreenState
import com.robiem.narahem.ui.map.MapTab
import com.robiem.narahem.ui.map.MapViewModel
import com.robiem.narahem.ui.places.PlaceEditorState
import com.robiem.narahem.ui.places.PlacesTab
import com.robiem.narahem.ui.places.PlacesViewModel
import com.robiem.narahem.ui.settings.DevicePermissions
import com.robiem.narahem.ui.settings.ProfilePhotos
import com.robiem.narahem.ui.settings.SettingsForm
import com.robiem.narahem.ui.settings.SettingsTab
import com.robiem.narahem.ui.settings.SettingsViewModel
import com.robiem.narahem.ui.signin.SignInForm
import com.robiem.narahem.ui.signin.SignInScreen
import com.robiem.narahem.ui.signin.SignInViewModel
import com.robiem.narahem.ui.theme.NaraHemTheme
import com.robiem.narahem.ui.theme.appBackground
import com.robiem.narahem.ui.trips.TripsTab
import com.robiem.narahem.ui.trips.TripsViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Formats the UTC build timestamp in the phone's time zone for the About section. Returns the input
 * unchanged if it can't be parsed.
 */
internal fun formatNaraHemBuild(utc: String): String = runCatching {
    java.time.Instant.parse(utc).atZone(java.time.ZoneId.systemDefault())
        .format(java.time.format.DateTimeFormatter.ofPattern("MMM d, yyyy · h:mm a"))
}.getOrDefault(utc)

/**
 * The app's single activity. Hosts the Compose UI and handles Android permission requests and
 * activity result launchers.
 */
class MainActivity : ComponentActivity() {
    /** Source of repositories and view model factories; replaced with fakes in UI tests. */
    private lateinit var container: AppContainer
    private val model: AppViewModel by viewModels { container.appViewModelFactory }
    private val screens get() = container.screenViewModelFactory(model.session)
    private val signInModel: SignInViewModel by viewModels { screens }
    private val mapModel: MapViewModel by viewModels { screens }
    private val tripsModel: TripsViewModel by viewModels { screens }
    private val placesModel: PlacesViewModel by viewModels { screens }
    private val settingsModel: SettingsViewModel by viewModels { screens }

    /**
     * Whether the app may override Do Not Disturb for the Find My Phone alarm. Refreshed in
     * onResume.
     */
    internal var finderPolicyAccess by mutableStateOf(false)

    /** Incremented in onResume so composables re-read the location permission. */
    internal var locationSettingsRefresh by mutableIntStateOf(0)

    /**
     * Stops a ringing Find My Phone alarm when a volume key is pressed. Android only delivers these
     * keys to the foreground activity; the alarm notification's Stop action covers the lock screen.
     */
    override fun onKeyDown(keyCode: Int, event: android.view.KeyEvent?): Boolean {
        if (FindPhonePlayer.isRinging &&
            (
                keyCode == android.view.KeyEvent.KEYCODE_VOLUME_UP ||
                    keyCode == android.view.KeyEvent.KEYCODE_VOLUME_DOWN
                )
        ) {
            model.stopFindPhoneAlarm()
            return true
        }
        return super.onKeyDown(keyCode, event)
    }

    /**
     * Re-checks Do Not Disturb access and location permission after returning from system settings,
     * and reports the permission state to the server.
     */
    override fun onResume() {
        super.onResume()
        finderPolicyAccess =
            getSystemService(
                android.app.NotificationManager::class.java
            ).isNotificationPolicyAccessGranted
        locationSettingsRefresh++
        model.reportDevicePermissions()
    }

    /** Explains why Do Not Disturb access is needed, then opens the system screen to grant it. */
    internal fun explainFinderAccess() {
        val granted = getSystemService(
            android.app.NotificationManager::class.java
        ).isNotificationPolicyAccessGranted
        android.app.AlertDialog.Builder(this)
            .setTitle(if (granted) "Revoke Find my phone access" else "Enable Find my phone access")
            .setMessage(
                if (granted) {
                    "On the next screen, select Nära Hem if a list appears, then turn off " +
                        "Allow Do Not Disturb access. To prevent all remote ringing, also " +
                        "turn off Allow remote alarm in Nära Hem."
                } else {
                    "On the next screen, select Nära Hem if a list appears, then turn on " +
                        "Allow Do Not Disturb access and confirm Allow. Return to Nära Hem " +
                        "afterward. Your Do Not Disturb mode must also allow alarms; access " +
                        "alone does not override every DND mode."
                }
            )
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Open settings") { _, _ ->
                val detail =
                    Intent(
                        "android.settings.NOTIFICATION_POLICY_ACCESS_DETAIL_SETTINGS",
                        Uri.parse("package:$packageName")
                    )
                try {
                    startActivity(detail)
                } catch (_: RuntimeException) {
                    try {
                        startActivity(Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS))
                    } catch (_: RuntimeException) {
                        android.widget.Toast.makeText(
                            this,
                            "Open Android Settings and search for Do Not Disturb access, " +
                                "then select Nära Hem.",
                            android.widget.Toast.LENGTH_LONG
                        ).show()
                    }
                }
            }.show()
    }

    /** Explains how to choose "Allow all the time", then opens the app's system settings page. */
    internal fun explainBackgroundLocation() {
        android.app.AlertDialog.Builder(this)
            .setTitle("Allow background location")
            .setMessage(
                "On the next screen select Permissions → Location → Allow all the time, then " +
                    "return to Nära Hem. Android doesn't provide a reliable direct shortcut " +
                    "on every device."
            )
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Open app settings") { _, _ ->
                try {
                    startActivity(
                        Intent(
                            Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                            Uri.parse("package:$packageName")
                        )
                    )
                } catch (_: RuntimeException) {
                    android.widget.Toast.makeText(
                        this,
                        "Open Android Settings → Apps → Nära Hem → Permissions → Location.",
                        android.widget.Toast.LENGTH_LONG
                    ).show()
                }
            }.show()
    }

    /** Returns true if coarse or fine location permission is granted. */
    private fun hasLocation(): Boolean {
        locationSettingsRefresh
        return checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED ||
            checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED
    }

    /** Collects the permission states shown on the Settings screen. */
    private fun devicePermissions(): DevicePermissions {
        val location = hasLocation()
        val background = Build.VERSION.SDK_INT < 29 ||
            checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION) ==
            PackageManager.PERMISSION_GRANTED
        return DevicePermissions(location, background, finderPolicyAccess)
    }

    /**
     * Reads an invitation link from the launching intent, builds the container and sets the Compose
     * content.
     */
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        NaraHemNotificationChannels.ensure(this)
        enableEdgeToEdge()
        // Invitation links are untrusted: they only prefill the form and never approve a device.
        val invitation = intent?.data?.takeIf { it.scheme == "narahem" && it.host == "join" }
        val invitedServer = invitation?.getQueryParameter("server")?.takeIf {
            runCatching { serverOrigin(it) }.isSuccess
        }
        val invitedToken = invitation?.getQueryParameter("token")?.takeIf {
            it.isNotBlank() && it.length <= 256
        }
        container = testContainer ?: PhoneAppContainer(applicationContext)
        setContent { NaraHemTheme { App(invitedServer, invitedToken) } }
    }

    /** Returns true on Android 13 and later when notification permission has not been granted. */
    private fun needsNotificationPermission() = Build.VERSION.SDK_INT >= 33 &&
        checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) !=
        PackageManager.PERMISSION_GRANTED

    /**
     * Root composable. Holds state that must survive rotation and sign-in restoration (forms,
     * selected tab, launchers) and shows the restoring screen, sign-in screen or signed-in app.
     */
    @Composable
    private fun App(invitedServer: String?, invitedToken: String?) {
        val state by model.state.collectAsStateWithLifecycle()
        val phoneSettings by model.phoneSettings.collectAsStateWithLifecycle()
        val startingServer = remember { initialServer(model.savedServer, invitedServer) }
        val signInForm = rememberSaveable(saver = SignInForm.Saver) {
            SignInForm(startingServer.server, invitedToken.orEmpty())
        }
        var pendingInviteServer by rememberSaveable {
            mutableStateOf(startingServer.unconfirmedInvite)
        }
        val settingsForm = rememberSaveable(saver = SettingsForm.Saver) { SettingsForm() }
        var tab by rememberSaveable { mutableStateOf("map") }
        val mapScreen = rememberSaveable(saver = MapScreenState.Saver) { MapScreenState() }
        var selectedMemberId by rememberSaveable { mutableStateOf<String?>(null) }
        var consentDialog by remember { mutableStateOf(false) }
        val placeEditor = remember { PlaceEditorState() }
        val notificationLauncher =
            rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {}
        val permissionLauncher =
            rememberLauncherForActivityResult(
                ActivityResultContracts.RequestMultiplePermissions()
            ) { grants ->
                if (grants[Manifest.permission.ACCESS_COARSE_LOCATION] == true ||
                    grants[Manifest.permission.ACCESS_FINE_LOCATION] == true
                ) {
                    mapModel.locate()
                    if (state.deviceStatus == "ready" && state.sharing) {
                        model.syncBackgroundSharing(hasLocation = true)
                    }
                    if (needsNotificationPermission()) {
                        notificationLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
                    }
                } else {
                    model.permissionDenied()
                }
            }
        val askLocation = {
            permissionLauncher.launch(
                arrayOf(
                    Manifest.permission.ACCESS_COARSE_LOCATION,
                    Manifest.permission.ACCESS_FINE_LOCATION
                )
            )
        }
        val galleryLauncher = rememberGalleryLauncher()
        val cameraLauncher = rememberCameraLauncher()
        LaunchedEffect(state.message, state.error) {
            if (state.message.isNotBlank() && !state.error) {
                delay(4500)
                model.dismissMessage(state.message)
            }
        }
        LaunchedEffect(Unit) {
            signInModel.restoreSession(signInForm.server)
            if (invitedServer != null && invitedToken != null && pendingInviteServer == null) {
                signInModel.onboarding("enroll")
            }
            if (!hasLocation() && model.takeFirstLaunchLocationPrompt()) askLocation()
        }
        AccountEffects(
            state = state,
            loadMap = phoneSettings.mapConsent,
            signInForm = signInForm,
            settingsForm = settingsForm,
            askLocation = askLocation,
            askNotifications = {
                notificationLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            },
            onAskConsent = { consentDialog = true },
            onSignedOut = { tab = "map" },
            mapShowing = { tab == "map" }
        )
        BackHandler(enabled = state.account != null && tab != "map") { tab = "map" }
        BackHandler(enabled = state.account != null && tab == "places" && placeEditor.open) {
            placeEditor.close()
        }
        pendingInviteServer?.let { invite ->
            InviteServerDialog(
                invite = invite,
                current = signInForm.server,
                onSwitch = {
                    signInForm.server = invite
                    pendingInviteServer = null
                    if (invitedToken != null) signInModel.onboarding("enroll")
                },
                onKeep = { pendingInviteServer = null }
            )
        }
        if (consentDialog && state.account != null) {
            LocationConsentDialog(
                onAccept = {
                    model.acceptMapConsent()
                    consentDialog = false
                    askLocation()
                },
                onDismiss = { consentDialog = false }
            )
        }
        if (settingsForm.audienceOpen && state.account != null && state.audienceLoaded &&
            !state.syncProblem && state.audienceChoices.any { it.id != state.account!!.id }
        ) {
            AudienceDialog(state, settingsForm, onSave = settingsModel::setSharingAudience)
        }
        Surface(
            Modifier.fillMaxSize().appBackground(),
            color = Color.Transparent,
            contentColor = MaterialTheme.colorScheme.onBackground
        ) {
            if (state.restoring) {
                RestoringScreen()
            } else if (state.account == null) {
                SignInScreen(state, signInForm, signInModel)
            } else {
                SignedIn(
                    state = state,
                    phoneSettings = phoneSettings,
                    tab = tab,
                    onTab = { tab = it },
                    mapScreen = mapScreen,
                    selectedMemberId = selectedMemberId,
                    onSelectMember = { selectedMemberId = it },
                    placeEditor = placeEditor,
                    settingsForm = settingsForm,
                    signInForm = signInForm,
                    askLocation = askLocation,
                    onAskConsent = { consentDialog = true },
                    onChoosePhoto = { galleryLauncher.launch("image/*") },
                    onTakePhoto = { cameraLauncher.launch(null) }
                )
            }
        }
    }

    /**
     * Creates a launcher that picks an image from the gallery and saves it as the profile photo.
     */
    @Composable
    private fun rememberGalleryLauncher(): ActivityResultLauncher<String> {
        val scope = rememberCoroutineScope()
        return rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
            if (uri != null) {
                scope.launch {
                    try {
                        val photo = withContext(Dispatchers.IO) {
                            ProfilePhotos.fromGallery(applicationContext, uri)
                        }
                        settingsModel.saveProfilePhoto(photo)
                    } catch (failure: Exception) {
                        settingsModel.photoError(failure.message ?: "Unable to open that photo.")
                    }
                }
            }
        }
    }

    /** Creates a launcher that takes a camera photo and saves it as the profile photo. */
    @Composable
    private fun rememberCameraLauncher(): ActivityResultLauncher<Void?> =
        rememberLauncherForActivityResult(
            ActivityResultContracts.TakePicturePreview()
        ) { bitmap: Bitmap? ->
            if (bitmap != null) {
                try {
                    settingsModel.saveProfilePhoto(ProfilePhotos.encode(bitmap))
                } catch (failure: Exception) {
                    settingsModel.photoError(failure.message ?: "Unable to use that camera photo.")
                }
            }
        }

    /**
     * Runs the side effects of signing in or out: clears forms, asks for permissions, prepares the
     * device, starts refreshes and syncs background sharing.
     */
    @Composable
    private fun AccountEffects(
        state: AppState,
        loadMap: Boolean,
        signInForm: SignInForm,
        settingsForm: SettingsForm,
        askLocation: () -> Unit,
        askNotifications: () -> Unit,
        onAskConsent: () -> Unit,
        onSignedOut: () -> Unit,
        mapShowing: () -> Boolean
    ) {
        var deviceAttemptedFor by remember { mutableStateOf("") }
        LaunchedEffect(state.account?.id) {
            settingsForm.username = state.account?.name.orEmpty()
        }
        LaunchedEffect(state.account) {
            signInForm.password = ""
            if (state.account != null) signInForm.confirmation = ""
            signInForm.showPassword = false
            if (state.account != null) {
                signInForm.server = serverOrigin(signInForm.server).toString().removeSuffix("/")
                if (!loadMap) {
                    onAskConsent()
                } else if (!hasLocation()) {
                    askLocation()
                } else if (needsNotificationPermission()) {
                    askNotifications()
                }
            } else {
                // Don't stop the location service here: an activity restart passes through this
                // while the session is still being restored.
                onSignedOut()
                signInForm.firstStep = true
                deviceAttemptedFor = ""
            }
        }
        // The account appears while sign-in is still busy. Wait until it finishes before preparing
        // the device, or HouseholdSession.work() skips it.
        LaunchedEffect(state.account?.id, state.busy) {
            val account = state.account
            if (account != null && !state.busy && deviceAttemptedFor != account.id) {
                deviceAttemptedFor = account.id
                model.prepareDevice(signInForm.server)
            }
        }
        LaunchedEffect(state.account?.id) {
            if (state.account != null) model.refreshHouseholdWhileOpen(mapShowing)
        }
        LaunchedEffect(state.joinedMembers) {
            if (state.joinedMembers.isNotEmpty()) {
                Toast.makeText(
                    this@MainActivity,
                    joinedMessage(state.joinedMembers),
                    Toast.LENGTH_LONG
                ).show()
                model.joinedMembersShown()
            }
        }
        LaunchedEffect(loadMap, state.deviceStatus, state.sharing, state.account) {
            model.syncBackgroundSharing(hasLocation())
        }
        LaunchedEffect(state.account?.id, loadMap) {
            if (state.account != null && loadMap && hasLocation()) mapModel.centerMapOnPhone()
        }
    }

    /** Signed-in layout: bottom navigation (or a side rail in landscape) and the selected tab. */
    @Composable
    private fun SignedIn(
        state: AppState,
        phoneSettings: PhoneSettings,
        tab: String,
        onTab: (String) -> Unit,
        mapScreen: MapScreenState,
        selectedMemberId: String?,
        onSelectMember: (String?) -> Unit,
        placeEditor: PlaceEditorState,
        settingsForm: SettingsForm,
        signInForm: SignInForm,
        askLocation: () -> Unit,
        onAskConsent: () -> Unit,
        onChoosePhoto: () -> Unit,
        onTakePhoto: () -> Unit
    ) {
        val configuration = LocalConfiguration.current
        val nearbyAddresses by mapModel.nearbyAddresses.collectAsStateWithLifecycle()
        val landscape = AdaptiveLayout.landscape(
            configuration.screenWidthDp,
            configuration.screenHeightDp
        )
        val selectTab: (String) -> Unit = { selected ->
            onTab(selected)
            placeEditor.close()
            if (selected == "trips") {
                val member = selectedMemberId ?: state.people.firstOrNull()?.id
                if (member != null) {
                    onSelectMember(member)
                    tripsModel.loadMemberTrips(member)
                }
            }
        }
        // Until this phone is set up, only its setup steps are shown, as on iPhone.
        val ready = state.deviceStatus == "ready"
        Scaffold(
            modifier = Modifier.fillMaxSize().safeDrawingPadding(),
            containerColor = Color.Transparent,
            bottomBar = {
                if (ready && !landscape) AdaptiveNavigation(tab, rail = false, onSelect = selectTab)
            }
        ) { padding ->
            Row(Modifier.fillMaxSize().padding(padding)) {
                if (ready && landscape) AdaptiveNavigation(tab, rail = true, onSelect = selectTab)
                Box(Modifier.weight(1f).fillMaxHeight()) {
                    when (if (ready) tab else "settings") {
                        "map" -> MapTab(
                            state = state,
                            screen = mapScreen,
                            loadMap = phoneSettings.mapConsent,
                            nearbyAddresses = nearbyAddresses,
                            selectedMemberId = selectedMemberId,
                            landscape = landscape,
                            sidePanel = AdaptiveLayout.sidePanelWidthDp(
                                configuration.screenWidthDp
                            ).dp,
                            model = mapModel,
                            onSelectMember = onSelectMember,
                            onAskConsent = onAskConsent,
                            onOpenTab = onTab,
                            onViewTrips = { member ->
                                tripsModel.loadMemberTrips(member)
                                onTab("trips")
                            },
                            onClearTrips = tripsModel::clearMemberTrips,
                            hasLocation = ::hasLocation
                        )

                        "trips" -> TripsTab(
                            state = state,
                            selectedMemberId = selectedMemberId,
                            onSelectMember = onSelectMember,
                            loadMap = phoneSettings.mapConsent,
                            addressLookup = phoneSettings.addressLookup,
                            model = tripsModel,
                            onSavePlace = { name, lat, lon ->
                                placesModel.savePlace(name, lat, lon, 100.0)
                            }
                        )

                        "places" -> PlacesTab(
                            state = state,
                            editor = placeEditor,
                            lastCamera = phoneSettings.mapCamera,
                            model = placesModel
                        )

                        else -> SettingsTab(
                            state = state,
                            form = settingsForm,
                            server = signInForm.server,
                            email = signInForm.email,
                            permissions = devicePermissions(),
                            addressLookup = phoneSettings.addressLookup,
                            model = settingsModel,
                            onAllowLocation = askLocation,
                            onBackgroundLocation = ::explainBackgroundLocation,
                            onFindPhoneAccess = ::explainFinderAccess,
                            onChoosePhoto = onChoosePhoto,
                            onTakePhoto = onTakePhoto
                        )
                    }
                }
            }
        }
    }

    /** Recreates the activity so a newly opened invitation link fills the sign-in form. */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        recreate()
    }

    /** Test hooks. */
    companion object {
        /** UI tests supply fake repositories (no server, Keystore or GPS). */
        @VisibleForTesting
        internal var testContainer: AppContainer? = null
    }
}

/** Loading screen shown while the saved session is restored. */
@Composable
private fun RestoringScreen() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            BrandHeader(height = 56.dp, centered = true)
            Spacer(Modifier.height(28.dp))
            CircularProgressIndicator()
            Spacer(Modifier.height(12.dp))
            Text("Restoring your sign-in…")
        }
    }
}

/** A label and value row in the member details panel. */
@Composable
internal fun MemberDetailRow(label: String, value: String) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 6.dp),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(label)
        Text(value, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
