# Branches and releases

Work happens on `dev`. Once it's checked, `dev` is merged into `main`, and `main` is what people get.

## Pushes to `dev`

Builds to try out; nothing reaches the public:

- **Server:** tests on SQLite and PostgreSQL, and the `dev` image.
- **iPhone:** simulator tests, Swift formatting, and an Ad Hoc copy on the Mac's share.
- **Android:** unit tests and lint, and a debug APK on the Mac's share.
- **Formatting** for every language.

A debug APK is signed with the build Mac's own key, so it can't be installed over a release (or the
other way round) without uninstalling first.

## Pushes to `main`

- **Website:** built and published.
- **iPhone:** signed for the App Store and uploaded to TestFlight.
- **Android:** the APK and Play Store bundle signed with the release key, also copied to the Mac's
  share.
- **Server:** the `latest` image.

## Versions

The [`VERSION`](../VERSION) file holds the version both apps show, such as `1.0.1`. To release a new
one, change it on `dev` and merge to `main`.

- When `main` builds a version that has no `v1.0.1` tag yet, the Android files are published as that
  version's GitHub Release, which creates the tag at the commit. Invitations link to the newest
  release.
- Later pushes with the same version still build, go to TestFlight and the Mac's share, but don't
  make another release.
- A release is only made from a commit signed with a key in
  [`.github/allowed_signers`](../.github/allowed_signers); commits made on GitHub's website aren't,
  and are skipped.
- Build numbers go up on their own with every run.
