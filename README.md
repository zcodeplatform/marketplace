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

## M-Pesa checkout setup
1. In the Safaricom Daraja portal, create an app and get its consumer key and secret, Lipa Na M-Pesa passkey, and shortcode.
2. Set `MPESA_CONSUMER_KEY`, `MPESA_CONSUMER_SECRET`, `MPESA_PASSKEY`, and `MPESA_SHORTCODE` in `.env`. Sandbox uses shortcode `174379`; leave `MPESA_BASE_URL` as `https://sandbox.safaricom.co.ke` for sandbox transactions.
3. Set `MPESA_CALLBACK_URL` to a publicly reachable HTTPS URL ending in `/mpesa/callback`. For local testing, expose port 5000 with a tunnel and use that HTTPS URL.
4. Restart Flask. On checkout, enter a Kenyan M-Pesa number; the app calculates the amount from current active product prices, sends the STK prompt, and updates the payment when Safaricom calls back.

The callback must be reachable by Safaricom. Do not use production credentials with the sandbox URL (or vice versa). M-Pesa STK amounts must be whole Kenyan shillings; checkout rejects fractional totals. Successful payments are stored in the `payments` table with a cart snapshot and payment status.

## Layout
- `app.py` app factory, CLI seed command · `config.py` · `extensions.py` · `models.py` · `utils.py`
- `auth.py` signup/login/logout + Google · `main.py` home/browse/public product pages · `payments.py` M-Pesa checkout/callback/status
- `mpesa.py` Daraja OAuth token and STK Push requests
- `seller.py` create/edit/delete/mark-sold (all `@login_required`, owner-only) · `account.py` profile
- `templates/`, `static/css/styles.css` (your original styles + additions), `static/js/app.js` (your cart + share button)
