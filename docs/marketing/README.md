# Store images

What to upload to each store. Everything here is made by
[`tools/showcase/store.py`](../../tools/showcase/store.py).

## `ios/` (App Store Connect)

- `app-store-header.png` (3840 × 1646): the Header Asset on the version page.
- `screenshots/` (1206 × 2622): the iPhone screenshots, for the required "iPhone with Dynamic
  Island (medium display)" slot (6.1" and 6.3"). Apple scales them down for smaller iPhones.

## `android/` (Google Play Console)

- `feature-graphic.png` (1024 × 500): the feature graphic.
- `screenshots/` (1080 × 1920): the phone screenshots.

Neither store accepts the other's images: the sizes differ, and each store rejects anything that
names the other's platform (App Store guideline 2.3.10), which is why nothing is shared between
the two folders.

## Updating them

- **Header and feature graphic:** `python tools/showcase/store.py art docs/marketing`
- **Screenshots:** they're taken from the real apps with a fictional family, on the Mac. Run the
  "Showcase site" workflow (it runs by itself when `main` changes `tools/showcase`), download its
  **marketing** artifact, and copy its `ios` and `android` folders over these.
