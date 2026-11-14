# Alexa

Ask an Echo about your household:

- "Alexa, ask Nara Home where Sam is." → "Sam has been at Home since 4:30 PM."
- "Alexa, ask Nara Home where Maya is." → "Maya is driving near Route 9, Springfield."
- "Alexa, ask Nara Home to find Sam's phone." → "Ringing Sam's phone now."

If Alexa mishears a name, it asks "Did you mean Maya?" when a household member's name is close.
Answer yes or no.

## Before you start

- It's **off** unless your server has `NARAHEM_ALLOW_ALEXA=true`.
- Alexa signs in with your **administrator** email and password, and sees what your admin browser
  sees: everyone who shares their location.
- Anyone who can talk to your Echo can ask. There is no PIN.
- What Alexa says passes through Amazon and the Nära Hem Alexa relay, which passes requests and
  answers along without keeping them (see the privacy policy).
- Rings only work for phones with **Find my phone** turned on in the app.
- Times are in your Echo's time zone.

## Set it up

1. Add `NARAHEM_ALLOW_ALEXA=true` to your stack's environment variables and redeploy.
2. In the Alexa app: **More → Skills & Games**, search for **Nära Hem**, and choose **Enable to
   use**.
3. Enter your server's address (shown in **Admin settings → Alexa**), then sign in with your Nära
   Hem administrator email and password.
4. Say "Alexa, ask Nara Home where _someone_ is."

## Unlinking

- **Unlink** in **Admin settings → Alexa** ends that link straight away. Link again from the Alexa
  app.
- Changing the administrator password ends every link.
- To turn Alexa off completely, remove `NARAHEM_ALLOW_ALEXA` and redeploy.

## Troubleshooting

- **"Please link Nara Hem…"**: the link was removed or the administrator password changed. Link
  again from the Alexa app.
- **"I'm not sure how to help with that"**: Alexa didn't hear the skill's name. Say "Alexa, open
  Nara Home" first, and check the Alexa app's voice history for what it heard.
- **A name isn't recognised**: Alexa matches first names best. Use the name shown in the app.
- **Admin settings says "Not available"**: your server was built without the Alexa relay. Official
  images have it; for your own build, set `NARAHEM_ALEXA_RELAY_URL` and
  `NARAHEM_ALEXA_STORE_SKILL_ID`.
