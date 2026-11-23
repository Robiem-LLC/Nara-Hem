package com.robiem.narahem.data.account

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.robiem.narahem.data.FakeAndroidKeyStore
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/** Remembered sessions, connection errors and form checks in [ServerAccountRepository]. */
@RunWith(AndroidJUnit4::class)
class AccountSessionTest {
    private val context: Context get() = ApplicationProvider.getApplicationContext()

    private val certificate =
        HeldCertificate.Builder().addSubjectAlternativeName("localhost").build()

    private val server = MockWebServer()
    private lateinit var client: OkHttpClient
    private lateinit var address: String

    @After fun tearDown() = server.shutdown()

    @Before fun setUp() {
        FakeAndroidKeyStore.install()
        server.useHttps(
            HandshakeCertificates.Builder().heldCertificate(certificate).build().sslSocketFactory(),
            false
        )
        server.start()
        address = server.url("/").toString()
        val trust =
            HandshakeCertificates.Builder().addTrustedCertificate(certificate.certificate).build()
        client = OkHttpClient.Builder()
            .sslSocketFactory(trust.sslSocketFactory(), trust.trustManager)
            .followRedirects(false).followSslRedirects(false)
            .callTimeout(2, TimeUnit.SECONDS).build()
    }

    private fun reply(body: String, code: Int = 200) =
        server.enqueue(MockResponse().setResponseCode(code).setBody(body))

    private fun signedIn(): ServerAccountRepository {
        reply("""{"access_token":"a1","refresh_token":"r1"}""")
        reply("""{"id":"acc","username":"","role":"admin","verified":true}""")
        reply("""{"id":"home"}""")
        val repo = ServerAccountRepository(client, context)
        val account = runBlocking { repo.signIn(address, " sam@example.invalid ", "pw") }
        assertEquals(Account("Admin", true, "home", "acc", "admin"), account)
        repeat(3) { server.takeRequest() }
        return repo
    }

    @Test fun rememberedSignInIsRestoredOnTheSameServerOnly() = runBlocking<Unit> {
        signedIn()
        val restored = ServerAccountRepository(client, context)
        assertNull(restored.restoreSession("https://other.example"))
        reply("""{"access_token":"a2","refresh_token":"r2"}""")
        reply("""{"id":"acc","username":"sam","verified":true}""")
        reply("""{"id":"home"}""")
        assertEquals("sam", restored.restoreSession(address)!!.name)
        val refresh = server.takeRequest()
        assertEquals("/api/native/session/refresh", refresh.path)
        assertEquals("r1", JSONObject(refresh.body.readUtf8()).getString("refresh_token"))
    }

    @Test fun expiredRememberedSignInIsForgotten() = runBlocking<Unit> {
        signedIn()
        reply("""{"detail":"Expired"}""", 401)
        assertNull(ServerAccountRepository(client, context).restoreSession(address))
        assertNull(RememberedSessionStore(context).read())
        assertNull(ServerAccountRepository(client).restoreSession(address))
    }

    @Test fun refreshFailuresOtherThanExpiryAreReported() = runBlocking<Unit> {
        signedIn()
        reply("""{"detail":"Maintenance"}""", 503)
        val error = assertThrows(AccountRequestException::class.java) {
            runBlocking { ServerAccountRepository(client, context).restoreSession(address) }
        }
        assertEquals("Maintenance", error.message)
    }

    @Test fun failedAccountLoadSignsTheNewSessionOut() = runBlocking<Unit> {
        reply("""{"access_token":"a1"}""")
        reply("""{"detail":"Broken"}""", 500)
        reply("""{"signed_out":true}""")
        val repo = ServerAccountRepository(client)
        assertThrows(AccountRequestException::class.java) {
            runBlocking { repo.signIn(address, "sam@example.invalid", "pw") }
        }
        repeat(2) { server.takeRequest() }
        assertEquals("/api/logout", server.takeRequest().path)
    }

    @Test fun signInChecksTheFormAndTheServersAnswer() = runBlocking<Unit> {
        val repo = ServerAccountRepository(client)
        val noEmail = assertThrows(AccountRequestException::class.java) {
            runBlocking { repo.signIn(address, " ", "pw") }
        }
        assertEquals(setOf("email"), noEmail.fields.keys)
        val noPassword = assertThrows(AccountRequestException::class.java) {
            runBlocking { repo.signIn(address, "sam@example.invalid", "") }
        }
        assertEquals(setOf("password"), noPassword.fields.keys)
        reply("""{"ok":true}""")
        val noToken = assertThrows(IOException::class.java) {
            runBlocking { repo.signIn(address, "sam@example.invalid", "pw") }
        }
        assertTrue(noToken.message!!.contains("native sign-in token"))
        reply("<html>Welcome</html>")
        val page = assertThrows(IOException::class.java) {
            runBlocking { repo.signIn(address, "sam@example.invalid", "pw") }
        }
        assertTrue(page.message!!.contains("unexpected page"))
        reply("Not here", 404)
        val missing = assertThrows(AccountRequestException::class.java) {
            runBlocking { repo.signIn(address, "sam@example.invalid", "pw") }
        }
        assertTrue(missing.message!!.contains("expected Nära Hem service"))
    }

    @Test fun connectionProblemsAreExplained() = runBlocking<Unit> {
        server.enqueue(MockResponse().setHeadersDelay(5, TimeUnit.SECONDS).setBody("{}"))
        val slow = assertThrows(IOException::class.java) {
            runBlocking { ServerAccountRepository(client).requestEnrollment(address, "a@b.c") }
        }
        assertTrue(
            slow.message!!.startsWith("Could not connect") || slow.message!!.contains("too long")
        )
        val untrusted = assertThrows(IOException::class.java) {
            runBlocking { ServerAccountRepository().requestEnrollment(address, "a@b.c") }
        }
        assertTrue(untrusted.message!!.contains("trusted HTTPS"))
        server.shutdown()
        val down = assertThrows(IOException::class.java) {
            runBlocking { ServerAccountRepository(client).requestEnrollment(address, "a@b.c") }
        }
        assertTrue(down.message!!.startsWith("Could not connect"))
    }

    @Test fun enrollmentFormsAreCheckedBeforeSending() = runBlocking<Unit> {
        val repo = ServerAccountRepository(client)
        val checks = listOf<suspend () -> Unit>(
            { repo.requestEnrollment(address, " ") },
            { repo.claimInvitation(address, "a@b.c", "x", "p".repeat(20)) },
            { repo.claimInvitation(address, "a@b.c", "sam", "short") },
            { repo.completeEnrollment(address, "short", "", "") },
            { repo.completeEnrollment(address, "t".repeat(30), "x", "") },
            { repo.completeEnrollment(address, "t".repeat(30), "", "short") }
        )
        for (check in checks) {
            assertThrows(AccountRequestException::class.java) { runBlocking { check() } }
        }
        assertEquals(0, server.requestCount)
        reply("""{"message":"Use the emailed link."}""")
        assertEquals(
            "Use the emailed link.",
            repo.claimInvitation(address, "a@b.c", "sam", "p".repeat(20))
        )
        reply("{}")
        repo.completeEnrollment(
            address,
            "https://x.example/#verify=" + "t".repeat(30) + "&x=1",
            "",
            ""
        )
        server.takeRequest()
        val verify = JSONObject(server.takeRequest().body.readUtf8())
        assertEquals("t".repeat(30), verify.getString("token"))
        assertTrue(verify.isNull("username"))
        // A texted code goes with the phone number it was sent to.
        reply("{}")
        repo.completeEnrollment(address, " 123456 ", "sam", "p".repeat(20), "+14155550123")
        val coded = JSONObject(server.takeRequest().body.readUtf8())
        assertEquals("123456", coded.getString("code"))
        assertEquals("+14155550123", coded.getString("email"))
        assertFalse(coded.has("token"))
    }

    @Test fun authenticatedRequestsCanUsePut() = runBlocking<Unit> {
        val repo = signedIn()
        reply("""{"username":"sam.lee"}""")
        repo.authenticated("/api/account/username", JSONObject().put("username", "sam.lee"), "PUT")
        val sent = server.takeRequest()
        assertEquals("PUT", sent.method)
        assertEquals("Bearer a1", sent.getHeader("Authorization"))
    }
}
