# Alexa

Ask an Echo about your household:

- "Alexa, ask Nara Home where Sam is." → "Sam has been at Home since 4:30 PM."
- "Alexa, ask Nara Home where Maya is." → "Maya is driving near Route 9, Springfield."
- "Alexa, ask Nara Home to find Sam's phone." → "Ringing Sam's phone now."

If Alexa mishears a name, it asks "Did you mean Maya?" when a household member's name is
close. Answer yes or no.

## How it works, and what to know first

- It's **off** unless your server has `NARAHEM_ALLOW_ALEXA=true`.
- Use the **Nära Hem skill** from the Alexa store, or make your own **private skill** in your own
  Amazon developer account. A private skill is free, needs no review by Amazon, only works on
  Echo devices signed in to that same Amazon account, and involves no relay.
- Alexa signs in with your **administrator** email and password. It sees what your admin browser
  sees: everyone who shares their location. Unlink it in **Admin settings → Alexa** at any time;
  changing the administrator password unlinks it too.
- What Alexa says passes through Amazon. Everywhere else, locations stay end-to-end encrypted
  between your household's devices and your server.
- Anyone who can talk to your Echo can ask. There is no PIN.
- Rings work only for phones with **Find my phone** turned on in the app. Your server signs the
  ring itself, with the same key it uses to add phones to the household.
- Times are in your Echo's time zone.

## Set it up with the Nära Hem skill (easiest)

1. Add `NARAHEM_ALLOW_ALEXA=true` to your stack's environment variables and redeploy.
2. In the Alexa app: **More → Skills & Games**, search for **Nära Hem**, and choose **Enable to
   use**.
3. Enter your server's address (as in Admin settings → Alexa), then sign in with your Nära Hem
   administrator email and password.
4. Say "Alexa, ask Nara Home where _someone_ is."

The store skill reaches your server through the Nära Hem Alexa relay, which passes requests and
answers along without keeping them (see the privacy policy). If you'd rather nothing goes through
a relay, use your own private skill instead.

## Or: your own private skill

1. **Turn it on.** Add `NARAHEM_ALLOW_ALEXA=true` to your stack's environment variables and
   redeploy. Open **Admin settings → Alexa**; keep that page open, you'll copy from it.
2. **Create the skill.** Go to the [Alexa developer console](https://developer.amazon.com/alexa/console/ask),
   signed in with the Amazon account your Echo uses, and choose **Create Skill**:
   - Name: `Nara Hem`, primary locale: your Echo's language (e.g. English (US)).
   - Experience: **Other**, model: **Custom**, hosting: **Provision your own**.
   - Template: **Start from Scratch**.
3. **Interaction model.** In **Build → Interaction Model → JSON Editor**, replace everything with
   the contents of [`deploy/alexa/interaction-model.json`](../deploy/alexa/interaction-model.json),
   then **Save** and **Build skill**.
4. **Endpoint.** In **Build → Endpoint**, choose **HTTPS** and paste **Endpoint (HTTPS)** from
   Admin settings into **Default Region**. For the certificate, choose "My development endpoint
   has a certificate from a trusted certificate authority". **Save**.
5. **Account linking.** In **Build → Tools → Account Linking**, turn on "Do you allow users to
   link an account", choose **Auth Code Grant**, and paste from Admin settings:
   - **Web Authorization URI**, **Access Token URI**, **Your Client ID** and **Your Secret**.
   - Client authentication scheme: **HTTP Basic (Recommended)**.
   - Scope: add `household`.

   **Save**.

6. **Skill ID.** On the console's skill list, choose **Copy Skill ID** under the skill and paste
   it into **Skill ID** in Admin settings. Your server refuses requests from any other skill.
7. **Testing.** In the skill's **Test** tab, set "Skill testing is enabled in" to
   **Development**.
8. **Link it.** In the Alexa app: **More → Skills & Games → Your Skills → Dev → Nara Hem →
   Enable to use**. Sign in with your Nära Hem administrator email and password. Admin settings
   now shows Alexa as linked.
9. Say "Alexa, ask Nara Home where _someone_ is."

## Unlinking

- **Unlink** in Admin settings ends that link straight away. Link again from the Alexa app.
- **New secret** ends every link. Use it if the secret may be known; then paste the new one in
  step 5 and link again.
- Changing the administrator password ends every link.
- To turn Alexa off completely, remove `NARAHEM_ALLOW_ALEXA` and redeploy.

## Troubleshooting

- **"Please link Nara Hem…"**: the link was revoked, the password changed or the secret was
  replaced. Link again from the Alexa app (step 8).
- **Alexa says the skill didn't respond**: check the server's address in step 4 and that the Skill
  ID in Admin settings matches the console's.
- **A name isn't recognised**: Alexa matches first names best. Use the name shown in the app.
