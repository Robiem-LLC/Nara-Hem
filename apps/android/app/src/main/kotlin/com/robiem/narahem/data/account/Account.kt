package com.robiem.narahem.data.account

/**
 * The signed-in account: display name, email verification state, household name, account ID and
 * role.
 */
data class Account(
    val name: String,
    val verified: Boolean,
    val household: String,
    val id: String = "",
    val role: String = "member"
)
