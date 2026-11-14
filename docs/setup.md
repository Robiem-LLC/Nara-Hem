# First-time setup

Once the server is [installed](../deploy/README.md) and reachable at its HTTPS address:

1. **Find the setup token.** The server prints it in its log the first time it starts:

   ```text
   NARAHEM FIRST-RUN SETUP TOKEN: …
   ```

   - **Portainer:** **Containers** → the `narahem` container → **Logs**.
   - **Docker Compose:** `docker compose logs narahem | grep "SETUP TOKEN"`.

   If the log has rotated, see [troubleshooting](troubleshooting.md#the-setup-token).

2. **Create the household.** Open your server's address, enter the token, name the household, and
   create the administrator: email, username and a password of at least 15 characters. Setup then
   closes for good.
3. **Set up email.** Sign in, open **Admin settings → Email**, and enter your SMTP details (common
   providers fill in by themselves). Send yourself a test, then confirm the administrator email.
4. **Trust this browser.** The first browser is approved with the device bootstrap token, or with a
   six-digit code by email. The page shows both; the token comes from
   [this command](troubleshooting.md#the-device-bootstrap-token).
5. **Optional extras** in **Admin settings**:
   - **Text messages:** add your Textbelt key to send invitations and codes by text too.
   - **Push relays:** shows whether the server has registered for iPhone and Android notifications;
     **Register now** if not.
   - **Alexa:** see [Alexa](alexa.md).
6. **Invite your household.** **Manage household** → enter an email or phone number → **Send
   invitation**. The invitation has the app download links, your server's address and how to sign
   in.
