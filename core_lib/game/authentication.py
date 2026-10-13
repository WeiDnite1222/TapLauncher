"""
Store all function for Microsoft authentication

WARNING: This module is vibed! With code reviewed!
"""
import logging
import time
import traceback
from typing import Callable

import requests

from core_lib.common.exception import AuthenticationSessionException, AuthenticationConnectException, \
    AuthenticationException, LauncherHTTPException

MICROSOFT_DEVICE_CODE_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
MICROSOFT_TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
XBOX_AUTH_URL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_AUTH_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
MINECRAFT_LOGIN_URL = "https://api.minecraftservices.com/authentication/login_with_xbox"
MINECRAFT_ENTITLEMENTS_URL = "https://api.minecraftservices.com/entitlements/mcstore"
MINECRAFT_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"

logger = logging.getLogger("Launcher.CoreLib")

def auth_exception_handler(request_handler: Callable, request_type: str = "without_token", stage: str = "authentication",):
    """
    Handle authentication exceptions
    :param stage:
    :param request_handler:
    :param request_type: Set this will change exception type when an error occurs. ("without_token" for process that
    don't use token, "with_token" for process that use token. If with token, exception usually throw
    AuthenticationSessionException. If not, throw AuthenticationException instead)
    :return:
    """
    exception_type = (
        AuthenticationSessionException
        if request_type == "with_token"
        else AuthenticationException
    )

    try:
        return request_handler()
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        response_data = {}
        if e.response is not None:
            try:
                value = e.response.json()
                if isinstance(value, dict):
                    response_data = value
            except ValueError:
                pass

        xerr = response_data.get("XErr")
        try:
            xerr = int(xerr) if xerr is not None else None
        except (TypeError, ValueError):
            pass

        # Below are the xsts error code suggestions. Why return that value (error is integer not string) ?
        # Maybe it makes international support more easily?
        xsts_suggestions = {
            2148916233: "This Microsoft account does not have an Xbox profile. Sign in at xbox.com and create one, then try again.",
            2148916235: "Xbox Live is not available for this account's country or region.",
            2148916236: "This account must complete adult verification on the Xbox website.",
            2148916237: "This account must complete age verification on the Xbox website.",
            2148916238: "This is a child account. An adult must add it to a Microsoft family and allow Xbox access.",
        }
        if xerr in xsts_suggestions:
            raise exception_type(
                f"{stage} failed with HTTP {status}, XErr {xerr}",
                user_message=f"{stage} failed (Xbox error {xerr}). {xsts_suggestions[xerr]}",
            ) from e

        server_message = response_data.get("Message") or response_data.get("error_description")
        # This suggestions can make user happy instead of seeing an HTTP error code
        suggestions = {
            400: "The authentication request or session was rejected.",
            401: "The login session is invalid or expired. Sign in again.",
            403: "This account is not allowed to complete this step. Check Xbox privacy settings and account restrictions."
                 " Or check the client id has authorized to use Minecraft API.",
            429: "The authentication service received too many requests. Wait a moment and try again.",
        }

        suggestion = suggestions.get(
            status,
            "The authentication service returned an unexpected response. Try again later.",
        )
        if server_message:
            suggestion = f"{suggestion} Server message: {server_message}"
        raise exception_type(f"{stage} failed with HTTP status {status}: {e}",
            user_message=f"{stage} failed (HTTP {status}). {suggestion}",
        ) from e
    except requests.exceptions.ConnectionError as e:
        raise AuthenticationConnectException(
            f"Unable to connect during {stage}: {e}",
            user_message=f"{stage} could not connect to the authentication server. Check your internet connection, proxy, and firewall.",
        ) from e
    except requests.exceptions.Timeout as e:
        raise AuthenticationConnectException(
            f"Request timed out during {stage}: {e}",
            user_message=f"{stage} timed out. Check your connection and try again later.",
        ) from e
    except requests.exceptions.RequestException as e:
        raise exception_type(
            f"Request error during {stage}: {e}",
            user_message=f"{stage} failed because the authentication request could not be completed: {e}",
        ) from e
    except AuthenticationException:
        raise
    except Exception as e:
        raise exception_type(
            f"Unexpected error during {stage}: {traceback.format_exc()}",
            user_message=f"{stage} failed because the server returned invalid or unexpected data.",
        ) from e


def get_device_code(client_id: str) -> tuple[str, dict]:
    """
    Get xbox live device code
    :param client_id:
    :return:
        device_code: str
        json_data: dict
    """
    def request_handler():
        body = {
            "client_id": client_id,
            "scope": "XboxLive.signin offline_access",
        }
        # Microsoft OAuth endpoints require form-encoded request bodies.
        r = requests.post(MICROSOFT_DEVICE_CODE_URL, data=body)
        r.raise_for_status()

        return r.json()

    data = auth_exception_handler(request_handler, stage="Requesting a Microsoft sign-in code")

    if not data.get("device_code"):
        raise AuthenticationException(
            "Authentication response missing device_code",
            user_message="Microsoft did not return a sign-in code. Check the client ID or update the launcher.",
        )

    return data["device_code"], data

def get_microsoft_token(client_id: str, device_code: str, interval: int, expires_in: float, cancelled=None) -> tuple[str, str, dict]:
    """
    Get microsoft token (with login wait)
    :param client_id:
    :param device_code:
    :param interval:
    :param expires_in:
    :param cancelled:
    :return:
        access_token: str
        refresh_token: str
        json_data: dict
    """
    def _request_handler():
        r = requests.post(MICROSOFT_TOKEN_URL, data={
            "client_id": client_id,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device_code,
        })

        return r.status_code, r.json()

    def verify_data(result: dict) -> tuple[str, str, dict]:
        access_token = result.get("access_token")
        refresh_token = result.get("refresh_token")
        if not access_token:
            raise AuthenticationException(
                "Authentication response missing access_token",
                user_message="Microsoft approved the sign-in but did not return an access token. Please sign in again.",
            )

        if not refresh_token:
            raise AuthenticationException(
                "Authentication response missing refresh_token",
                user_message="Microsoft did not return a refresh token. Ensure the offline_access permission is enabled, then sign in again.",
            )

        return access_token, refresh_token, result

    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        # cancel callback
        if cancelled and cancelled():
            raise InterruptedError("Login cancelled.")

        time.sleep(interval)

        status, data = auth_exception_handler(_request_handler, stage="Waiting for Microsoft sign-in approval")

        if status == 200:
            return verify_data(data)
        error = data.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue

        description = data.get("error_description") or data.get("error") or "No details were provided"
        raise AuthenticationException(
            f"Microsoft token request failed with HTTP {status}: {description}",
            user_message=f"Microsoft sign-in was rejected (HTTP {status}): {description}",
        )

    raise TimeoutError("Microsoft sign-in code expired before login was completed. Start the sign-in process again.")

def get_xbox_token_and_user_hash(access_token: str) -> tuple[str, str, dict]:
    """
    Get xbox live token and user hash
    :param access_token: Microsoft account access token
    :return:
        xbox_token: str
        user_hash: str
        json_data: dict
    """
    def _request_handler():
        r = requests.post(XBOX_AUTH_URL, json={
            "Properties": {
                "AuthMethod": "RPS",
                "SiteName": "user.auth.xboxlive.com",
                "RpsTicket": f"d={access_token}",
            },
            "RelyingParty": "http://auth.xboxlive.com",
            "TokenType": "JWT",
        }, headers={"Accept": "application/json"})
        r.raise_for_status()
        return r.json()

    def verify_data(result: dict) -> tuple[str, str, dict]:
        xbox_token = result.get("Token")
        user_hash = None

        try:
            user_hash = result.get("DisplayClaims", {}).get("xui", {})[0].get("uhs")
        except Exception as e:
            logger.error("Unable to get user hash from data {}: {}".format(result, e))

        if not xbox_token:
            raise AuthenticationException(
                "Authentication response missing xbox_token",
                user_message="Xbox Live accepted the sign-in but did not return an authentication token. Please sign in again.",
            )

        if not user_hash:
            raise AuthenticationException(
                "Authentication response missing user_hash",
                user_message="Xbox Live did not return the account identifier. Check the account's Xbox profile and try again.",
            )

        return xbox_token, user_hash, result

    data = auth_exception_handler(_request_handler, stage="Signing in to Xbox Live")
    return verify_data(data)

def get_xsts_token(xbox_token: str) -> tuple[str, dict]:
    """
    Get xsts token
    :param xbox_token:
    :return:
        xsts_token: str
        json_data: dict
    """
    def _request_handler():
        r = requests.post(XSTS_AUTH_URL, json={
            "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbox_token]},
            "RelyingParty": "rp://api.minecraftservices.com/",
            "TokenType": "JWT",
        }, headers={"Accept": "application/json"})
        r.raise_for_status()
        return r.json()

    def verify_data(result: dict) -> tuple[str, dict]:
        xsts_token = result.get("Token")

        if not xsts_token:
            raise AuthenticationException(
                "Authentication response missing xsts_token",
                user_message="Xbox security authorization did not return a token. The account may need an Xbox profile or may be restricted.",
            )

        return xsts_token, result

    data = auth_exception_handler(
        _request_handler,
        request_type="with_token",
        stage="Authorizing the Xbox session for Minecraft",
    )

    return verify_data(data)

def get_minecraft_access_token(user_hash: str, xsts_token: str) -> tuple[str, dict]:
    """
    Get minecraft access token
    :param user_hash: Xbox live user hash
    :param xsts_token: XSTS token
    Above param can get from get_xbox_token_and_user_hash and get_xsts_token
    :return:
        access_token: str
        json_data: dict
    """
    def _request_handler():
        r = requests.post(MINECRAFT_LOGIN_URL, json={"identityToken": f"XBL3.0 x={user_hash};{xsts_token}"},
            headers={"Accept": "application/json"})
        r.raise_for_status()
        return r.json()

    def verify_data(result: dict) -> tuple[str, dict]:
        access_token = result.get("access_token")

        if not access_token:
            raise AuthenticationException(
                "Authentication response missing access token",
                user_message="Minecraft services accepted the Xbox session but did not return a game access token. Please sign in again.",
            )

        return access_token, result

    data = auth_exception_handler(
        _request_handler,
        request_type="with_token",
        stage="Signing in to Minecraft services",
    )

    return verify_data(data)


def get_account_entitlements(minecraft_access_token: str) -> dict:
    """
    Get minecraft account entitlements
    :param minecraft_access_token:
    :return:
    """
    def _request_handler():
        response = requests.get(
            MINECRAFT_ENTITLEMENTS_URL,
            headers={"Authorization": f"Bearer {minecraft_access_token}"},
        )
        response.raise_for_status()
        return response.json()

    data = auth_exception_handler(
        _request_handler,
        request_type="with_token",
        stage="Checking Minecraft ownership",
    )
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise AuthenticationSessionException(
            "Minecraft entitlement response is missing the items list",
            user_message="Minecraft services returned an invalid ownership response. Please sign in again or try later.",
        )

    return data


def get_minecraft_profile(minecraft_access_token: str) -> dict:
    """
    Get minecraft profile
    :param minecraft_access_token:
    :return:
        profile_data: dict
    """
    def _request_handler():
        response = requests.get(
            MINECRAFT_PROFILE_URL,
            headers={"Authorization": f"Bearer {minecraft_access_token}"},
        )
        response.raise_for_status()
        return response.json()

    data = auth_exception_handler(
        _request_handler,
        request_type="with_token",
        stage="Loading the Minecraft profile",
    )
    if not isinstance(data, dict) or not data.get("id") or not data.get("name"):
        raise AuthenticationSessionException(
            "Minecraft profile response is missing id or name",
            user_message="Minecraft services did not return a valid player profile. Ensure this account owns Minecraft and has created a profile.",
        )

    return data


def has_minecraft_license(entitlements: dict) -> bool:
    """
    Check if provided account entitlements have minecraft license
    :param entitlements:
    :return:
        found: bool
    """
    if not isinstance(entitlements, dict):
        raise AuthenticationException(
            f"Expected Minecraft entitlements to be a dictionary, got {type(entitlements).__name__}",
            user_message="Unable to verify Minecraft ownership because the ownership response is invalid.",
        )

    items = entitlements.get("items")
    if not isinstance(items, list):
        raise AuthenticationException(
            "Minecraft entitlement response is missing a valid items list",
            user_message="Unable to verify Minecraft ownership because the ownership list is missing or invalid.",
        )

    return any(
        isinstance(item, dict)
        and item.get("name") in {"game_minecraft", "product_minecraft"}
        for item in items
    )

def refresh_microsoft_token(client_id: str, refresh_token: str) -> tuple[str, str, dict]:
    """
    Use existing microsoft refresh token to get new (or extend the expires time) refresh token
    Returns:
        microsoft_access_token,
        new_refresh_token,
        response_data
    """

    def request_handler():
        response = requests.post(
            MICROSOFT_TOKEN_URL,
            data={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "XboxLive.signin offline_access",
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    result = auth_exception_handler(
        request_handler,
        request_type="with_token",
        stage="Refreshing Microsoft credentials",
    )

    access_token = result.get("access_token")
    new_refresh_token = result.get("refresh_token")

    if not access_token:
        raise AuthenticationSessionException(
            "Refresh response missing access_token",
            user_message=(
                "Microsoft could not refresh this account. "
                "Please sign in again."
            ),
        )

    # Return original refresh token if new token is not show up in response
    return (
        access_token,
        new_refresh_token or refresh_token,
        result,
    )

def is_access_token_valid(minecraft_access_token: str) -> bool:
    """
    Check if the access token is valid
    :param minecraft_access_token:
    :return:
    """
    try:
        response = requests.get(
            MINECRAFT_PROFILE_URL,
            headers={"Authorization": f"Bearer {minecraft_access_token}"},
            timeout=10,
        )
    except Exception as e:
        raise AuthenticationSessionException(
            status_code=None,
            user_message="An error occurred while connecting to Minecraft API.",
        ) from e

    status_code = response.status_code

    if status_code == 400:
        raise AuthenticationException(
            user_message="Got bad request response from Minecraft API. Client request format may outdated.",
        )
    elif status_code == 401:
        # Session is invalid
        return False

    if status_code != 200:
        raise AuthenticationSessionException(
            "Get HTTP status code {} while fetch profile data for verifying access token".format(status_code),
            status_code=response.status_code,
            user_message="Unable to verify access token. An server error occurred. ({})".format(status_code),
        )

    return True
