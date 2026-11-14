package com.robiem.narahem.data.location

/** Fixed answers for tests; nothing leaves the test. */
class FakeAddressLookup(
    private val nearby: (Double, Double) -> String? = { _, _ -> null },
    private val found: Map<String, Pair<Double, Double>> = emptyMap()
) : AddressLookup {
    override suspend fun near(latitude: Double, longitude: Double) = nearby(latitude, longitude)
    override suspend fun find(query: String) = found[query]
}
