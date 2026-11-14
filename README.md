# Nära Hem

Self-hosted household location sharing. Your household runs its own server; the iPhone and
Android apps and the browser connect to it.

- **Map:** where everyone who shares their location is, with saved places and alerts when someone
  arrives or leaves.
- **Trips:** each drive, with distance, top speed and the route.
- **Find my phone:** ring a household member's phone, if they've turned it on in the app.
- **Alexa (optional):** "Alexa, ask Nara Home where Sam is."

**Your household server can read everyone's locations, trips, saved places and profile photos.**
See [what the server can see](docs/security-model.md#what-the-server-can-see). New phones and
browsers only get household data once they've been approved.

## Install

- **Server:** [install](deploy/README.md), then [first-time setup](docs/setup.md). One Docker
  stack is one household. Stuck? See [troubleshooting](docs/troubleshooting.md).
- **Apps:** sign in with your server's address and your account; your server's invitation email
  has the download links.
- **Alexa:** [docs/alexa.md](docs/alexa.md).

## Security

See [SECURITY.md](SECURITY.md).

## Credits

- The iPhone push relay was inspired by [Paje](https://github.com/jonesphillip/paje) by Phillip
  Jones: self-hosted iOS push notifications on Cloudflare Workers.
- Ideas for battery-friendly location tracking came from
  [Traccar](https://github.com/traccar/traccar), the open-source GPS tracking system.

## License

Copyright © 2026 Robiem LLC. Nära Hem is free software under the
[GNU Affero General Public License v3.0](LICENSE): you may use, change and share it, and if you run
a changed version as a service for others, you must offer them its source code.

### Additional permissions (AGPL section 7)

1. If you modify this program, or any covered work, by linking or combining it with the Google
   Maps SDK, Google Play services, Firebase, or other libraries supplied by Apple or Google for
   their platforms (or a modified version of those libraries), Robiem LLC grants you additional
   permission to convey the resulting work. The Corresponding Source for the non-source form of
   such a combination need not include the source code for those libraries.
2. You may convey this program, or a work based on it, through an app store whose terms add
   restrictions for recipients, provided the Corresponding Source is also offered under this
   License, free of charge.

"Nära Hem" and its logo are trademarks of Robiem LLC and aren't covered by the license. Changed
versions must use a different name and logo.
