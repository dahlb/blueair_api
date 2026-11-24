"""Constants, API keys, and typed structures used across the Blueair API client."""

from collections.abc import Mapping
from typing import TypedDict

VERSION: str = "2.1.1"

# Field and header names (compared lowercase) whose values are masked in
# debug logs: credentials, tokens, session secrets, signatures and email.
SENSITIVE_FIELD_NAMES = [
    "username",
    "password",
    "loginid",
    "email",
    "authorization",
    "idtoken",
    "id_token",
    "access_token",
    "refresh_token",
    "oauth_token",
    "secret",
    "regtoken",
    "sessiontoken",
    "sessionsecret",
    "cookievalue",
    "uidsignature",
    "x-auth-token",
    "ba_x-amz-customauthorizer-signature",
    "ba_x-amz-customauthorizer-token",
]

# Statuses the Blueair API uses to report a rate limit: the standard HTTP 429,
# and the non-standard 229 that BlueCloud answers with
# ``{"message": "There are too many calls, please try again later"}``.
RATE_LIMIT_STATUS_CODES: frozenset[int] = frozenset({229, 429})

# Total time allowed for one HTTP request to the Blueair API, in seconds.
REQUEST_TIMEOUT_SECONDS: float = 20

# How long the MQTT client waits for a credential refresh before a reconnect.
# A full refresh makes up to 6 requests in sequence (Gigya login, plus
# completing a pending registration and logging in again when needed, then
# getJWT and the BlueCloud login), each bounded by REQUEST_TIMEOUT_SECONDS.
MQTT_CREDENTIAL_REFRESH_TIMEOUT_SECONDS: float = 6 * REQUEST_TIMEOUT_SECONDS

# Refresh the BlueCloud access token this many seconds before its ``exp``
# claim, so requests in flight do not carry a token that expires mid-request.
# Capped at half the token's lifetime so a short-lived token is not refreshed
# on every request.
ACCESS_TOKEN_REFRESH_MARGIN_SECONDS: float = 60

# The BlueAir API uses a fixed API key.
API_KEY = "eyJhbGciOiJIUzI1NiJ9.eyJncmFudGVlIjoiYmx1ZWFpciIsImlhdCI6MTQ1MzEyNTYzMiwidmFsaWRpdHkiOi0xLCJqdGkiOiJkNmY3OGE0Yi1iMWNkLTRkZDgtOTA2Yi1kN2JkNzM0MTQ2NzQiLCJwZXJtaXNzaW9ucyI6WyJhbGwiXSwicXVvdGEiOi0xLCJyYXRlTGltaXQiOi0xfQ.CJsfWVzFKKDDA6rWdh-hjVVVE9S3d6Hu9BzXG9htWFw"  # noqa: E501

AWS_APIKEYS = {
    "us": {
        "gigyaRegion": "accounts.us1.gigya.com",
        "restApiId": "on1keymlmh",
        "awsRegion": "us-east-2.amazonaws.com",
        "apiKey": "3_-xUbbrIY8QCbHDWQs1tLXE-CZBQ50SGElcOY5hF1euE11wCoIlNbjMGAFQ6UwhMY",
    },
    "eu": {
        "gigyaRegion": "accounts.eu1.gigya.com",
        "restApiId": "hkgmr8v960",
        "awsRegion": "eu-west-1.amazonaws.com",
        "apiKey": "3_qRseYzrUJl1VyxvSJANalu_kNgQ83swB1B9uzgms58--5w1ClVNmrFdsDnWVQQCl",
    },
    "cn": {
        "gigyaRegion": "accounts.cn1.sapcdm.cn",
        "restApiId": "ftbkyp79si",
        "awsRegion": "cn-north-1.amazonaws.com.cn",
        "apiKey": "3_h3UEfJnA-zDpFPR9L4412HO7Mz2VVeN4wprbWYafPN1gX0kSnLcZ9VSfFi7bEIIU",
    },
    "au": {
        "gigyaRegion": "accounts.au1.gigya.com",
        "restApiId": "hkgmr8v960",
        "awsRegion": "eu-west-1.amazonaws.com",
        "apiKey": "3_Z2N0mIFC6j2fx1z2sq76R3pwkCMaMX2y9btPb0_PgI_3wfjSJoofFnBbxbtuQksN",
    },
}

# MQTT broker endpoints per region (AWS IoT Core).
# Identified via the Blueair cloud API login response and AWS IoT
# endpoint patterns.
AWS_MQTT_BROKERS = {
    "us": "a3tpdpjvxk6yog-ats.iot.us-east-2.amazonaws.com",
    "eu": "a3tpdpjvxk6yog-ats.iot.eu-west-1.amazonaws.com",
    "au": "a3tpdpjvxk6yog-ats.iot.eu-west-1.amazonaws.com",
    "cn": "a2du5f95w7oz2a.ats.iot.cn-north-1.amazonaws.com.cn",
}


class MeasurementBundle(TypedDict):
    """A single sensor/datapoint history bundle returned by the AWS API."""

    sensors: list[str]
    datapoints: list[list[int | float]]


MeasurementList = list[Mapping[str, int | float]]
