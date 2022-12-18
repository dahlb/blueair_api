import logging

from aiohttp import ClientSession, ClientResponse, FormData
from .const import AWS_APIKEYS

from .util_http import request_with_logging
from .errors import AuthError

_LOGGER = logging.getLogger(__name__)


def request_with_active_session(func):
    async def request_with_active_session_wrapper(*args, **kwargs):
        _LOGGER.debug("session")
        try:
            return await func(*args, **kwargs)
        except AuthError as e:
            url = kwargs["url"]
            if "accounts.login" in url:
                raise e
            else:
                _LOGGER.debug(f"got invalid session, attempting to repair and resend")
                self = args[0]
                self.session_token = None
                self.session_secret = None

                self.access_token = None

                self.jwt = None
                response = await func(*args, **kwargs)
                return response

    return request_with_active_session_wrapper


def request_with_errors(func):
    async def request_with_errors_wrapper(*args, **kwargs):
        _LOGGER.debug("checking for errors")
        response: ClientResponse = await func(*args, **kwargs)
        status_code = response.status
        try:
            response_json = await response.json(content_type=None)
            if "statusCode" in response_json:
                _LOGGER.debug("response json found, checking status code from response")
                status_code = response_json["statusCode"]
        except Exception as e:
            _LOGGER.debug(f"Error parsing response for errors {e}")
            return response
        if status_code == 200:
            _LOGGER.debug("response 200")
            return response
        if 400 <= status_code <= 500:
            _LOGGER.debug("auth error")
            raise AuthError(await response.text())

    return request_with_errors_wrapper


class HttpAwsBlueair:
    def __init__(
        self,
        username: str,
        password: str,
        region: str = "us",
        client_session: ClientSession = None,
    ):
        self.username = username
        self.password = password
        self.region = region

        self.session_token = None
        self.session_secret = None

        self.access_token = None

        self.jwt = None

        if client_session is None:
            self.api_session = ClientSession(raise_for_status=False)
        else:
            self.api_session = client_session

    async def cleanup_client_session(self):
        await self.api_session.close()

    @request_with_active_session
    @request_with_errors
    @request_with_logging
    async def _get_request_with_logging_and_errors_raised(
        self, url: str, headers: dict = None
    ) -> ClientResponse:
        return await self.api_session.get(url=url, headers=headers)

    @request_with_active_session
    @request_with_errors
    @request_with_logging
    async def _post_request_with_logging_and_errors_raised(
        self, url: str, json_body: dict = None, form_data: FormData = None, headers: dict = None
    ) -> ClientResponse:
        return await self.api_session.post(url=url, data=form_data, json=json_body, headers=headers)

    async def refresh_session(self):
        url = f"https://accounts.{AWS_APIKEYS[self.region]['gigyaRegion']}.gigya.com/accounts.login"
        form_data = FormData()
        form_data.add_field("apikey", AWS_APIKEYS[self.region]['apiKey'])
        form_data.add_field("loginID", self.username)
        form_data.add_field("password", self.password)
        form_data.add_field("targetEnv", 'mobile')
        response: ClientResponse = (
            await self._post_request_with_logging_and_errors_raised(
                url=url, form_data=form_data
            )
        )
        response_json = await response.json(content_type="text/javascript")
        self.session_token = response_json["sessionInfo"]["sessionToken"]
        self.session_secret = response_json["sessionInfo"]["sessionSecret"]

    async def refresh_jwt(self):
        if self.session_token is None or self.session_secret is None:
            await self.refresh_session()
        url = f"https://accounts.{AWS_APIKEYS[self.region]['gigyaRegion']}.gigya.com/accounts.getJWT";
        form_data = FormData()
        form_data.add_field("oauth_token", self.session_token)
        form_data.add_field("secret", self.session_secret)
        form_data.add_field("targetEnv", 'mobile')
        response: ClientResponse = (
            await self._post_request_with_logging_and_errors_raised(
                url=url, form_data=form_data
            )
        )
        response_json = await response.json(content_type="text/javascript")
        self.jwt = response_json["id_token"]

    async def refresh_access_token(self):
        if self.jwt is None:
            await self.refresh_jwt()
        url = f"https://{AWS_APIKEYS[self.region]['restApiId']}.execute-api.{AWS_APIKEYS[self.region]['awsRegion']}.amazonaws.com/prod/c/login"
        headers = {
          "idtoken": self.jwt
        }
        response: ClientResponse = (
            await self._post_request_with_logging_and_errors_raised(
                url=url, headers=headers
            )
        )
        response_json = await response.json()
        self.access_token = response_json['access_token']

    async def get_access_token(self):
        if self.access_token is None:
            await self.refresh_access_token()
        return self.access_token

    async def devices(self):
        url = f"https://{AWS_APIKEYS[self.region]['restApiId']}.execute-api.{AWS_APIKEYS[self.region]['awsRegion']}.amazonaws.com/prod/c/registered-devices"
        headers = {
            'Authorization': f"Bearer {await self.get_access_token()}",
        }
        response: ClientResponse = (
            await self._get_request_with_logging_and_errors_raised(
                url=url, headers=headers
            )
        )
        response_json = await response.json()
        return response_json["devices"]

    async def device_info(self, device_name, device_uuid):
        """
        sample; [{'id': '1b41a7c6-8f02-42fa-9af8-868dad9be98a', 'configuration': {'df': {'a': 877, 'ot': 'G4Filter', 'alg': 'FilterAlg1'}, 'di': {'cfv': '2.1.1', 'cma': '3c:61:05:45:56:98', 'mt': '2', 'name': 'sage', 'sku': '105826', 'mfv': '1.0.12', 'ofv': '2.1.1', 'hw': 'high_1.5', 'ds': '110582600000110110016855'}, '_ot': 'CmConfig', '_f': False, '_it': 'urn:blueair:openapi:version:healthprotect:0.0.5', '_eid': 'f8cb142f-c77d-11eb-b045-c98ff4f5a769', '_sc': 'Instance', 'ds': {'tVOC': {'tf': 'senml+json', 'ot': 'TVOC', 'e': True, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/tVOC', 'ttl': 0, 'n': 'tVOC', 'fe': True}, 'fu0': {'tf': 'senml+json', 'ot': 'FU', 'e': False, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/fu0', 'ttl': -1, 'n': 'fu0', 'fe': True}, 'ledb': {'tf': 'senml+json', 'ot': 'Led', 'e': False, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/ledb', 'ttl': 0, 'n': 'ledb', 'fe': True}, 'co2': {'tf': 'senml+json', 'ot': 'Co2', 'e': False, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/co2', 'ttl': 0, 'n': 'co2', 'fe': True}, 'pm2_5c': {'tf': 'senml+json', 'ot': 'PMParticleCount', 'e': False, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/pm2_5c', 'ttl': 0, 'n': 'pm2_5c', 'fe': True}, 'sb': {'tf': 'senml+json', 'ot': 'Standby', 'e': True, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/sb', 'ttl': -1, 'n': 'sb', 'fe': True}, 'ss0': {'tf': 'senml+json', 'ot': 'SafetySwitch', 'e': True, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/ss0', 'ttl': -1, 'n': 'ss0', 'fe': True}, 'rt1s': {'tf': 'senml+json', 'ot': 'RT1s', 'e': True, 'i': 1000, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/1s', 'sn': ['pm1', 'pm2_5', 'pm10', 't', 'h', 'tVOC', 'rssi'], 'ttl': 0, 'n': 'rt1s', 'fe': True}, 'rt5s': {'tf': 'senml+json', 'ot': 'RT5s', 'e': False, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/5s', 'sn': ['pm1', 'pm2_5', 'pm10', 't', 'h', 'tVOC', 'rssi'], 'ttl': -1, 'n': 'rt5s', 'fe': True}, 'pm1': {'tf': 'senml+json', 'ot': 'PM1', 'e': True, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/pm1', 'ttl': 0, 'n': 'pm1', 'fe': True}, 'pm2_5': {'tf': 'senml+json', 'ot': 'PM2_5', 'e': True, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/pm2_5', 'ttl': 0, 'n': 'pm2_5', 'fe': True}, 'pm10c': {'tf': 'senml+json', 'ot': 'PMParticleCount', 'e': False, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/pm10c', 'ttl': 0, 'n': 'pm10c', 'fe': True}, 'sp': {'tf': 'senml+json', 'ot': 'SensorBoxPresense', 'e': False, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/sp', 'ttl': -1, 'n': 'sp', 'fe': True}, 'rssi': {'tf': 'senml+json', 'ot': 'RSSI', 'e': True, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/rssi', 'ttl': 0, 'n': 'rssi', 'fe': True}, 'chl': {'tf': 'senml+json', 'ot': 'ChildLock', 'e': True, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/chl', 'ttl': -1, 'n': 'chl', 'fe': True}, 'fp0': {'tf': 'senml+json', 'ot': 'FilterPresence', 'e': False, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/fp0', 'ttl': -1, 'n': 'fp0', 'fe': True}, 'pm10': {'tf': 'senml+json', 'ot': 'PM10', 'e': True, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/pm10', 'ttl': 0, 'n': 'pm10', 'fe': True}, 'h': {'tf': 'senml+json', 'ot': 'Humidity', 'e': False, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/h', 'ttl': 0, 'n': 'h', 'fe': True}, 'is': {'tf': 'senml+json', 'ot': 'IonizerState', 'e': False, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/is', 'ttl': -1, 'n': 'is', 'fe': True}, 'gs': {'tf': 'senml+json', 'ot': 'GermShield', 'e': True, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/gs', 'ttl': -1, 'n': 'gs', 'fe': True}, 'am': {'tf': 'senml+json', 'ot': 'AutoMode', 'e': True, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/am', 'ttl': -1, 'n': 'am', 'fe': True}, 'tVOCbaseline': {'t': 0, 'e': False, 'ot': 'TVOCbaseline', 'i': 60000, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/TVOCbaseline', 'ttl': 600, 'n': 'tVOCbaseline', 'fe': True}, 'rt5m': {'tf': 'senml+json', 'ot': 'RT5m', 'e': True, 'i': 300000, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/5m', 'sn': ['pm1', 'pm2_5', 'pm10', 't', 'h', 'tVOC'], 'ttl': 0, 'n': 'rt5m', 'fe': True}, 't': {'tf': 'senml+json', 'ot': 'Temperature', 'e': True, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/t', 'ttl': 0, 'n': 't', 'fe': True}, 'pm1c': {'tf': 'senml+json', 'ot': 'PMParticleCount', 'e': False, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/pm1c', 'ttl': 0, 'n': 'pm1c', 'fe': True}, 'b5m': {'tf': 'senml+json', 'th': ['5kb', '4h'], 'ot': 'Batch5m', 'e': True, 'i': 300000, 'tn': '$aws/rules/telemetry_ingest_rule/d/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/batch/b5m', 'sn': ['pm1', 'pm2_5', 'pm10', 't', 'h', 'tVOC', 'fsp0'], 'ttl': -1, 'n': 'b5m', 'fe': True}, 'fsp0': {'st': 'fsp0', 'tf': 'senml+json', 't': 10, 'ot': 'Fanspeed', 'e': True, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/fsp0', 'sn': ['fsp0'], 'ttl': -1, 'n': 'fsp0', 'fe': True}, 'nm': {'tf': 'senml+json', 'ot': 'NightMode', 'e': True, 'i': 0, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/s/nm', 'ttl': -1, 'n': 'nm', 'fe': True}}, '_r': 'us-east-2', '_s': {'sig': 'f812cd40acae289ad965c159051abadb28ed6c8b1eb2df917fedaa135f5a69d2', 'salg': 'SHA256'}, '_t': 'Diff', '_v': 1655924801, '_cas': 1623062101, '_id': '1b41a7c6-8f02-42fa-9af8-868dad9be98a', 'fc': {'pwd': '9102revreSyrotcaF', 'ssid': 'BAFactory', 'url': ' '}, 'da': {'reboot': {'p': False, 'a': False, 'ot': 'Reboot', 'e': True, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/a/reboot', 'n': 'reboot', 'fe': True}, 'uitest': {'a': 'off', 'ot': 'UiTest', 'e': True, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/a/uitest', 'n': 'uitest', 'fe': True}, 'ledb': {'p': True, 'a': 0, 'tf': 'senml+json', 'ot': 'LedBrightness', 'e': True, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/a/ledb', 'n': 'ledb', 'fe': True}, 'chl': {'p': True, 'a': False, 'tf': 'senml+json', 'ot': 'ChildLock', 'e': True, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/a/chl', 'n': 'chl', 'fe': True}, 'sflu': {'p': False, 'a': False, 'ot': 'SensorFlush', 'e': True, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/a/sflu', 'n': 'sflu', 'fe': True}, 'buttontest': {'p': False, 'a': False, 'ot': 'ButtonTest', 'e': True, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/a/buttontest', 'n': 'buttontest', 'fe': True}, 'is': {'p': True, 'a': False, 'tf': 'senml+json', 'ot': 'IonizerState', 'e': True, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/a/is', 'n': 'is', 'fe': True}, 'gs': {'p': True, 'a': False, 'tf': 'senml+json', 'ot': 'GermShield', 'e': True, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/a/gs', 'n': 'gs', 'fe': True}, 'am': {'p': True, 'a': False, 'tf': 'senml+json', 'ot': 'AutoMode', 'e': True, 'amt': 'PM', 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/a/am', 'n': 'am', 'fe': True}, 'tVOCbaseline': {'a': 0, 'ot': 'TVOCbaseline', 'e': True, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/a/tVOCbaseline', 'n': 'tVOCbaseline', 'fe': True}, 'sb': {'p': True, 'a': False, 'tf': 'senml+json', 'sbt': 'sensor_on', 'ot': 'Standby', 'e': True, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/a/sb', 'n': 'sb', 'fe': True}, 'fsp0': {'p': True, 'st': 'fsp0', 'a': 20, 'tf': 'senml+json', 'ot': 'Fanspeed', 'e': True, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/a/fsp0', 'n': 'fsp0', 'fe': True}, 'nm': {'p': True, 'maxfsp': 25, 'a': False, 'tf': 'senml+json', 'nmt': 'PM', 'ot': 'NightMode', 'ledb': 12, 'e': True, 'tn': 'd/1b41a7c6-8f02-42fa-9af8-868dad9be98a/a/nm', 'n': 'nm', 'fe': True}}, 'dc': {'cfv': {'d': 'di.cfv', 't': 'integer', 'v': 0, 'n': 'cfv'}, 'germshield': {'a': 'gs', 's': 'gs', 't': 'boolean', 'v': False, 'n': 'germshield'}, 'filterusage': {'s': 'fu0', 't': 'integer', 'v': 0, 'n': 'filterusage'}, 'brightness': {'a': 'ledb', 's': 'ledb', 't': 'integer', 'v': 100, 'n': 'brightness'}, 'standby': {'a': 'sb', 's': 'sb', 't': 'boolean', 'v': False, 'n': 'standby'}, 'fanspeed': {'a': 'fsp0', 's': 'fsp0', 't': 'integer', 'v': 11, 'n': 'fanspeed'}, 'nightmode': {'a': 'nm', 's': 'nm', 't': 'boolean', 'v': False, 'n': 'nightmode'}, 'childlock': {'a': 'chl', 's': 'chl', 't': 'boolean', 'v': False, 'n': 'childlock'}, 'safetyswitch': {'s': 'ss0', 't': 'boolean', 'v': True, 'n': 'safetyswitch'}, 'mfv': {'d': 'di.mfv', 't': 'integer', 'v': 0, 'n': 'mfv'}, 'ofv': {'d': 'di.ofv', 't': 'integer', 'v': 0, 'n': 'ofv'}, 'automode': {'a': 'am', 's': 'am', 't': 'boolean', 'v': False, 'n': 'automode'}}}, 'alarms': [], 'events': [], 'sensordata': [{'v': '0', 'n': 'pm1', 't': 1656198091}, {'v': '0', 'n': 'pm2_5', 't': 1656198091}, {'v': '0', 'n': 'pm10', 't': 1656198091}, {'v': '23', 'n': 't', 't': 1656198091}, {'v': '45', 'n': 'h', 't': 1656198091}, {'v': '170', 'n': 'tVOC', 't': 1656198091}, {'v': '11', 'n': 'fsp0', 't': 1656198091}], 'states': [{'n': 'cfv', 'v': 33554689, 't': 1656203510}, {'n': 'germshield', 'vb': True, 't': 1656203510}, {'n': 'filterusage', 'v': 1, 't': 1656203510}, {'n': 'brightness', 'v': 0, 't': 1656203510}, {'n': 'standby', 'vb': False, 't': 1656203510}, {'n': 'fanspeed', 'v': 11, 't': 1656203510}, {'n': 'nightmode', 'vb': False, 't': 1656203510}, {'n': 'childlock', 'vb': False, 't': 1656203510}, {'n': 'safetyswitch', 'vb': True, 't': 1656203510}, {'n': 'mfv', 'v': 16777228, 't': 1656203510}, {'n': 'ofv', 'v': 33554689, 't': 1656203510}, {'n': 'automode', 'vb': False, 't': 1656203510}, {'t': 1656203510, 'vb': True, 'n': 'online'}], 'welcomehome': {'setting': []}, 'fleet_info': []}]

        :param device_name:
        :param device_uuid:
        :return:
        """
        url = f"https://{AWS_APIKEYS[self.region]['restApiId']}.execute-api.{AWS_APIKEYS[self.region]['awsRegion']}.amazonaws.com/prod/c/{device_name}/r/initial"
        headers = {
            'Authorization': f"Bearer {await self.get_access_token()}",
        }
        json_body = {
          "deviceconfigquery": [
            {
              "id": device_uuid,
              "r": {
                "r": [
                  "sensors",
                ],
              },
            },
          ],
          "includestates": True,
          "eventsubscription": {
            "include": [
              {
                "filter": {
                  "o": f"= {device_uuid}",
                },
              },
            ],
          },
        }
        response: ClientResponse = (
            await self._post_request_with_logging_and_errors_raised(
                url=url, headers=headers, json_body=json_body
            )
        )
        response_json = await response.json()
        return response_json["deviceInfo"][0]

    async def set_device_info(self, device_uuid, service_name, action_verb, action_value):
        url = f"https://{AWS_APIKEYS[self.region]['restApiId']}.execute-api.{AWS_APIKEYS[self.region]['awsRegion']}.amazonaws.com/prod/c/{device_uuid}/a/{service_name}"
        headers = {
            'Authorization': f"Bearer {await self.get_access_token()}",
        }
        json_body = {
            "n": service_name,
            action_verb: action_value
        }
        response: ClientResponse = (
            await self._post_request_with_logging_and_errors_raised(
                url=url, headers=headers, json_body=json_body
            )
        )
        response_text = await response.text()
        return response_text == "Success"
