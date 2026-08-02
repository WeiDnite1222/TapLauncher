"""
Contains some function that deal with 3rd party api
"""
import requests

from core_lib.common.exception import ThirdPartyAPIException

MC_HEADS_HEAD_ENDPOINT = "https://api.mcheads.org/head/{username}/{size}"

def get_minecraft_head_url(username: str, size: int=256) -> str:
    if not 256 >= size >= 32:
        raise ValueError("size must be between 256 and 32")

    return MC_HEADS_HEAD_ENDPOINT.format(username=username, size=size)

def get_minecraft_head(username: str, size: int=256, timeout: float=10.0) -> bytes:
    """
    Get minecraft head
    :param username:
    :param size:
    :return:
        head_data: bytes
    """
    url = get_minecraft_head_url(username, size)

    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.content
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code

        if status_code == 404:
            raise ThirdPartyAPIException(
                "Got HTTP 404 when fetching api {}. Did the provider still running this service ?".format(MC_HEADS_HEAD_ENDPOINT),
                user_message="Unable to fetch third party API. Provider may no longer exist. Try updating the launcher."
            )
        elif status_code == 500:
            raise ThirdPartyAPIException(
                "Got HTTP 500 when fetching api {}. Did the head size is correct?".format(MC_HEADS_HEAD_ENDPOINT),
                user_message="Unable to fetch third party API. Try updating the launcher.",
            )
        else:
            raise ThirdPartyAPIException(
                "Got HTTP {} unhandled error. Result: {}".format(status_code, e.response.text),
                user_message="Unable to fetch third party API. Unknown HTTP Error: {}".format(status_code),
            )
    except requests.exceptions.RequestException as e:
        raise ThirdPartyAPIException(
            "An error occurred while fetching third party API: {}".format(e),
            user_message="Unable to fetch third party API. Try updating the launcher.",
        )

