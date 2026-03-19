#!/usr/bin/env python

"""
EIC Client Interface module.

Based on code for ONCat client by Peter Parker.
Modified to support EIC by Ray Gregory.

-----------------------------------------------------------------------------------------------------------------------
There are three main parts to this code:

    * EICClientAuthComm class: for making EIC-related http/https calls with OAuth authentication.

    * EICClientComm class: for making EIC-related http/https calls without OAuth authentication. This is for testing
        ping endpoints, etc. 
        
    * EICClient class: main class for user interaction with EIC.
-----------------------------------------------------------------------------------------------------------------------
"""

import os
import sys
import warnings
import argparse
import traceback
import re
import pickle
import zlib
import base64
import json
import copy
import subprocess
# noinspection PyUnresolvedReferences
import pkg_resources

# noinspection PyUnresolvedReferences
import urllib3
# noinspection PyUnresolvedReferences
import requests
# noinspection PyUnresolvedReferences
import requests_oauthlib
# noinspection PyUnresolvedReferences
import oauthlib

# noinspection PyUnresolvedReferences
from cryptography.fernet import Fernet

# noinspection PyUnresolvedReferences
from requests.packages.urllib3.exceptions import InsecureRequestWarning

# Disable InsecureRequestWarning in urllib3.
# noinspection PyUnresolvedReferences
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

use_https_in_production = True
# default_eic_ssl_port = '443'
default_eic_ssl_port = '8443'

default_url_base_dev = "http://127.0.0.1:5000"

default_ping_fed_host_url = "https://extidp.ornl.gov/as/token.oauth2"
default_system_openssl_path = '/bin/openssl'

# Some clients (e.g., my Windows desktop) are not supposed to connect via proxy.
# Identify these according to environment variables so as to properly define
# the proxies dict.

https_proxy = os.getenv('https_proxy')
if https_proxy == "":
    https_proxy = None

http_proxy = os.getenv('http_proxy')
if http_proxy == "":
    http_proxy = None

no_proxy = os.getenv('no_proxy')
if no_proxy == "":
    no_proxy = None

if no_proxy:
    http_proxy = None
    https_proxy = None

proxies = {
    "http": http_proxy,
    "https": https_proxy
}

if use_https_in_production:
    default_verify_ssl = True
else:
    default_verify_ssl = False


class EICClientError(Exception):
    def __init__(self, message=None, original_error=None):
        if not message:
            message = ""
        # noinspection PyBroadException
        try:
            message += " [" + original_error.response.json()["message"] + "]"
        except Exception:
            pass
        super(EICClientError, self).__init__(message)
        self.original_error = original_error


class UnauthorizedError(EICClientError):
    pass


class InvalidClientCredentialsError(EICClientError):
    pass


class InvalidUserCredentialsError(EICClientError):
    pass


class InvalidRefreshTokenError(EICClientError):
    pass


class LoginRequiredError(EICClientError):
    pass


class NotFoundError(EICClientError):
    pass


class BadRequestError(EICClientError):
    pass

# ----------------------------------------------------------------------------------------------------------------------


class EICClientAuthComm(object):
    """
    Class for EIC client communications with authentication.
    """
    def __init__(
        self,
        eic_base_url,
        ping_fed_url,
        client_id=None,
        client_secret=None,
        token_getter=None,
        token_setter=None,
        api_token=None,
        scopes=None,
        verify=True,
        timeout=None
    ):
        self._token_getter = token_getter
        self._token_setter = token_setter

        self._api_token = api_token
        self._client_id = client_id
        self._client_secret = client_secret
        self._eic_base_url = eic_base_url
        self._ping_fed_url = ping_fed_url
        self._scopes = scopes
        self._verify = verify
        self._timeout = timeout

        self._token = None
        self._oauth_client = None

    def get(self, url, **kwargs):
        return self._call_method("get", url, None, **kwargs)

    def put(self, url, data, **kwargs):
        result = self._call_method("put", url, data, **kwargs)

        # Not all resources will return a confirmation representation.
        return result if result != "" else None

    def post(self, url, data, **kwargs):
        return self._call_method("post", url, data, **kwargs)

    def delete(self, url, **kwargs):
        self._call_method("delete", url, None, **kwargs)

    def _call_method(self, method, url, data, **kwargs):
        # noinspection PyUnresolvedReferences
        url = requests.utils.quote(url)
        url_sep = "/" if not url.startswith("/") else ""
        full_url = self.eic_base_url() + url_sep + url
        # print(f'\n\nIn EICClientComm._call_method().\n'
        #       f'self.eic_base_url() = {self.eic_base_url()} url = {url} full_url = {full_url}\n\n')
        # print(f"\n\nIn EICClientAuthComm._call_method(). eic_base_url: {self.eic_base_url()} full_url: {full_url}\n\n")

        def send_request():
            if use_https_in_production and self._client_id:
                do_verify = self.should_verify()
                client = self.oauth_client()
                response = getattr(client, method)(
                    full_url,
                    params=kwargs,
                    json=data,
                    verify=do_verify,
                    # verify=False,
                    timeout=self._timeout,
                )
            else:
                response = getattr(requests, method)(
                    full_url,
                    params=kwargs,
                    json=data,
                    # verify=do_verify,
                    verify=False,
                    headers={"Authorization": f"Bearer {self._api_token}"} if self._api_token else None,
                    timeout=self._timeout,
                )
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as send_error:
                if send_error.response.status_code == 400:
                    raise BadRequestError("Bad request", original_error=send_error)
                if send_error.response.status_code == 401:
                    raise UnauthorizedError(f'Not authorized to access "{full_url}"', original_error=send_error)
                if send_error.response.status_code == 404:
                    raise NotFoundError(f'Could not find resource at "{full_url}"', original_error=send_error)
                raise EICClientError(f'Error: "{send_error}"', original_error=send_error)

            return response

        # noinspection PyUnresolvedReferences
        try:
            return send_request()
        except oauthlib.oauth2.rfc6749.errors.InvalidGrantError as error:
            raise EICClientError('Error: "%s"' % str(error), original_error=error)
        except oauthlib.oauth2.TokenExpiredError:
            self.login()
            return send_request()

    def oauth_client(self):
        if not self._oauth_client:
            self.login()

        return self._oauth_client

    def get_token(self):
        if self._token_getter is not None:
            return self._token_getter()

        return self._token

    def set_token(self, token):
        if self._token_setter is not None:
            self._token_setter(token)
        else:
            self._token = token

    def should_verify(self):
        if self._verify:
            do_verify = (
                "localhost" not in self.eic_base_url()
                and "load-balancer" not in self.eic_base_url()
                and "proxy" not in self.eic_base_url())

            # print(f'\n\nIn EICClientAuthComm.should_verify(). do_verify = {do_verify}\n\n')
            if not do_verify:
                # Ignore invalid certs and lack of SSL for OAuth if
                # deploying locally.
                # noinspection PyUnresolvedReferences
                requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
                os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

        else:
            do_verify = False

        return do_verify

    def eic_base_url(self):
        return self._eic_base_url

    def ping_fed_url(self):
        return self._ping_fed_url

    def login(self):
        self._login_client_credentials()

    def _retrieve_client_credentials_token(self):
        grant_type = "client_credentials"

        response = requests.post(
            self.ping_fed_url(),
            data={
                "grant_type": grant_type,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": self._scopes
            },
            proxies=proxies
        )
        response.raise_for_status()

        return response.json()

    def _login_client_credentials(self):
        # print('\n\nIn _login_client_credentials(). Checkpoint 1\n\n')
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning)
            # noinspection PyUnresolvedReferences
            self._oauth_client = requests_oauthlib.OAuth2Session(
                client=oauthlib.oauth2.BackendApplicationClient(
                    client_id=self._client_id,
                    client_secret=self._client_secret,
                    scope=self._scopes,
                ),
                scope=self._scopes,
            )
        # print('\n\nIn _login_client_credentials(). Checkpoint 2\n\n')
        # noinspection PyUnresolvedReferences
        try:
            token = self._oauth_client.fetch_token(
                self.ping_fed_url(),
                auth=False,
                client_id=self._client_id,
                client_secret=self._client_secret,
                include_client_id=True,
                verify=self.should_verify(),
                scope=self._scopes,
                timeout=self._timeout,
                proxies=proxies
            )
            # print('\n\nIn _login_client_credentials(). Checkpoint 3\n\n')
        except oauthlib.oauth2.rfc6749.errors.InvalidClientError as error:
            e = sys.exc_info()
            error_message = f"ERROR in _login_client_credentials(): {e}"
            print(f'\n\n{error_message}\n\n')
            raise InvalidClientCredentialsError(
                    "You seem to have provided some invalid client "
                    "credentials.  Are you sure they are correct?",
                    original_error=error)

        self.set_token(token)


# ----------------------------------------------------------------------------------------------------------------------

class EICClientComm(object):
    """
    Class for EIC Client communication without OAuth authentication.
    """
    def __init__(self, eic_base_url, timeout=None, verify=True):

        self._eic_base_url = eic_base_url
        self._timeout = timeout
        self._verify = verify

    def get(self, url, **kwargs):
        return self._call_method("get", url, None, **kwargs)

    def put(self, url, data, **kwargs):
        result = self._call_method("put", url, data, **kwargs)

        # Not all resources will return a confirmation representation.
        return result if result != "" else None

    def post(self, url, data, **kwargs):
        return self._call_method("post", url, data, **kwargs)

    def delete(self, url, **kwargs):
        self._call_method("delete", url, None, **kwargs)

    def _call_method(self, method, url, data, **kwargs):
        # noinspection PyUnresolvedReferences
        url = requests.utils.quote(url)
        url_sep = "/" if not url.startswith("/") else ""
        full_url = self.eic_base_url() + url_sep + url

        # print(f"\n\nIn EICClientComm._call_method(). full_url: {full_url}\n\n")

        def send_request():
            response = getattr(requests, method)(
                full_url,
                params=kwargs,
                json=data,
                timeout=self._timeout,
                verify=self._verify)
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as send_error:
                if send_error.response.status_code == 400:
                    raise BadRequestError("Bad request", original_error=send_error)
                if send_error.response.status_code == 401:
                    raise UnauthorizedError(f'Not authorized to access "{full_url}"', original_error=send_error)
                if send_error.response.status_code == 404:
                    raise NotFoundError(f'Could not find resource at "{full_url}"', original_error=send_error)
                raise EICClientError(f'Error: "{send_error}"', original_error=send_error)

            return response

        # noinspection PyUnresolvedReferences
        try:
            return send_request()
        except oauthlib.oauth2.rfc6749.errors.InvalidGrantError as error:
            raise EICClientError('Error: "%s"' % str(error), original_error=error)

    def eic_base_url(self):
        return self._eic_base_url

# ----------------------------------------------------------------------------------------------------------------------


class EICClient(object):
    """
    Main user class for EIC Client interaction.
    """

    read_scope = ['EIC:read']
    write_scope = ['EIC:write']

    def __init__(self, eic_token, ipts_number=None, beamline=None, url_base=None, ping_fed_host_url=None,
                 system_openssl_path=None, verify_ssl=None, eic_ssl_port=None):
        """
        EICClient constructor

        :param eic_token: EIC token
        :param ipts_number: IPTS number
        :param beamline: beamline
        :param url_base: url base (e.g., "https://hb2c-dassrv1.ornl.gov:8443")
        :param ping_fed_host_url: PING FED URL to use for authentication
            (e.g., "https://extidp.ornl.gov/as/token.oauth2")
        :param system_openssl_path: path to system openssl (defaults to '/bin/openssl'
        :param verify_ssl: whether to verify SSL
        :param eic_ssl_port: EIC IP port for SSL

        """
        self.is_production_environment = self._is_production_environment()
        # print(f'\n\nIn EICClient.__init__(). is_production_environment = {self.is_production_environment}\n\n')

        self.eic_token = eic_token

        if ipts_number is None:
            ipts_number = ''
        self.ipts_number = ipts_number
        self.outer_data, self.outer_decrypt_error = self._deserialize_outer_data()

        if beamline is None:
            beamline = self.outer_data.get('beamline')
        if url_base is None:
            url_base = self.outer_data.get('url_base')
        self.client_id = self.outer_data.get('client_id')
        self.client_secret = self.outer_data.get('client_secret')
        self.inner_token = self.outer_data.get('inner_token')

        if not beamline:
            beamline = 'BL201'
        self.beamline = beamline

        if not eic_ssl_port:
            eic_ssl_port = default_eic_ssl_port
        self.eic_ssl_port = str(eic_ssl_port)

        if not url_base:
            url_base = self._get_url_base()
        self.url_base = url_base

        # print(f'\n\nIn EICClient.__init__(). url_base = {self.url_base}\n\n')

        if ping_fed_host_url is None:
            ping_fed_host_url = default_ping_fed_host_url
        self.ping_fed_host_url = ping_fed_host_url

        if system_openssl_path is None:
            system_openssl_path = default_system_openssl_path
        self.system_openssl_path = system_openssl_path

        if verify_ssl is None:
            verify_ssl = default_verify_ssl
        self.verify_ssl = verify_ssl

        self.platform_str = None
        self.is_linux = False
        self.is_macos = False
        self.is_windows = False
        self._get_platform_info()

        self.pip_systems_certs_is_installed = self._is_pip_system_certs_installed()

        if self.is_production_environment:
            self._set_sll_crt_file()
        else:
            # Need to set this if we are doing testing without https.
            os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = "1"

    def _deserialize_outer_data(self, handle_exceptions=True):
        """
        Deserialize a serialized base64 data string to Python data.

        :param handle_exceptions: whether to handle exceptions

        :return: deserialized data and error (None if no error)
        """

        # Fernet outer key.
        outer_key = b'R-2xj4mOi7UxjC7fR119FD5aw_GCfN4IZYlGn41XUxU='
        outer_fernet = Fernet(outer_key)
        outer_id_plaintext = outer_fernet.decrypt(bytes(self.eic_token, 'utf8'))

        error = None
        outer_data = None
        # noinspection PyBroadException
        try:
            if outer_id_plaintext:
                ser_str = self._get_serialized_data_as_string(outer_id_plaintext)
                compressed_data = base64.b64decode(ser_str)
                pickled_data = zlib.decompress(compressed_data)
                outer_data = pickle.loads(pickled_data)
        except:
            if handle_exceptions:
                first_char = outer_id_plaintext[0] if (outer_id_plaintext is not None and (len(outer_id_plaintext) > 0)) else ''
                log_message = f"Exception in EICClient._deserialize_outer_data() serialized data: [{outer_id_plaintext}]" \
                              f" type: {type(outer_id_plaintext)} 1st char: {first_char}"
                error = self._log_exception(log_message)
            else:
                raise

        if error is not None:
            outer_data = {}
        return outer_data, error

    @staticmethod
    def _get_serialized_data_as_string(serialized_data):
        """
        If this is Python 2 reading data serialized in Python 3, then serialized data will be a byte string
        of the form b'*'. In this case, this function returns *, otherwise the serialized data is returned.

        :param serialized_data: serialized data

        :return: serialized data as a string.
        """
        if len(serialized_data) > 2 and serialized_data[0] == 'b' \
                and serialized_data[1] == "'" and serialized_data[-1] == "'":
            ser_str = eval(serialized_data)
        else:
            ser_str = serialized_data
        return ser_str

    @staticmethod
    def _log_exception(log_message):
        """
        Log exception.

        :param log_message: log message

        :return: exception message
        """
        exc_type, exc_value, exc_traceback = sys.exc_info()
        traceback_str = ''.join(list(traceback.format_tb(exc_traceback)))
        # exception_message = f"MESSAGE:\n{log_message}\nEND MESSAGE\n" \
        #                     f"EXCTYPE:\n{exc_type}\nEND EXCTYPE\n" \
        #                     f"EXCVALUE:\n{exc_value}\nEND EXCVALUE\n" \
        #                     f"TRACEBACK:\n{traceback_str}\nEND TRACEBACK\n"
        exception_message = f"{log_message} (Type: {exc_type}):\n{exc_value}\n{traceback_str}"
        print(f"EXCEPTION: {exception_message}")
        return exc_value

    @staticmethod
    def _get_now_beamline_and_web_server(beamline_ini):
        """
        Get nED-on-Wheels beamline and web server if applicable.

        :param beamline_ini: beamline initial string

        :return: resulting beamline and web server
        """
        beamline_result = None
        web_server = None
        search_str = r"^bl-?0([a-z])$"
        search_result = re.search(search_str, beamline_ini)
        if search_result:
            match = search_result.groups()
            beamline_result = f'bl0{match[0]}'
            facility = 'ornl' if (match[0] in ['e']) else 'sns'
            web_server = f'{beamline_result}-now1.{facility}.gov'
        return beamline_result, web_server

    @staticmethod
    def _get_rgb_dev_beamline_and_web_server(beamline_ini):
        """
        Get rgb-dv beamline and web server if applicable.

        :param beamline_ini: beamline initial string

        :return: resulting beamline and webserver
        """
        beamline_result = None
        web_server = None
        if beamline_ini in ['bl200', 'bl201']:
            beamline_result = beamline_ini
            dev_num = '1' if beamline_ini == 'bl200' else '2'
            web_server = f'rgb-dev-dassrv{dev_num}.ornl.gov'
        return beamline_result, web_server

    @staticmethod
    def _get_test_beamline_and_web_server(beamline_ini):
        """
        Get test beamline and web server if applicable.

        :param beamline_ini: beamline initial string

        :return: resulting beamline and webserver
        """
        beamline_result = None
        web_server = None
        if beamline_ini in ['bl100', 'bl104']:
            beamline_result = beamline_ini
            facility = 'ornl' if (beamline_ini in ['bl104']) else 'sns'
            web_server = f'{beamline_result}-dassrv1.{facility}.gov'
        return beamline_result, web_server

    @staticmethod
    def _get_hfir_beamline_and_web_server(beamline_ini):
        """
        Get HFIR beamline and web server if applicable.

        :param beamline_ini: beamline initial string

        :return: resulting beamline and web server
        """
        beamline_result = None
        web_server = None

        if beamline_ini in ['hb1a', 'hb-1a']:
            beamline_result = 'hb1a'
        elif beamline_ini in ['hb1', 'hb-1']:
            beamline_result = 'hb1'
        elif beamline_ini in ['hb2a', 'hb-2a', 'powder']:
            beamline_result = 'hb2a'
        elif beamline_ini in ['hb2b', 'hb-2b', 'residual stress', 'residual-stress', 'hidra']:
            beamline_result = 'hb2b'
        elif beamline_ini in ['hb2c', 'hb-2c', 'wand', 'wand2']:
            beamline_result = 'hb2c'
        elif beamline_ini in ['hb2d', 'hb-2d']:
            beamline_result = 'hb2d'
        elif beamline_ini in ['hb3', 'hb-3']:
            beamline_result = 'hb3'
        elif beamline_ini in ['hb3a', 'hb-3a', 'four circle', 'four-circle', 'demand']:
            beamline_result = 'hb3a'
        elif beamline_ini in ['cg1a', 'cg-1a']:
            beamline_result = 'cg1a'
        elif beamline_ini in ['cg1c', 'cg-1c']:
            beamline_result = 'cg1c'
        elif beamline_ini in ['cg1d', 'cg-1d', 'imaging']:
            beamline_result = 'cg1d'
        elif beamline_ini in ['cg2', 'cg-2', 'gp sans', 'gpsans', 'gp-sans']:
            beamline_result = 'cg2'
        elif beamline_ini in ['cg3', 'cg-3', 'bio sans', 'biosans', 'bio-sans']:
            beamline_result = 'cg3'
        elif beamline_ini in ['cg4a', 'cg-4a']:
            beamline_result = 'cg4a'
        elif beamline_ini in ['cg4b', 'cg-4b']:
            beamline_result = 'cg4b'
        elif beamline_ini in ['cg4c', 'cg-4c', 'ctax']:
            beamline_result = 'cg4c'
        elif beamline_ini in ['cg4d', 'cg-4d', 'imagine']:
            beamline_result = 'cg4d'

        if beamline_result is not None:
            web_server = f'{beamline_result}-dassrv1.ornl.gov'
        return beamline_result, web_server

    @staticmethod
    def _get_sns_beamline_and_web_server(beamline_ini):
        """
        Get SNS beamline and web server if applicable.

        :param beamline_ini: beamline initial string

        :return: resulting beamline and web server
        """
        beamline_result = None
        web_server = None

        if beamline_ini in ['bl1a', 'bl-1a', 'usans', 'u-sans', 'u sans']:
            beamline_result = 'bl1a'
        elif beamline_ini in ['bl1b', 'bl-1b', 'nomad']:
            beamline_result = 'bl1b'
        elif beamline_ini in ['bl2', 'bl-2', 'basis']:
            beamline_result = 'bl2'
        elif beamline_ini in ['bl3', 'bl-3', 'snap']:
            beamline_result = 'bl3'
        elif beamline_ini in ['bl4a', 'bl-4a', 'ref-m']:
            beamline_result = 'bl4a'
        elif beamline_ini in ['bl4b', 'bl-4b', 'ref-l']:
            beamline_result = 'bl4b'
        elif beamline_ini in ['bl5', 'bl-5', 'cncs']:
            beamline_result = 'bl5'
        elif beamline_ini in ['bl6', 'bl-6', 'eqsans', 'eq sans' 'eq-sans']:
            beamline_result = 'bl6'
        elif beamline_ini in ['bl7', 'bl-7', 'vulcan']:
            beamline_result = 'bl7'
        elif beamline_ini in ['bl9', 'bl-9', 'corelli']:
            beamline_result = 'bl9'
        elif beamline_ini in ['bl10', 'bl-10', 'venus']:
            beamline_result = 'bl10'
        elif beamline_ini in ['bl11a', 'bl-11a', 'powgen']:
            beamline_result = 'bl11a'
        elif beamline_ini in ['bl11b', 'bl-11b', 'mandi']:
            beamline_result = 'bl11b'
        elif beamline_ini in ['bl12', 'bl-12', 'topaz']:
            beamline_result = 'bl12'
        elif beamline_ini in ['bl13', 'bl-13', 'fnpb']:
            beamline_result = 'bl13'
        elif beamline_ini in ['bl14b', 'bl-14b', 'hyspec']:
            beamline_result = 'bl14b'
        elif beamline_ini in ['bl15', 'bl-15', 'nse', 'spin echo', 'spin-echo']:
            beamline_result = 'bl15'
        elif beamline_ini in ['bl16b', 'bl-16b', 'vision']:
            beamline_result = 'bl16b'
        elif beamline_ini in ['bl17', 'bl-17', 'sequoia']:
            beamline_result = 'bl17'
        elif beamline_ini in ['bl18', 'bl-18', 'arcs']:
            beamline_result = 'bl18'

        if beamline_result is not None:
            web_server = f'{beamline_result}-dassrv1.sns.gov'
        return beamline_result, web_server

    def _get_beamline_and_web_server(self, beamline_or_inst_name):
        """
        Get beamline name and web_server name from beamline or instrument name.

        :param beamline_or_inst_name: beamline or instrument name
        :return: beamline name and web server
        """
        beamline = beamline_or_inst_name.lower().strip()
        web_server = None

        # Check for nED-on-Wheels system.
        beamline_result, web_server_result = self._get_now_beamline_and_web_server(beamline)
        if beamline_result is not None:
            beamline = beamline_result
            web_server = web_server_result
        else:

            # Check for test beamline system.
            beamline_result, web_server_result = self._get_test_beamline_and_web_server(beamline)
            if beamline_result is not None:
                beamline = beamline_result
                web_server = web_server_result
            else:

                # Check for rgb dev VM system.
                beamline_result, web_server_result = self._get_rgb_dev_beamline_and_web_server(beamline)
                if beamline_result is not None:
                    beamline = beamline_result
                    web_server = web_server_result
                else:

                    # Check for HFIR beamline.
                    beamline_result, web_server_result = self._get_hfir_beamline_and_web_server(beamline)
                    if beamline_result is not None:
                        beamline = beamline_result
                        web_server = web_server_result
                    else:

                        # Check for SNS beamline.
                        beamline_result, web_server_result = self._get_sns_beamline_and_web_server(beamline)
                        if beamline_result is not None:
                            beamline = beamline_result
                            web_server = web_server_result
                        else:
                            # No valid beamline identified.
                            pass

        return beamline, web_server

    def _get_url_base(self):
        if self.is_production_environment:
            bl_processed, web_server = self._get_beamline_and_web_server(self.beamline)

            if use_https_in_production:
                if web_server is not None:
                    url_base = f'https://{web_server}:{self.eic_ssl_port}'
                else:
                    # Can't identify web server for beamline.
                    url_base = f'https://unidentified-for-beamline-{bl_processed}.ornl.gov:{self.eic_ssl_port}'
            else:
                if web_server is not None:
                    url_base = f'http://{web_server}'
                else:
                    # Can't identify web server for beamline.
                    url_base = f'http://unidentified-for-beamline-{bl_processed}.ornl.gov'
        else:
            url_base = default_url_base_dev

        return url_base

    def _get_platform_info(self):
        """
        Gets platform info (i.e., what OS)
        """

        self.platform_str = sys.platform.lower()
        self.is_linux = 'linux' in self.platform_str
        self.is_macos = 'darwin' in self.platform_str
        self.is_windows = 'win32' in self.platform_str

    @staticmethod
    def _is_pip_system_certs_installed():
        """
        Determine whether pip-system-certs package is installed.

        :return: whether pip-system-certs package is installed.
        """
        is_installed = False
        pkg_txt = 'pip-system-certs'
        for pkg in pkg_resources.working_set:
            # print(f'\n\nIn _is_pip_system_certs_installed().\npkg = {pkg}\n\n')
            if pkg_txt in str(pkg):
                is_installed = True
                break
        # print(f'\n\nIn _is_pip_system_certs_installed().\nis_installed = {is_installed}\n\n')
        return is_installed

    @staticmethod
    def _is_production_environment():
        is_production_environment = True
        eic_env_var_name = 'EIC_ENV'
        # noinspection PyBroadException
        try:
            eic_env = os.environ[eic_env_var_name]
            # print(f'\n\nIn EICClient._is_production_environment().'
            #       f' env {eic_env_var_name} = ({eic_env}) type(eic_env) = {type(eic_env)}\n\n')
            if eic_env == 'dev':
                is_production_environment = False
        except:
            # On exception presume production.
            # e = sys.exc_info()
            # error_message = f"ERROR In EICClient._is_production_environment(); presuming production environment." \
            #                 f" (env={eic_env_var_name}): {e}"
            # print(f'\n\n{error_message}\n\n')
            pass
        return is_production_environment

    # noinspection PyMethodMayBeStatic
    def _use_ssl_unverified_context(self):
        # noinspection PyBroadException
        try:
            import ssl
            # print(f"\n\nIn EICClient._use_ssl_unverified_context(). platform string {self.platform_str}\n\n")
            # noinspection PyUnresolvedReferences,PyProtectedMember
            ssl._create_default_https_context = ssl._create_unverified_context
        except:
            e = sys.exc_info()
            error_message = f"ERROR in EIClient._use_ssl_unverified_context(): {e}"
            print(f'\n\n{error_message}\n\n')
            traceback.print_exc(limit=50, file=sys.stdout)

    @staticmethod
    def _find_pem_file(directory_path):
        """
        Finds first .pem file in specified directory.
    
        :param directory_path: directory path
        :return:
        """
        for file in os.listdir(directory_path):
            if file.endswith(".pem"):
                full_filename = os.path.join(directory_path, file)
                if os.path.isfile(full_filename):
                    return full_filename
        return None

    # noinspection PyMethodMayBeStatic
    def _install_certificates(self):
        """
        Install certificates (for macOS).

        (based on https://github.com/python/cpython/blob/main/Mac/BuildScript/resources/install_certificates.command)
        """
        # print(f"\n\nIn EICClient._install_certificates(). macOS? {self.is_macos}\n\n")
        if self.is_macos:
            # noinspection PyBroadException
            try:
                # noinspection PyUnresolvedReferences
                import certifi
                import stat
                import ssl

                stat_0o775 = (stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
                              | stat.S_IRGRP | stat.S_IWGRP | stat.S_IXGRP
                              | stat.S_IROTH | stat.S_IXOTH)

                openssl_dir, openssl_cafile = os.path.split(
                    ssl.get_default_verify_paths().openssl_cafile)

                # change working directory to the default SSL directory
                os.chdir(openssl_dir)
                relpath_to_certifi_cafile = os.path.relpath(certifi.where())
                print(" -- removing any existing file or link")
                try:
                    os.remove(openssl_cafile)
                except FileNotFoundError:
                    pass
                print(" -- creating symlink to certifi certificate bundle")
                os.symlink(relpath_to_certifi_cafile, openssl_cafile)
                print(" -- setting permissions")
                os.chmod(openssl_cafile, stat_0o775)
                print(" -- update complete")
            except:
                e = sys.exc_info()
                error_message = f"ERROR in EIClient._install_certificates(): {e}"
                print(f'\n\n{error_message}\n\n')
                traceback.print_exc(limit=50, file=sys.stdout)

    def _set_sll_crt_file(self, print_results_and_errors=True):
        # noinspection GrazieInspection
        """
            On some systems (e.g., the Python 3.10 conda environment I have been developing with), Python
            (because of an environment-specific install of openssl) doesn't check against the system's normal
            trusted certificates. This can be mitigated by setting the environment variable SSL_CERT_FILE appropriately.
            In order to find the right value to set it to, we run the shell command '/bin/openssl version -d'
            and examine its output. Then we set SSL_CERT_FILE.
    
            :param print_results_and_errors: wither to print results and errors
            """
        # noinspection PyBroadException
        try:
            # Use system's openssl, presumed to be at /bin/openssl
            result = subprocess.run([self.system_openssl_path, 'version', '-d'], stdout=subprocess.PIPE)
            result_str = result.stdout.decode('utf-8')
            search_str = 'OPENSSLDIR: "(.*)"'
            cert_directory = re.search(search_str, result_str).groups()[0]
            cert_file = self._find_pem_file(cert_directory)
            os.environ['SSL_CERT_FILE'] = cert_file
            # print(f'\n\nIn _set_sll_crt_file(). cert_file = {cert_file} cert_directory = {cert_directory}\n\n')
        except:
            e = sys.exc_info()
            error_message = f"ERROR in _set_sll_crt_file(): {e}"
            may_need_setting = self.is_linux
            if may_need_setting and print_results_and_errors:
                print(f'\n\n{error_message}\n\n')
                traceback.print_exc(limit=50, file=sys.stdout)

    def set_system_openssl_path(self, system_openssl_path):
        """
        Set System's openssl path
        (path to system's openssl, for determining location of CRT file)

        :param system_openssl_path: System's openssl path
        """
        self.system_openssl_path = system_openssl_path

    def set_ssl_verify(self, verify_ssl):
        """
        Set whether to verify SSL

        :param verify_ssl: whether to verify SSL
        """
        self.verify_ssl = verify_ssl

    @staticmethod
    def generate_http_response_data(response):
        """
        Generate data from HTTP response.
    
        :param response: HTTP response object.
    
        :return: response data (dict or string)
        """
        response_data = '*** NO DATA RESPONSE ***'
        if isinstance(response, dict):
            response_data = response.get('json', response_data)
        elif isinstance(response, requests.models.Response):
            # print(f'\n\nIn generate_http_response_data().\nvars(response) = {vars(response)}\n\n')
            http_response_status = f'{response.status_code}-{response.reason}'
            if not response.text == '':
                # Generate data from base64-encoded, json string embedded in response.
                resp_raw = response.json()
                json_resp_raw = re.findall(r'response_json\s+(.*)', resp_raw)
                if len(json_resp_raw) > 0:
                    resp_json_base64 = re.findall(r'response_json\s+(.*)', resp_raw)[0]
                    resp_json_bytes = resp_json_base64.encode('utf-8')
                    message_bytes = base64.b64decode(resp_json_bytes)
                    resp_json_str = message_bytes.decode('utf-8')
                    response_data = json.loads(resp_json_str)
                else:
                    response_data = response.text
            if isinstance(response_data, str):
                response_data = {'http_response': response_data}
            if isinstance(response_data, dict):
                response_data['http_response_status'] = http_response_status
        return response_data

    def _check_error_message_for_troubleshooting_clues(self, error_message):
        """
        Check error message for troubleshooting clues.

        This includes:
        *   determining whether the specified error message suggests that the
            pip-system-certs package needs to be installed.
        *   determining if SSL verification failed

        :param error_message: error message

        :return: ssl_cert_verify_failed, and may_need_pip_system_certs
        """
        local_issuer_certificate_msg_fragment = "unable to get local issuer certificate"
        cert_failed_message_snippet = 'certificate verify failed'
        ssl_cert_verify_failed = cert_failed_message_snippet in error_message

        message_fits = (local_issuer_certificate_msg_fragment in error_message) or ssl_cert_verify_failed

        if message_fits and (not self.pip_systems_certs_is_installed) and (not self.is_macos):
            may_need_pip_system_certs = True
        else:
            may_need_pip_system_certs = False

        return ssl_cert_verify_failed, may_need_pip_system_certs

    def _suggest_a_possibly_appropriate_response(self, ssl_cert_verify_failed, may_need_pip_system_certs):
        """
        Suggest a possibly appropriate response to erroneous call.

        :param ssl_cert_verify_failed: whether SSL certificate verification failed.
        :param may_need_pip_system_certs: whether Python environment may need pip-system-certs package.
        """
        if may_need_pip_system_certs:
            print('\n\n*** EIC Client WARNING: It may be necessary to install Python package pip-system-certs.\n\n')
        else:
            if self.verify_ssl:
                if ssl_cert_verify_failed:
                    print('\n\n*** EIC Client WARNING: SSL verification may be inoperative.\n\n')
            else:
                if self.pip_systems_certs_is_installed:
                    print('\n\n*** EIC Client WARNING:'
                          ' It may be necessary to uninstall Python package pip-system-certs.\n\n')

    def http_auth_call_base(self, relative_url, submit_func, data=None, print_traceback_on_exception=False):
        """
        Hit specified HTTP endpoint.
    
        :param relative_url: relative URL
        :param submit_func: Python function to use
        :param data: data for POST submissions
        :param print_traceback_on_exception: whether to print traceback on exception
    
        :return: test results (str), ssl_cert_verify_failed, and may_need_pip_system_certs
        """
        error_key = 'http_error_response'
        ssl_cert_verify_failed = False
        may_need_pip_system_certs = False
        # noinspection PyBroadException
        try:
            relative_url = relative_url
            response = submit_func(relative_url, data)
            response_data = self.generate_http_response_data(response)
        except:
            e = sys.exc_info()
            error_message = f"ERROR in http_auth_call_base(): {str(e[1])}"
            ssl_cert_verify_failed, may_need_pip_system_certs = \
                self._check_error_message_for_troubleshooting_clues(error_message)
            response_data = {error_key: error_message}
            if print_traceback_on_exception:
                traceback.print_exc(limit=50, file=sys.stdout)
    
        return response_data, ssl_cert_verify_failed, may_need_pip_system_certs

    def http_auth_call(self, uri, data, http_method, do_auth=True,
                       scopes=None, print_traceback_on_exception=False):
        """
        Make HTTP call
    
        :param uri: URI
        :param data: data (for PUT and POST calls)
        :param http_method: ('get', 'put', 'post', or 'delete')
        :param do_auth: whether to do authentication
        :param scopes: OAuth scopes (array of strings)
        :param print_traceback_on_exception: whether to print traceback on exception

        :return: response data, ssl_cert_verify_failed, and may_need_pip_system_certs
        """
        if http_method is None or (http_method not in ['get', 'put', 'post', 'delete']):
            http_method = 'post'
    
        if do_auth:
            if scopes is None:
                scopes = []

            # Set inner token and IPTS number.
            if data is not None and isinstance(data, dict):
                data['inner_token'] = self.inner_token
                data['ipts_number'] = self.ipts_number

            # print(f"\n\nIn EICClient.http_auth_call(). {data=}\n\n")

            client_comm = EICClientAuthComm(
                self.url_base,
                self.ping_fed_host_url,
                client_id=self.client_id,
                client_secret=self.client_secret,
                scopes=scopes,
                verify=self.verify_ssl)
        else:
            client_comm = EICClientComm(self.url_base, verify=self.verify_ssl)
    
        def do_client_comm(relative_url, comm_data):
            """
            Do HTTP communication with client authentication token with previously created client comm object.
    
            :param relative_url: relative URL
            :param comm_data: data (for put and post methods)
    
            :return: response
            """
            response = f'No Response for relative_url = {relative_url} and http_method = {http_method}.'
            if http_method == 'get':
                response = client_comm.get(relative_url)
            elif http_method == 'put':
                response = client_comm.put(relative_url, comm_data)
            elif http_method == 'post':
                response = client_comm.post(relative_url, comm_data)
            elif http_method == 'delete':
                client_comm.delete(relative_url)
            return response

        # print(f"\n\nIn EICClient.do_client_comm(). type(client_comm): {type(client_comm)}\n\n")

        # Perform HTTP call.
        response_data, ssl_cert_verify_failed, may_need_pip_system_certs = self.http_auth_call_base(
            uri, submit_func=do_client_comm, data=data, print_traceback_on_exception=print_traceback_on_exception)
        return response_data, ssl_cert_verify_failed, may_need_pip_system_certs

    @staticmethod
    def _get_eic_response_value(response_data, key, default_value=None):
        """
        Get EIC response value from response data.
    
        :param response_data: response data from EIC http call
        :param key: data key
        :param default_value: default value
    
        :return: response value
        """
        """
        Get EIC response value from response data.
    
        :param response_data: response data
    
        :return: whether EIC call was successful
        """
        # noinspection PyBroadException
        try:
            resp_val = response_data.get(key, default_value)
        except:
            e = sys.exc_info()
            error_message = f"ERROR in _get_eic_response_value(): {e}"
            print(f'\n\n{error_message}\n\n')
            traceback.print_exc(limit=50, file=sys.stdout)
            resp_val = default_value
    
        return resp_val
    
    def call_eic_standard(self, eic_command, eic_parms, print_traceback_on_exception=False):
        """
        Make a standard EIC call.
    
        :param eic_command: EIC command (string or None)
        :param eic_parms: EIC parameters (dict or string)
        :param print_traceback_on_exception: whether to print traceback on exception

        :return: response data
        """
        if eic_command is None:
            eic_command = 'EICStatus'
            eic_parms = {}
    
        if isinstance(eic_parms, str):
            eic_parms = eval(eic_parms)
    
        # Submit EIC command: control scenario.
        action_data = {'command': eic_command, 'parameters': eic_parms}
        # print(f'\n\nIn call_eic_standard().\naction_data = {action_data}\n\n')
        response_data, ssl_cert_verify_failed, may_need_pip_system_certs = self.http_auth_call(
            '/eic/actions', action_data, 'post', scopes=self.write_scope,
            print_traceback_on_exception=print_traceback_on_exception)
        success = self._get_eic_response_value(response_data, 'success', default_value=False)
        if not success:
            self._suggest_a_possibly_appropriate_response(ssl_cert_verify_failed, may_need_pip_system_certs)
        return success, response_data

    # noinspection GrazieInspection
    def call_eic_ping_base(self, uri, do_auth=True, scopes=None,
                           print_traceback_on_exception=False, propagate_exceptions=False):
        """
        Query an EIC ping endpoint.
    
        :param uri: endpoint uri
        :param do_auth: whether to do authentication
        :param scopes: authentication scopes
        :param print_traceback_on_exception: whether to print traceback on exception
        :param propagate_exceptions: whether to propagate exceptions

        :return: response data
        """
        error_key = 'http_error_response'
        success_key = 'success'
        success = False
        ssl_cert_verify_failed = False
        may_need_pip_system_certs = False
        response_data = {}
        # noinspection PyBroadException
        try:
            data = None
            raw_response, ssl_cert_verify_failed, may_need_pip_system_certs = self.http_auth_call(
                uri, data, 'get', do_auth=do_auth,
                scopes=scopes, print_traceback_on_exception=False)
            response_data.update(raw_response)
            # print(f'\n\nIn call_eic_ping_base().\nresponse_data = {response_data}\n\n')
            error_response = response_data.get(error_key)
            if error_response is None:
                success = True
        except:
            e = sys.exc_info()
            error_message = f"ERROR in call_eic_ping_base(): {e}"
            response_data = {'error_message': error_message}
            if print_traceback_on_exception:
                traceback.print_exc(limit=50, file=sys.stdout)
            if propagate_exceptions:
                raise Exception(error_message)
    
        response_data[success_key] = success
        if not success:
            self._suggest_a_possibly_appropriate_response(ssl_cert_verify_failed, may_need_pip_system_certs)
        return response_data

    def call_eic_ping(self, print_results=False, propagate_exceptions=False):
        """
        Query EIC unauthenticated endpoint.
    
        :param print_results: whether to print results
        :param propagate_exceptions: whether to propagate exceptions

        :return: response data
        """
        response_data = self.call_eic_ping_base('/eic/ping', do_auth=False, print_traceback_on_exception=print_results,
                                                propagate_exceptions=propagate_exceptions)
    
        if print_results:
            print(f'\nIn call_eic_ping().\n\tresponse_data = {response_data}\n')
    
        return response_data

    def call_eic_ping_authenticated(self, print_results=False, propagate_exceptions=False):
        """
        Query EIC authenticated endpoint with no scope requirement.
    
        :param print_results: whether to print results
        :param propagate_exceptions: whether to propagate exceptions

        :return: response data
        """
        response_data = self.call_eic_ping_base('/eic/ping_authenticated',
                                                print_traceback_on_exception=print_results,
                                                propagate_exceptions=propagate_exceptions)
    
        if print_results:
            print(f'\nIn call_eic_ping_authenticated().\n\tresponse_data = {response_data}\n')
    
        return response_data
    
    def call_eic_ping_authenticated_read_scope(self, scopes=None,
                                               print_results=False, propagate_exceptions=False):
        """
        Query EIC authenticated endpoint with read scope requirement.
    
        :param scopes: override scope
        :param print_results: whether to print results
        :param propagate_exceptions: whether to propagate exceptions

        :return: response data
        """
        # noinspection PyBroadException
        if scopes is None:
            scopes = self.read_scope
        response_data = self.call_eic_ping_base(
            '/eic/ping_authenticated_read_scope', scopes=scopes,
            print_traceback_on_exception=print_results,
            propagate_exceptions=propagate_exceptions)
    
        if print_results:
            print(f'\nIn call_eic_ping_authenticated_read_scope()'
                  f' (using scopes {scopes}).\n\tresponse_data = {response_data}\n')
        return response_data
    
    def call_eic_ping_authenticated_write_scope(self, scopes=None,
                                                print_results=False, propagate_exceptions=False):
        """
        Query EIC authenticated endpoint with write scope requirement.
    
        :param scopes: override scope
        :param print_results: whether to print results
        :param propagate_exceptions: whether to propagate exceptions

        :return: response data
        """
        # noinspection PyBroadException
        if scopes is None:
            scopes = self.write_scope
        response_data = self.call_eic_ping_base(
            '/eic/ping_authenticated_write_scope', scopes=scopes,
            print_traceback_on_exception=print_results,
            propagate_exceptions=propagate_exceptions)
    
        if print_results:
            print(f'\nIn call_eic_ping_authenticated_write_scope() (using scopes {scopes}).'
                  f'\n\tresponse_data = {response_data}\n')
        return response_data
    
    def do_control_scenario(self, control_scenario, control_scenario_parms):
        """
        Perform EIC Control Scenario Operation.

        :param control_scenario: control scenario name
        :param control_scenario_parms: control scenario parameters (dict)
        """
        eic_command = 'ControlScenario'
        eic_parms = {'control_scenario': control_scenario, 'parameters': control_scenario_parms}
        success, response_data = self.call_eic_standard(eic_command, eic_parms)
        return success, response_data

    def submit_table_scan(
            self, parms=None, desc=None, run_mode=None, headers=None, rows=None, simulate_only=None):
        """
        Submit Table Scan 1.

        :param parms: Table Scan parameters (dict containing keys 'run_mode', 'headers', and 'rows')
        :param desc: description
        :param run_mode: run mode (0 = Run per 'Wait', 1 = One Table Run, 2 = No runs, 3 = No runs (parallel))
        :param headers: table headers
        :param rows: table rows
        :param simulate_only: whether to do simulation only

        :return: success, scan ID, and response data
        """
        if desc is None:
            desc = f'EIC Table Scan'
        if parms is None:
            parms = {}
        if run_mode is not None:
            parms['run_mode'] = run_mode
        if headers is not None:
            parms['headers'] = headers
        if rows is not None:
            parms['rows'] = rows
        if simulate_only is not None:
            parms['simulate_only'] = simulate_only

        control_scenario = 'TableScan'
        control_scenario_parms = copy.deepcopy(parms)
        control_scenario_parms['description'] = desc
        success, response_data = self.do_control_scenario(
            control_scenario, control_scenario_parms)
        scan_id = self._get_eic_response_value(response_data, 'scan_id', default_value=-1)
        return success, scan_id, response_data

    def get_scan_status(self, scan_id=None):
        """
        Get Scan Status.

        :param scan_id: scan ID

        :return: success and response data
        """
        control_scenario = 'ScanStatus'
        control_scenario_parms = {}
        if scan_id is not None:
            control_scenario_parms['scan_id'] = scan_id
        success, response_data = self.do_control_scenario(
            control_scenario, control_scenario_parms)
        is_done = self._get_eic_response_value(response_data, 'is_done', default_value=None)
        state = self._get_eic_response_value(response_data, 'state', default_value=None)
        return success, is_done, state, response_data

    def abort_scan(self, scan_id=None):
        """
        Abort specified scan.

        :param scan_id: scan ID

        :return: success and response data
        """
        control_scenario = 'AbortScan'
        control_scenario_parms = {}
        if scan_id is not None:
            control_scenario_parms['scan_id'] = scan_id
        success, response_data = self.do_control_scenario(
            control_scenario, control_scenario_parms)
        return success, response_data

    def set_pv(self, pv_name=None, pv_value=None, timeout=None, wait_for_completion=None):
        """
        Set specified PV to specified value.

        :param pv_name: PV name
        :param pv_value: PV value
        :param timeout: timeout (sec)
        :param wait_for_completion: whether to wait for completion

        :return: success and response data
        """
        control_scenario = 'SetPV'
        control_scenario_parms = {}

        pv_name_key = 'pv_name'
        pv_value_key = 'pv_value'
        wait_for_completion_key = 'wait'
        timeout_key = 'timeout'

        control_scenario_parms[pv_name_key] = pv_name
        control_scenario_parms[pv_value_key] = pv_value
        control_scenario_parms[timeout_key] = timeout
        control_scenario_parms[wait_for_completion_key] = wait_for_completion

        success, response_data = self.do_control_scenario(control_scenario, control_scenario_parms)
        return success, response_data

    def get_pv(self, pv_name=None, timeout=None, parms=None):
        """
        Set specified PV to specified value.

        :param pv_name: PV name
        :param timeout: timeout (sec)
        :param parms: control scenario parameters

        :return: success and response data
        """
        control_scenario = 'GetPV'
        if parms is not None:
            control_scenario_parms = parms
        else:
            control_scenario_parms = {}

        pv_name_key = 'pv_name'
        timeout_key = 'timeout'

        control_scenario_parms[pv_name_key] = pv_name
        control_scenario_parms[timeout_key] = timeout

        success, response_data = self.do_control_scenario(control_scenario, control_scenario_parms)
        pv_value = self._get_eic_response_value(response_data, 'pv_value', default_value=None)
        return success, pv_value, response_data

    def is_eic_enabled(self, print_results=False,
                       disabled_on_exception=True, print_traceback_on_exception=False):
        """
        Determines whether EIC is enabled.
    
        :param print_results: whether to print results
        :param disabled_on_exception: whether to return that EIC is disabled when an exception occurs
            (instead of propagating the exception)
        :param print_traceback_on_exception: whether to print traceback on exception

        :return: whether EIC is enabled
        """
        response_data = 'No valid response.'
        # noinspection PyBroadException
        try:
            eic_command = 'EICStatus'
            eic_parms = {}
    
            success, response_data = self.call_eic_standard(eic_command, eic_parms,
                                                            print_traceback_on_exception=print_traceback_on_exception)
            if not isinstance(response_data, dict):
                raise Exception(f'EIC response data is not a dict:'
                                f' response_data = {response_data} type(response_data) = {type(response_data)}')
            is_enabled = response_data.get('EICEnabled')
            if (success is not None) and success and (is_enabled is not None):
                eic_is_enabled = is_enabled
            else:
                raise Exception(f"EIC call to get EIC status had invalid response. success: {success}; response_data: {response_data}")
        except:
            e = sys.exc_info()
            error_msg = f"ERROR in is_get_eic_enabled(): ERROR in is_eic_enabled(): {str(e[1])}"
            if disabled_on_exception:
                if not print_results:
                    print(f'\n\n{error_msg}\n\n')
                eic_is_enabled = False
            else:
                raise Exception(error_msg)
    
        if print_results:
            qualifier = ' ' if eic_is_enabled else ' NOT '
            print(f'\nDetermined that EIC is{qualifier}enabled.\n\tresponse_data = {response_data}\n')
    
        return eic_is_enabled
    
    
def eic_main():
    """
    Make External Instrument Control (EIC) call using command line arguments.
    """
    parser = argparse.ArgumentParser(description="EIC Client")
    parser.add_argument('--command', help="Command Name", metavar="CMD_NAME")
    parser.add_argument('--key', help="EIC Key", metavar="KEY")
    parser.add_argument('--desc', help="Description", metavar="DESC")
    parser.add_argument('--parameters', help="Command Parameters", metavar="CMD_PARMS", default='{}')
    parser.add_argument('--verify', help="Verify SSL", metavar="VERIFY", default='True')

    args = parser.parse_args()

    eic_command = args.command
    eic_parms = args.parameters
    eic_key = args.key
    if eic_key is None:
        eic_key = ''
    call_description = args.desc
    verify_ssl = args.verify
    eic_client = EICClient(eic_key, verify_ssl=verify_ssl)
    success, response_data = eic_client.call_eic_standard(eic_command, eic_parms)
    print(f'\n\n{call_description}:\n\tsuccess = {success} response_data = {response_data}\n\n')


if __name__ == "__main__":
    # Talk to EIC.
    eic_main()

