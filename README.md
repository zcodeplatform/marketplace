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

## Layout
- `app.py` app factory, CLI seed command · `config.py` · `extensions.py` · `models.py` · `utils.py`
- `auth.py` signup/login/logout + Google · `main.py` home/browse/public product pages
- `seller.py` create/edit/delete/mark-sold (all `@login_required`, owner-only) · `account.py` profile
- `templates/`, `static/css/styles.css` (your original styles + additions), `static/js/app.js` (your cart + share button)
