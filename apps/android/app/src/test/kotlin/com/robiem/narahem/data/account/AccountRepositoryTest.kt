package com.robiem.narahem.data.account

import java.io.IOException
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class AccountRepositoryTest {
    @Test fun rejectsUnsafeOrNonOriginAddresses() {
        for (url in listOf(
            "http://localhost",
            "https://user:password@example.invalid",
            "https://example.invalid/path",
            "https://example.invalid?query=1",
            "https://example.invalid/#token"
        )) {
            assertThrows(IllegalArgumentException::class.java) { serverOrigin(url) }
        }
        assertEquals(
            "https://example.invalid:8443/",
            serverOrigin(" https://example.invalid:8443 ").toString()
        )
        // Typed just as the invitation text writes it.
        assertEquals(
            "https://nara-hem.family.example/",
            serverOrigin("nara-hem<.>family < . > example").toString()
        )
        assertEquals(
            "https://example.invalid:8443/",
            serverOrigin(" example.invalid:8443 ").toString()
        )
    }

    @Test fun invitationLinkNeverSilentlyReplacesSavedServer() {
        // A link can fill in a fresh install.
        assertEquals(
            InitialServer("https://family.example.invalid"),
            initialServer("", "https://family.example.invalid")
        )
        // Same origin (any spelling) keeps the saved value without asking.
        assertEquals(
            InitialServer("https://family.example.invalid"),
            initialServer("https://family.example.invalid", "family.example.invalid")
        )
        // A different server keeps the saved one and requires explicit confirmation.
        assertEquals(
            InitialServer("https://family.example.invalid", "https://evil.example.invalid"),
            initialServer("https://family.example.invalid", "https://evil.example.invalid")
        )
        assertEquals(
            InitialServer("https://family.example.invalid"),
            initialServer("https://family.example.invalid", null)
        )
    }

    private fun withServer(test: (MockWebServer, ServerAccountRepository) -> Unit) {
        val certificate = HeldCertificate.Builder().addSubjectAlternativeName("localhost").build()
        val serverTls = HandshakeCertificates.Builder().heldCertificate(certificate).build()
        val clientTls = HandshakeCertificates.Builder().addTrustedCertificate(
            certificate.certificate
        ).build()
        MockWebServer().use { server ->
            server.useHttps(serverTls.sslSocketFactory(), false)
            val client = OkHttpClient.Builder().sslSocketFactory(
                clientTls.sslSocketFactory(),
                clientTls.trustManager
            )
                .followRedirects(false).followSslRedirects(false).build()
            test(server, ServerAccountRepository(client))
        }
    }

    @Test fun nativeLoginAndLogoutUseSeparateAccountBearerWithoutUploadingLocations() = withServer {
            server,
            repository
        ->
        server.enqueue(MockResponse().setBody("{\"access_token\":\"synthetic-token\"}"))
        server.enqueue(MockResponse().setBody("{\"username\":\"Test member\",\"verified\":false}"))
        server.enqueue(MockResponse().setBody("{\"id\":\"synthetic-household\",\"revision\":0}"))
        server.enqueue(MockResponse().setBody("{\"signed_out\":true}"))
        runBlocking {
            val account = repository.signIn(
                server.url("/").toString(),
                " member@example.invalid ",
                "synthetic password"
            )
            assertFalse(account.verified)
            assertEquals("Test member", account.name)
            repository.signOut()
        }
        val login = server.takeRequest()
        assertEquals("/api/login", login.path)
        assertEquals("native", login.getHeader("X-NaraHem-Client"))
        assertNull(login.getHeader("Origin"))
        val payload = JSONObject(login.body.readUtf8())
        assertTrue(payload.getBoolean("native"))
        assertEquals("member@example.invalid", payload.getString("email"))
        for (path in listOf("/api/session", "/api/household", "/api/logout")) {
            val request = server.takeRequest()
            assertEquals(path, request.path)
            assertEquals("Bearer synthetic-token", request.getHeader("Authorization"))
        }
        assertEquals(4, server.requestCount)
    }

    @Test fun expiredAccessUsesRotatingNativeGrantAndRevokesItOnSignOut() = withServer {
            server,
            repository
        ->
        server.enqueue(
            MockResponse().setBody(
                "{\"access_token\":\"short-lived-a\",\"refresh_token\":\"refresh-a\"}"
            )
        )
        server.enqueue(
            MockResponse().setBody(
                "{\"id\":\"acc\",\"username\":\"Test member\",\"verified\":true}"
            )
        )
        server.enqueue(MockResponse().setBody("{\"id\":\"household\",\"revision\":1}"))
        server.enqueue(MockResponse().setResponseCode(401).setBody("{\"detail\":\"Expired\"}"))
        server.enqueue(
            MockResponse().setBody(
                "{\"access_token\":\"short-lived-b\",\"refresh_token\":\"refresh-b\"}"
            )
        )
        server.enqueue(MockResponse().setBody("{\"members\":[]}"))
        server.enqueue(MockResponse().setBody("{\"signed_out\":true}"))
        server.enqueue(MockResponse().setBody("{\"signed_out\":true}"))
        runBlocking {
            repository.signIn(
                server.url("/").toString(),
                "member@example.invalid",
                "synthetic password"
            )
            val response = repository.authenticated("/api/household/members")
            assertEquals(0, response.getJSONArray("members").length())
            repository.signOut()
        }
        val requests = (1..8).map { server.takeRequest() }
        assertEquals(
            listOf(
                "/api/login",
                "/api/session",
                "/api/household",
                "/api/household/members",
                "/api/native/session/refresh",
                "/api/household/members",
                "/api/native/session/revoke",
                "/api/logout"
            ),
            requests.map { it.path }
        )
        assertEquals("Bearer short-lived-a", requests[3].getHeader("Authorization"))
        assertEquals(
            "refresh-a",
            JSONObject(requests[4].body.readUtf8()).getString("refresh_token")
        )
        assertEquals("Bearer short-lived-b", requests[5].getHeader("Authorization"))
        assertEquals(
            "refresh-b",
            JSONObject(requests[6].body.readUtf8()).getString("refresh_token")
        )
    }

    @Test fun preservesRateLimitFeedback() = withServer { server, repository ->
        server.enqueue(
            MockResponse().setResponseCode(
                429
            ).setBody("{\"detail\":\"Too many requests; try again later\"}")
        )
        val error = assertThrows(IOException::class.java) {
            runBlocking {
                repository.signIn(
                    server.url("/").toString(),
                    "member@example.invalid",
                    "synthetic password"
                )
            }
        }
        assertEquals("Too many requests; try again later", error.message)
        assertEquals(1, server.requestCount)
    }

    @Test fun invitationsUseNativeRoutesAndDoNotSignInOrUpload() = withServer {
            server,
            repository
        ->
        server.enqueue(
            MockResponse().setResponseCode(202).setBody("{\"message\":\"Check your email\"}")
        )
        server.enqueue(MockResponse().setBody("{\"verified\":true}"))
        server.enqueue(
            MockResponse().setResponseCode(202).setBody("{\"message\":\"Request queued\"}")
        )
        runBlocking {
            assertEquals(
                "Check your email",
                repository.requestEnrollment(server.url("/").toString(), "member@example.invalid")
            )
            repository.completeEnrollment(
                server.url("/").toString(),
                server.url("/").toString() + "#verify=" + "t".repeat(32),
                "member",
                "a long synthetic password"
            )
            assertEquals(
                "Request queued",
                repository.requestInvitation(
                    server.url("/").toString(),
                    "new@example.invalid",
                    "New person",
                    "School friend"
                )
            )
        }
        for (path in listOf(
            "/api/enrollment/request",
            "/api/enrollment/verify",
            "/api/invitation-requests"
        )) {
            val request = server.takeRequest()
            assertEquals(path, request.path)
            assertEquals("native", request.getHeader("X-NaraHem-Client"))
            assertNull(request.getHeader("Authorization"))
        }
    }

    @Test fun validationErrorsRetainFieldNamesWithoutEchoingSecrets() = withServer {
            server,
            repository
        ->
        server.enqueue(
            MockResponse().setResponseCode(
                422
            ).setBody(
                "{\"detail\":\"Please correct the highlighted " +
                    "fields.\",\"fields\":[{\"field\":\"email\",\"message\":\"Enter a valid " +
                    "email.\"}]}"
            )
        )
        val error =
            assertThrows(com.robiem.narahem.data.account.AccountRequestException::class.java) {
                runBlocking {
                    repository.requestEnrollment(server.url("/").toString(), "not-an-email")
                }
            }
        assertEquals("Enter a valid email.", error.fields["email"])
        assertEquals(422, error.status)
    }

    @Test fun doesNotFollowCredentialRedirects() = withServer { server, repository ->
        server.enqueue(MockResponse().setResponseCode(307).setHeader("Location", "/unexpected"))
        assertThrows(IOException::class.java) {
            runBlocking {
                repository.signIn(
                    server.url("/").toString(),
                    "member@example.invalid",
                    "synthetic password"
                )
            }
        }
        assertEquals(1, server.requestCount)
    }
}
