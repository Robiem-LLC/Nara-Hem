package com.robiem.narahem.data

import java.util.concurrent.TimeUnit
import okhttp3.OkHttpClient

/**
 * Shared OkHttp client for requests to the household server. Clients derived with newBuilder()
 * reuse its connection pool and threads.
 */
object ServerHttp {
    /**
     * Base client with a 25 second call timeout. Redirects are disabled so credentials are never
     * sent to another host.
     */
    val client: OkHttpClient = OkHttpClient.Builder()
        .followRedirects(false)
        .followSslRedirects(false)
        .callTimeout(25, TimeUnit.SECONDS)
        .build()
}
