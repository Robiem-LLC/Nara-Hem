package com.robiem.narahem.data.account

import java.io.IOException

/**
 * Error response from the account API. [status] is the HTTP status (0 for client-side validation)
 * and [fields] maps form field names to messages.
 */
class AccountRequestException(
    val status: Int,
    message: String,
    val fields: Map<String, String> = emptyMap()
) : IOException(message)
