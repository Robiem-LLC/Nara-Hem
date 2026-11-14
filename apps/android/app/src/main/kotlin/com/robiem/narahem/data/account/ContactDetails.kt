package com.robiem.narahem.data.account

/**
 * The signed-in account's email address and phone number, either of which may be missing, and
 * whether the server can text (without that, a phone number can't be added).
 */
data class ContactDetails(val email: String?, val phone: String?, val textingOn: Boolean)
