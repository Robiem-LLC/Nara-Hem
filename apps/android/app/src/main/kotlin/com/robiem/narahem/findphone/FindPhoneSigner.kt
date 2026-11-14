package com.robiem.narahem.findphone

/** A device allowed to sign Find My Phone commands, taken from the roster. */
data class FindPhoneSigner(val id: String, val accountId: String, val key: String)
