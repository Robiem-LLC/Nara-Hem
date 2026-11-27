# Store images

What to upload to each store. Everything here is made by
[`tools/showcase/store.py`](../../tools/showcase/store.py).

## `ios/` (App Store Connect)

- `app-store-header.png` (3840 × 1646): the Header Asset on the version page.
- `screenshots/` (1206 × 2622): the iPhone screenshots, for the required "iPhone with Dynamic
  Island (medium display)" slot (6.1" and 6.3"). Apple scales them down for smaller iPhones.

## `android/` (Google Play Console)

- `play-icon.png` (512 × 512): the app icon, the iPhone icon scaled down. Play rounds the
  corners itself, so it's a full square.
- `feature-graphic.png` (1024 × 500): the feature graphic.
- `screenshots/` (1080 × 1920): the phone screenshots.

Neither store accepts the other's images: the sizes differ, and each store rejects anything that
names the other's platform (App Store guideline 2.3.10), which is why nothing is shared between
the two folders.

## `badges/`

Apple's "Download on the App Store" (`app-store.svg`) and Google's "Get it on Google Play"
(`google-play.png`) badges, as each company publishes them. The website shows them once the app
links point at the stores ([releasing](../releasing.md#once-the-apps-are-in-the-stores)). Both
stores' rules: don't change a badge's colours, words or shape, show them the same height side by
side, leave space around each, and link each to the app's page in its store. They're the official
files, not made by `store.py`: get new ones from
[Apple](https://toolbox.marketingtools.apple.com/en-us/app-store/us) and
[Google](https://play.google.com/intl/en_us/badges/).

## Updating them

- **Header and feature graphic:** `python tools/showcase/store.py art docs/marketing`
- **Screenshots:** they're taken from the real apps with a fictional family, on the Mac. Run the
  "Showcase site" workflow (it runs by itself when `main` changes `tools/showcase`), download its
  **marketing** artifact, and copy its `ios` and `android` folders over these.
