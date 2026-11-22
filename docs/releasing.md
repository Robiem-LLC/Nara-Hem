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
- **Server:** the `latest` image.

Nothing is signed, sent to TestFlight or released for Android by a push. Those are manual runs, so
`main` can take changes without releasing anything.

## Releasing the apps

In GitHub, open **Actions**, pick the workflow, click **Run workflow** and choose `main`:

- **iPhone:** "iOS Mac mini" with **signing** set to `app-store`. It's signed for the App Store and
  uploaded to TestFlight.
- **Android:** "Android" with **release** ticked. The APK and Play Store bundle are signed with the
  release key and copied to the Mac's share, and a new version becomes a GitHub Release (below).

## Versions

The [`VERSION`](../VERSION) file holds the version both apps show, such as `1.0.1`. To release a new
one:

1. Change `VERSION` on `dev` and check the builds there.
2. Merge `dev` into `main` and, in the same push, a `v1.0.1` tag on that commit, signed with a key
   in [`.github/allowed_signers`](../.github/allowed_signers), then run the releases above:

   ```bash
   git tag -s v1.0.1 -m "Nära Hem 1.0.1" main
   git push origin main v1.0.1
   ```

When an Android release run builds a version that has no GitHub Release yet and finds its signed
tag on the very commit it built, the Android files are published as that release; invitations link
to the newest one. Otherwise (no tag yet, a tag on another commit, or a version already released)
it still builds, goes to the Mac's share, and says why it didn't release. Pushing the tag later and
running it again releases it then.

The "Release tags" ruleset keeps `v*` tags from being made, moved or deleted by anyone but the
owner. Only commits signed with an allowed key are built at all; commits made on GitHub's website
aren't, and are skipped. Build numbers go up on their own with every run.
