# Comrade Marketplace (Flask)

## Run it
```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # then fill in the values
flask --app app seed-demo                             # optional: loads the original 6 products
flask --app app run --debug
```
Open http://localhost:5000 (use `localhost`, not `127.0.0.1`, so it matches the Google redirect URI).

## Google sign-in setup
1. https://console.cloud.google.com → create/select a project.
2. **APIs & Services → OAuth consent screen**: choose External, fill app name + your email, add scopes `openid`, `email`, `profile`. While in "Testing" mode add your Google account under **Test users**.
3. **Credentials → Create credentials → OAuth client ID → Web application**.
4. **Authorized redirect URIs**: `http://localhost:5000/auth/google/callback`
   (in production also add `https://YOUR-DOMAIN/auth/google/callback`).
5. Copy the Client ID / Secret into `.env` as `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.
The "Continue with Google" button only appears once both values are set.

## Homepage ads
Set `ADMIN_EMAILS` to a comma-separated list of account email addresses that can manage homepage banners, for example `ADMIN_EMAILS=admin@example.com`. Those accounts see the **Ads** link and can upload, publish, hide, or delete banners at `/admin/ads`; other signed-in users are denied access.

Ad images use the existing WebP image pipeline and configured image storage (Cloudflare R2 by default). Only the three newest active ads appear in the homepage slideshow. Each ad needs a short accessible description and can optionally link to an external `http` or `https` URL.

## M-Pesa checkout setup
1. In the Safaricom Daraja portal, create an app and get its consumer key and secret, Lipa Na M-Pesa passkey, and shortcode.
2. Set `MPESA_CONSUMER_KEY`, `MPESA_CONSUMER_SECRET`, `MPESA_PASSKEY`, and `MPESA_SHORTCODE` in `.env`. Sandbox uses shortcode `174379`; leave `MPESA_BASE_URL` as `https://sandbox.safaricom.co.ke` for sandbox transactions.
3. Set `MPESA_CALLBACK_URL` to a publicly reachable HTTPS URL ending in `/mpesa/callback`. For local testing, expose port 5000 with a tunnel and use that HTTPS URL.
4. Restart Flask. On checkout, enter a Kenyan M-Pesa number; the app calculates the amount from current active product prices, sends the STK prompt, and updates the payment when Safaricom calls back. The checkout checks for a callback briefly, then stops automatic polling; use **Check M-Pesa now** to query Daraja directly if the callback has not arrived.

The callback must be reachable by Safaricom; `localhost` and `127.0.0.1` are not reachable from Safaricom, so use a public HTTPS tunnel during local development. Do not use production credentials with the sandbox URL (or vice versa). A canceled prompt is recorded separately from other failures when Daraja reports cancellation. M-Pesa STK amounts must be whole Kenyan shillings; checkout rejects fractional totals. Successful payments are stored in the `payments` table with a cart snapshot and payment status.

Seller profiles show the seller’s per-checkout gross sales amount and item snapshot, with pending, successful, failed, and canceled statuses. This is transaction history, not a seller payout ledger. Seller history is tracked for checkouts created after the seller-payment records were added.

## Seller listing plan
The first five seller listings are free. From the seller profile, a seller can pay KES 100 through M-Pesa for unlimited visible listings for 30 days. The plan starts only after a successful M-Pesa confirmation; the profile shows payment status and expiry, and pending payments can be checked directly with Daraja. Each successful payment starts a new 30-day period. After expiry, the seller’s five oldest listings remain visible and newer listings are hidden until renewal. Plan payment records are stored separately from customer checkout payments in `listing_plan_payments`.

## Image storage setup
Image uploads are decoded and re-encoded as WebP (quality 80) before storage. To store them in Cloudflare R2:
1. Create an R2 bucket and an R2 API token with object read/write permissions for that bucket.
2. Set `IMAGE_STORAGE_BACKEND=r2`, `CLOUDFLARE_R2_ACCOUNT_ID`, `CLOUDFLARE_R2_ACCESS_KEY_ID`, `CLOUDFLARE_R2_SECRET_ACCESS_KEY`, and `CLOUDFLARE_R2_BUCKET` in `.env`.
3. Enable public access for the bucket with an `r2.dev` URL or attach a custom domain, then set `CLOUDFLARE_R2_PUBLIC_URL` to that public base URL (no trailing slash).
4. Restart Flask. New product and profile images will be uploaded as `.webp` objects. Existing local uploads continue to use their existing URLs.

R2 is the default storage backend. Set `IMAGE_STORAGE_BACKEND=local` to keep uploads on disk during development. If R2 is selected but not configured, image uploads fail with a visible configuration error rather than silently saving locally. Do not commit R2 credentials.

## Layout
- `app.py` app factory, CLI seed command · `config.py` · `extensions.py` · `models.py` · `utils.py`
- `auth.py` signup/login/logout + Google · `main.py` home/browse/public product pages · `payments.py` M-Pesa checkout/callback/status
- `mpesa.py` Daraja OAuth token and STK Push requests · `utils.py` image processing and local/R2 storage
- `seller.py` create/edit/delete/mark-sold (all `@login_required`, owner-only) · `account.py` profile
- `templates/`, `static/css/styles.css` (your original styles + additions), `static/js/app.js` (your cart + share button)
