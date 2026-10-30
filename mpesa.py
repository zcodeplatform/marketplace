import base64
from datetime import datetime, timedelta, timezone

import requests
from flask import current_app


class MpesaError(Exception):
    """Raised when Daraja cannot accept or process an STK Push request."""


def _credentials():
    keys = (
        "MPESA_BASE_URL",
        "MPESA_CONSUMER_KEY",
        "MPESA_CONSUMER_SECRET",
        "MPESA_PASSKEY",
        "MPESA_SHORTCODE",
        "MPESA_CALLBACK_URL",
    )
    missing = [key for key in keys if not current_app.config.get(key)]
    if missing:
        raise MpesaError("M-Pesa checkout is not configured. Please contact the marketplace.")
    return current_app.config


def _access_token(config):
    url = f"{config['MPESA_BASE_URL']}/oauth/v1/generate?grant_type=client_credentials"
    try:
        response = requests.get(
            url,
            auth=(config["MPESA_CONSUMER_KEY"], config["MPESA_CONSUMER_SECRET"]),
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as error:
        raise MpesaError("Could not connect to M-Pesa. Please try again.") from error

    if not isinstance(data, dict):
        raise MpesaError("M-Pesa returned an invalid access token response.")
    token = data.get("access_token")
    if not token:
        raise MpesaError("M-Pesa did not provide an access token. Please try again later.")
    return token


def stk_push(phone_number, amount, reference):
    config = _credentials()
    token = _access_token(config)
    timestamp = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y%m%d%H%M%S")

    payload = {
        "BusinessShortCode": config["MPESA_SHORTCODE"],
        "Password": _password(config, timestamp),
        "Timestamp": timestamp,
        "TransactionType": config["MPESA_TRANSACTION_TYPE"],
        "Amount": amount,
        "PartyA": phone_number,
        "PartyB": config["MPESA_SHORTCODE"],
        "PhoneNumber": phone_number,
        "CallBackURL": config["MPESA_CALLBACK_URL"],
        "AccountReference": reference,
        "TransactionDesc": "Marketplace order",
    }

    try:
        response = requests.post(
            f"{config['MPESA_BASE_URL']}/mpesa/stkpush/v1/processrequest",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as error:
        raise MpesaError("Could not send the M-Pesa payment prompt. Please try again.") from error

    if not isinstance(data, dict):
        raise MpesaError("M-Pesa returned an invalid payment response.")
    if str(data.get("ResponseCode")) != "0" or not data.get("CheckoutRequestID"):
        message = data.get("CustomerMessage") or data.get("ResponseDescription")
        raise MpesaError(message or "M-Pesa could not start this payment. Please try again.")
    return data


def _password(config, timestamp):
    raw = f"{config['MPESA_SHORTCODE']}{config['MPESA_PASSKEY']}{timestamp}"
    return base64.b64encode(raw.encode("ascii")).decode("ascii")


def stk_query(checkout_request_id):
    config = _credentials()
    token = _access_token(config)
    timestamp = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y%m%d%H%M%S")
    payload = {
        "BusinessShortCode": config["MPESA_SHORTCODE"],
        "Password": _password(config, timestamp),
        "Timestamp": timestamp,
        "CheckoutRequestID": checkout_request_id,
    }

    try:
        response = requests.post(
            f"{config['MPESA_BASE_URL']}/mpesa/stkpushquery/v1/query",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as error:
        raise MpesaError("Could not check the payment with M-Pesa. Please try again.") from error

    if not isinstance(data, dict):
        raise MpesaError("M-Pesa returned an invalid payment status response.")
    if str(data.get("ResponseCode")) != "0":
        message = data.get("ResponseDescription") or data.get("errorMessage")
        raise MpesaError(message or "M-Pesa could not check this payment yet.")
    return data
