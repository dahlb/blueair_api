from typing import Any, Dict, List, Mapping, Union
from typing_extensions import TypedDict


SENSITIVE_FIELD_NAMES = [
    "username",
    "password",
]

# The BlueAir API uses a fixed API key.
API_KEY = "eyJhbGciOiJIUzI1NiJ9.eyJncmFudGVlIjoiYmx1ZWFpciIsImlhdCI6MTQ1MzEyNTYzMiwidmFsaWRpdHkiOi0xLCJqdGkiOiJkNmY3OGE0Yi1iMWNkLTRkZDgtOTA2Yi1kN2JkNzM0MTQ2NzQiLCJwZXJtaXNzaW9ucyI6WyJhbGwiXSwicXVvdGEiOi0xLCJyYXRlTGltaXQiOi0xfQ.CJsfWVzFKKDDA6rWdh-hjVVVE9S3d6Hu9BzXG9htWFw"  # noqa: E501

MeasurementBundle = TypedDict(
    "MeasurementBundle",
    {"sensors": List[str], "datapoints": List[List[Union[int, float]]]},
)

MeasurementList = List[Mapping[str, Union[int, float]]]

AWS_APIKEYS = {
  'us': {
    'gigyaRegion': 'us1',
    'restApiId': 'on1keymlmh',
    'awsRegion': 'us-east-2',
    'apiKey': '3_-xUbbrIY8QCbHDWQs1tLXE-CZBQ50SGElcOY5hF1euE11wCoIlNbjMGAFQ6UwhMY',
  },
  'eu': {
    'gigyaRegion': 'eu1',
    'restApiId': 'hkgmr8v960',
    'awsRegion': 'eu-west-1',
    'apiKey': '3_qRseYzrUJl1VyxvSJANalu_kNgQ83swB1B9uzgms58--5w1ClVNmrFdsDnWVQQCl',
  },
}