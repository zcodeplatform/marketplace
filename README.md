# Comrade Marketplace

A Flask marketplace with seller listings, buyer and seller profiles, M-Pesa STK Push payments, administrator-managed homepage ads, and optional Cloudflare R2 image storage.

## Requirements

- Python 3.10 or later
- Safaricom Daraja credentials for M-Pesa payments
- Cloudflare R2 credentials if using R2 image storage

## Install and run

From the project directory, create and activate a virtual environment, install dependencies, and copy the environment template:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` with the settings described below, then start the application:

```powershell
flask --app app seed-demo  # Optional: add sample storefront products
flask --app app run --debug
```

Open `http://localhost:5000`. Use the same hostname configured in your Google OAuth redirect URI.

Run the automated tests with:

```powershell
python -m unittest discover -s tests
```

## Configuration

`.env.example` lists all supported environment variables. At minimum, set a unique `SECRET_KEY` before deploying. Leave `DATABASE_URL` blank to use the local SQLite database at `instance/marketplace.db`.

### Google sign-in (optional)

1. In the [Google Cloud Console](https://console.cloud.google.com/), configure the OAuth consent screen and create a Web application OAuth client.
2. Add `http://localhost:5000/auth/google/callback` as an authorized redirect URI. Add your production callback URL when deploying.
3. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`.

The Google sign-in option is shown only when both values are configured. Users can also sign up with an email and password.

### Homepage ads

Set `ADMIN_EMAILS` to a comma-separated list of marketplace account emails authorized to manage banners, for example:

```env
ADMIN_EMAILS=admin@example.com,another.admin@example.com
```

Authorized users must sign in with one of those accounts. They can upload, edit, publish, hide, or delete banners at `/admin/ads`. Each banner has a required title/description, an optional destination URL, and an optional image replacement when editing. Destination URLs must use `http` or `https`.

The homepage shows up to the three newest active ads. On desktop they display side by side; on mobile they rotate one at a time. Uploaded images use the configured image-storage backend and are converted to WebP.

### M-Pesa checkout

1. Create a Daraja app and obtain its consumer key, consumer secret, Lipa Na M-Pesa passkey, and shortcode.
2. Set `MPESA_CONSUMER_KEY`, `MPESA_CONSUMER_SECRET`, `MPESA_PASSKEY`, and `MPESA_SHORTCODE` in `.env`. For sandbox testing, use the sandbox base URL and shortcode `174379`.
3. Set `MPESA_CALLBACK_URL` to a publicly reachable HTTPS URL ending in `/mpesa/callback`. Safaricom cannot reach `localhost`; use an HTTPS tunnel during local development.
4. Restart the Flask app after changing environment settings.

Keep sandbox credentials paired with the sandbox base URL, and production credentials paired with the production base URL. Checkout is available only to signed-in users and uses current server-side product prices; M-Pesa totals must be whole Kenyan shillings.

Each initiated customer checkout is recorded in the `payments` table with its buyer, order snapshot, amount, M-Pesa references/response, and status. Callback results and manual Daraja status checks update pending payments to `success`, `failed`, or `cancelled`. Buyers can view their purchase payment history in their profile; sellers can view their gross sales shares and statuses there. Sales history is not a payout ledger. Listing-plan charges are stored separately in `listing_plan_payments`.

The callback must be reachable for Safaricom to report the final status. Checkout checks for a callback briefly, then stops automatic polling; buyers can use **Check M-Pesa now** to query Daraja. A pending transaction remains visible in history until a result is confirmed. Existing customer payment records are retained when the buyer ownership field is added, but older records cannot be attributed to a buyer retroactively.

### Seller listing plan

Each seller can create up to five product listings without a plan. From the profile, they can pay KES 100 through M-Pesa for unlimited visible listings for 30 days. The plan begins only after payment succeeds. After expiry, the seller’s five oldest listings remain visible and newer listings are hidden until renewal. Plan status, expiry, and payment history appear in the seller profile.

## Image storage

Product, profile, and homepage-ad uploads are validated and converted to WebP (maximum dimensions 2000 × 2000, quality 80). Cloudflare R2 is the default storage backend.

1. Create an R2 bucket and an API token with read/write access to the bucket.
2. Set `IMAGE_STORAGE_BACKEND=r2`, `CLOUDFLARE_R2_ACCOUNT_ID`, `CLOUDFLARE_R2_ACCESS_KEY_ID`, `CLOUDFLARE_R2_SECRET_ACCESS_KEY`, and `CLOUDFLARE_R2_BUCKET` in `.env`.
3. Enable public access using an `r2.dev` URL or custom domain, and set `CLOUDFLARE_R2_PUBLIC_URL` to the public base URL without a trailing slash.
4. Restart Flask. New image objects are stored under the `uploads/` prefix.

Set `IMAGE_STORAGE_BACKEND=local` to save uploads in `static/uploads/` instead. If R2 is selected but missing configuration, uploads return an error rather than silently switching to local storage. Do not commit `.env` or R2 credentials.

## Product categories and visibility

The marketplace uses these categories: Electronics, Home & Furniture, Clothing & Shoes, Food & Groceries, Beauty & Personal Care, Books & Stationery, Sports & Outdoors, Toys & Games, and Other. The application migrates products using the original category names when it starts.

## Project layout

- `app.py`, `config.py`, `extensions.py`, `models.py`: application setup, configuration, extensions, and data models
- `auth.py`, `account.py`: authentication and profile pages
- `main.py`, `seller.py`: storefront, browsing, and seller listings
- `payments.py`, `mpesa.py`: checkout, payment callbacks/status, listing-plan charges, and Daraja API requests
- `ads.py`: administrator homepage-ad management
- `utils.py`: image processing, local/R2 storage, and shared utilities
- `templates/`, `static/`: Jinja templates and browser assets
- `tests/`: payment, ad, and image-storage tests
