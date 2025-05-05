from collections.abc import Mapping
from typing import TypedDict

SENSITIVE_FIELD_NAMES = [
    "username",
    "password",
]

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


class MeasurementBundle(TypedDict):
    sensors: list[str]
    datapoints: list[list[int | float]]


MeasurementList = list[Mapping[str, int | float]]
