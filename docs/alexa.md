# Alexa

Ask an Echo about your household:

- "Alexa, ask Close to Home where Sam is." → "Sam has been at Home since 4:30 PM."
- "Alexa, ask Close to Home where Maya is." → "Maya is driving near Route 9, Springfield."
- "Alexa, ask Close to Home to find Sam's phone." → "Ringing Sam's phone now."
- "Alexa, ask Close to Home to let me know when Mom gets home." → later, your Echo chimes: "From
  Nara Hem: Mom has arrived home."
- "Alexa, ask Close to Home to let me know when Maya leaves school." → "From Nara Hem: Maya has
  left school."

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

## Let me know when…

- Works with any saved place: "…when Sam gets to Grandma's house", "…when Maya leaves the park".
  Without a place, it means **Home**.
- The first time, Alexa asks "Close to Home would like to set reminders. Is that OK?" Say **yes**
  once, then ask again; nothing needs doing in the Alexa app.
- Each time, Alexa checks: "I'll watch for when Mom arrives at Home for 24 hours and notify you if
  it expires. Is that okay?" Say **yes**. If Mom is already home, or Maya isn't at school, Alexa
  says so instead, and the same alert can't be set twice.
- It works through an Alexa reminder, so it shows in your reminders list ("Your Nara Hem location
  alert expired."). When it happens, the reminder changes to ring a few seconds later with "From
  Nara Hem: Mom has arrived home." If it doesn't happen within a day, the reminder is deleted;
  only if that fails do you hear the "expired" line.
- Say **cancel** to the skill to cancel all your waiting alerts.
- Arriving counts once the phone is inside the place; leaving counts once it's well outside, so
  GPS wobble at the edge doesn't set it off. Turning off sharing or deleting the place cancels it.
- Amazon hears the sentences it speaks ("Mom has arrived home"), and nothing else.

## Without saying "Close to Home"

In the US, you can also just say "Alexa, where is Maya?" or "Alexa, find Sam's phone". Alexa may
then ask Nära Hem whether it knows Maya, and if your household has someone by that name, it
answers as if you'd used the skill's name. Amazon decides when to do this, so it doesn't always
work, and Alexa's own features can win; saying "ask Close to Home…" always works. Nothing is shared
when Alexa asks: your server only answers yes or no.

To make your own phrase always reach the skill, add an Alexa routine: **More → Routines → +**,
**When this happens → Voice** with your phrase, then **Add action → Customized** with, for example,
`ask close to home where is Maya`.

## Set it up

1. Add `NARAHEM_ALLOW_ALEXA=true` to your stack's environment variables and redeploy.
2. In the Alexa app: **More → Skills & Games**, search for **Nära Hem**, and choose **Enable to
   use**.
3. Enter your server's address (shown in **Admin settings → Alexa**), then sign in with your Nära
   Hem administrator email and password.
4. Say "Alexa, ask Close to Home where _someone_ is."

## Unlinking

- **Unlink** in **Admin settings → Alexa** ends that link straight away. Link again from the Alexa
  app.
- Changing the administrator password ends every link.
- To turn Alexa off completely, remove `NARAHEM_ALLOW_ALEXA` and redeploy.

## Troubleshooting

- **"Please link Nara Hem…"**: the link was removed or the administrator password changed. Link
  again from the Alexa app.
- **"I'm not sure how to help with that"**: Alexa didn't hear the skill's name. Say "Alexa, open
  Close to Home" first, and check the Alexa app's voice history for what it heard.
- **A name isn't recognised**: Alexa matches first names best. Use the name shown in the app.
- **Admin settings says "Not available"**: your server was built without the Alexa relay. Official
  images have it; for your own build, set `NARAHEM_ALEXA_RELAY_URL` and
  `NARAHEM_ALEXA_STORE_SKILL_ID`.
