import base64
import json
import logging
import os
import shutil
import re
from shutil import copy2
from http import HTTPStatus

import magen_statistics_server.counters as counters
from flask import request, flash, Blueprint
from magen_logger.logger_config import LogDefaults
from magen_rest_apis.rest_client_apis import RestClientApis
from magen_rest_apis.rest_server_apis import RestServerApis
from magen_rest_apis.server_urls import ServerUrls
from magen_statistics_api.metric_flavors import RestResponse, RestRequest
from magen_utils_apis.datetime_api import datetime_parse_iso8601_string_to_utc
from magen_utils_apis.domain_resolver import inside_docker
from werkzeug.exceptions import BadRequest
from werkzeug.utils import secure_filename

from ingestion.ingestion_apis.asset_creation_api import AssetCreationApi
from ingestion.ingestion_apis.asset_db_api import AssetDbApi
from ingestion.ingestion_apis.container_api import ContainerApi
from ingestion.ingestion_apis.encryption_api import EncryptionApi
from ingestion.ingestion_server.ingestion_globals import IngestionGlobals
from ingestion.ingestion_server.ingestion_rest_api_v2 import ingestion_bp_v2

project_root = os.path.dirname(__file__)
template_path = os.path.join(project_root, 'templates')
logger = logging.getLogger(LogDefaults.default_log_name)

dir_path = os.path.dirname(os.path.realpath(__file__))
UPLOAD_FOLDER = dir_path + '/magen_files'
ALLOWED_EXTENSIONS = set(['txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'docx'])

__author__ = "Reinaldo Penno repenno@cisco.com"
__copyright__ = "Copyright(c) 2015, Cisco Systems, Inc."
__version__ = "0.1"
__status__ = "alpha"

INGESTION = "Ingestion"

# get /config/routes/
#
# post /config/
#
# get /data/magen_ingestion:assets/
#
# put /data/magen_ingestion:assets/
#
# delete /data/magen_ingestion:assets/
#
# post /data/magen_ingestion:assets/
#
# get /data/magen_ingestion:assets/asset/{uuid}/
#
# put /data/magen_ingestion:assets/asset/{uuid}/
#
# delete /data/magen_ingestion:assets/asset/{uuid}/

ingestion_bp = Blueprint('ingestion', __name__, template_folder=template_path)
configuration = Blueprint('configuration', __name__)


# Assets

@ingestion_bp_v2.route('/check/', methods=["GET"])
@ingestion_bp.route('/check/', methods=["GET"])
def heath_check():
    docker = False
    if inside_docker:
        docker = True
    return RestServerApis.respond(
        HTTPStatus.OK, "Health Check", {
            "docker": docker})


@ingestion_bp_v2.route('/logging_level/', methods=["PUT"])
@ingestion_bp.route('/logging_level/', methods=["PUT"])
def set_logging_level():
    try:
        logging_dict = request.json
        level = logging_dict["level"]

        do_set_logging_level(level)

        return RestServerApis.respond(
            HTTPStatus.OK, "set_logging_level", {
                "success": True, "cause": "level set to %s" %
                                          level})
    except ValueError:
        return RestServerApis.respond(
            HTTPStatus.INTERNAL_SERVER_ERROR, "set_logging_level", {
                "success": False, "cause": HTTPStatus.INTERNAL_SERVER_ERROR.phrase})


def do_set_logging_level(level):
    logger = logging.getLogger(LogDefaults.default_log_name)

    level = str(level).upper()

    logger.setLevel(level=level)
    requestsLogger = logging.getLogger("requests")
    requestsLogger.setLevel(level=level)
    werkzeugLogger = logging.getLogger("werkzeug")
    werkzeugLogger.setLevel(level=level)
    return True

@ingestion_bp_v2.route('/assets/', methods=["DELETE"])
@ingestion_bp.route('/assets/', methods=["DELETE"])
def magen_delete_assets():
    """
    REST API used to delete all assets from database.
    :return: A dictionary with the proper HTTP error code plus other metadata
    """
    counters.increment(RestRequest.DELETE, INGESTION)
    success, response = AssetDbApi.delete_all()
    counters.increment(RestResponse.OK, INGESTION)
    if success:
        return RestServerApis.respond(HTTPStatus.OK, "Delete Assets",
                                      {"success": True, "cause": response})
    else:  # pragma: no cover
        return RestServerApis.respond(HTTPStatus.INTERNAL_SERVER_ERROR, "Delete Assets",
                                      {"success": False, "cause": response})


@ingestion_bp.route('/assets/', methods=["GET"])
def magen_get_assets():
    """
    REST API used to retrieve all assets from database
    :return: A dictionary with the proper HTTP error code plus other metadata
    """
    counters.increment(RestRequest.GET, INGESTION)
    response = AssetDbApi.get_all()
    result = dict(
        success=True,
        assets=response,
        cause=""
    )
    counters.increment(RestResponse.OK, INGESTION)
    status = HTTPStatus.OK
    if not response:
        result["cause"] = "No Assets Found"
    return RestServerApis.respond(status, "Get Assets", result)


def download_file(asset_url, local_file_path):
    """
    Downloads or copy asset and stores it at local_file_path
    :param asset_url: A HTTP or FILE URL
    :param local_file_path: A file system path
    :return: True or False
    """
    match = re.search('^file://(.*)', asset_url)
    try:
        if match:
            file_path_in_json = match.group(1).split("localhost")
            if file_path_in_json[0] != local_file_path:
                copy2(file_path_in_json[0], local_file_path)
            return True
        else:
            r = RestClientApis.http_get_and_check_success(asset_url, stream=True)
            if not r.success:
                logger.error("Could not access URL: %s", asset_url)
                return False

            with open(local_file_path, 'w+b') as f:
                shutil.copyfileobj(r.raw, f)
    except (OSError, IOError) as e:
        # TODO need to remove copied file
        logger.error("Could not save file: %s", str(e))
        return False
    return True


# Creation of Asset
@ingestion_bp_v2.route('/assets/asset/', methods=["POST"])
@ingestion_bp.route('/assets/asset/', methods=["POST"])
def magen_create_asset():
    """
    REST API used to create a single asset on the database. It will retrieve
    the asset specified in the dowload_url json attribute, encrypt and save in the
    working directory. The file is not returned to the client, just the asset ID and
    other information

    :return: A dictionary with the proper HTTP error code plus other metadata
    """
    counters.increment(RestRequest.POST, INGESTION)
    asset_process_success = False
    asset_dict = None
    try:
        asset_dict = request.json["asset"][0]
        # Asset_dict is modified in place and there are no added internal
        # fields so at this point response and asset_dict should be the same.
        if "download_url" not in asset_dict:
            raise BadRequest("donwload_url is mandatory")
        download_url = asset_dict["download_url"]
        file_name = download_url.split('/')[-1]
        asset_dict["file_name"] = file_name
        dst_file_path = os.path.join(IngestionGlobals().data_dir, file_name)
        enc_file_path = dst_file_path + ".enc"
        base64_file_path = enc_file_path + ".b64"
        asset_dict["file_path"] = dst_file_path

        # TODO: move to function

        asset_process_success, message, count = AssetCreationApi.process_asset(asset_dict)
        if asset_process_success and count:
            asset_dict_json = dict(asset_dict)
            # We need to remove keys that will break JSONnify
            asset_dict_json.pop('_id', None)
            # We also POP the local file path since it has local significance only
            # asset_dict_json.pop('file_path', None)
            # Since we created an asset, now we will request its key
            server_urls_instance = ServerUrls().get_instance()
            key_post_dict = {"asset": {"asset_id": asset_dict["uuid"]}, "format": "json", "ks_type": "local"}
            json_post = json.dumps(key_post_dict)
            post_return_obj = RestClientApis.http_post_and_check_success(server_urls_instance.key_server_asset_url,
                                                                         json_post)
            if post_return_obj.success:
                key_info = post_return_obj.json_body
                key_b64 = key_info["response"]["key"]
                logger.debug("key_id :%s", key_info["response"]["key_id"])
                key_iv_b64 = key_info["response"]["iv"]
                # Decode key material we got from KS
                # iv_decoded = base64.b64decode(key_iv_b64)
                iv_decoded = key_iv_b64
                logger.debug("decoded iv amd length: %s %s", iv_decoded, len(iv_decoded))
                # key_decoded = base64.b64decode(key_b64)
                key_decoded = key_b64
                logger.debug("decoded key and length: %s %s", key_decoded, len(key_decoded))

                b64_file_digest, file_size, message  = ContainerApi.download_and_encrypt_file(download_url, base64_file_path, key_decoded, iv_decoded)
                if not b64_file_digest:
                    # TODO if something goes wrong we need to delete copy of file.
                    raise Exception(message)

                asset_dict["file_size"] = file_size

                metadata_json, metadata_dict = ContainerApi.create_meta_v2(asset_dict,
                                                                           creator_domain="www.magen.io",
                                                                           enc_asset_hash=b64_file_digest.hexdigest(),
                                                                           iv=iv_decoded)
                metadata_b64 = ContainerApi.b64encode_meta_v2(metadata_json)
                metadata_b64_str = metadata_b64.decode("utf-8")
                html_container_path = dst_file_path + ".html"
                if not ContainerApi.create_html_file_container_from_file(metadata_dict, metadata_b64_str,
                                                                         base64_file_path, html_container_path):
                    raise Exception("Failed to create container: {}".format(dst_file_path))

                counters.increment(RestResponse.CREATED, INGESTION)
                http_response = RestServerApis.respond(HTTPStatus.CREATED, "Create Asset", {
                    "success": True, "cause": HTTPStatus.CREATED.phrase, "asset": asset_dict_json})
                http_response.headers['location'] = request.url + asset_dict_json['uuid'] + '/'
                return http_response
            else:
                raise Exception("Key Server problem")
        else:
            raise Exception(message)
    except (KeyError, IndexError, BadRequest) as e:
        if asset_process_success:
            AssetDbApi.delete_one(asset_dict['uuid'])
        counters.increment(RestResponse.BAD_REQUEST, INGESTION)
        message = str(e)
        return RestServerApis.respond(HTTPStatus.BAD_REQUEST, "Create Asset", {
            "success": False, "cause": message, "asset": None})
    except Exception as e:
        if asset_process_success:
            AssetDbApi.delete_one(asset_dict['uuid'])
        counters.increment(RestResponse.INTERNAL_SERVER_ERROR, INGESTION)
        message = str(e)
        return RestServerApis.respond(HTTPStatus.INTERNAL_SERVER_ERROR, "Create Asset", {
            "success": False, "cause": message, "asset": None})


# Update of Asset - not supported yet
@ingestion_bp_v2.route('/assets/asset/<asset_uuid>/', methods=["PUT"])
@ingestion_bp.route('/assets/asset/<asset_uuid>/', methods=["PUT"])
def magen_update_asset(asset_uuid):
    """
    REST API used to update or create a single asset on database
    :param asset_uuid: Asset UUID
    :return: A dictionary with the proper HTTP error code plus other metadata
    """
    counters.increment(RestRequest.PUT, INGESTION)
    success = False
    asset_dict = request.json["asset"][0]
    if "creation_timestamp" in asset_dict:
        original_creation_timestamp = datetime_parse_iso8601_string_to_utc(asset_dict["creation_timestamp"])
        asset_dict["creation_timestamp"] = original_creation_timestamp
    if asset_dict["uuid"] != asset_uuid:
        result = {
            "success": success,
            "cause": "UUID in URL different from payload",
            "asset": asset_uuid

        }
        counters.increment(RestResponse.BAD_REQUEST, INGESTION)
        return RestServerApis.respond(HTTPStatus.BAD_REQUEST, "Create Asset",
                                      result)
    success, msg = AssetDbApi.replace(asset_dict)
    result = {
        "success": success,
        "asset": asset_uuid,
        "cause": msg
    }
    if success:
        counters.increment(RestResponse.CREATED, INGESTION)
        http_response = RestServerApis.respond(HTTPStatus.CREATED, "Create Asset",
                                               result)
        http_response.headers['location'] = request.url + asset_uuid + '/'
        return http_response
    else:
        counters.increment(RestResponse.INTERNAL_SERVER_ERROR, INGESTION)
        return RestServerApis.respond(HTTPStatus.INTERNAL_SERVER_ERROR, "Create Asset",
                                      result)


@ingestion_bp_v2.route('/assets/asset/<asset_uuid>/', methods=["DELETE"])
@ingestion_bp.route('/assets/asset/<asset_uuid>/', methods=["DELETE"])
def magen_delete_asset(asset_uuid):
    """
    REST API used to delete a single asset from database
    :param asset_uuid: Asset UUID
    :return: HTTP Response with the appropriate payload
    """
    try:
        counters.increment(RestRequest.DELETE, INGESTION)
        success, count, msg = AssetDbApi.delete_one(asset_uuid, asset_dict=None)
        result = {
            "success": success,
            "asset": asset_uuid,
            "cause": msg
        }
        if success:
            if count:
                counters.increment(RestResponse.OK, INGESTION)
                return RestServerApis.respond(HTTPStatus.OK, "Delete Asset",
                                              result)
            else:
                counters.increment(RestResponse.NOT_FOUND, INGESTION)
                return RestServerApis.respond(HTTPStatus.NOT_FOUND, "Delete Asset",
                                              result)
        else:
            counters.increment(RestResponse.INTERNAL_SERVER_ERROR, INGESTION)
            return RestServerApis.respond(HTTPStatus.INTERNAL_SERVER_ERROR, "Delete Asset",
                                          result)
    except ValueError as e:
        counters.increment(RestResponse.BAD_REQUEST, INGESTION)
        return RestServerApis.respond(HTTPStatus.BAD_REQUEST, "Create Asset", {
            "success": False, "cause": e.args[0], "asset": asset_uuid})


@ingestion_bp_v2.route('/assets/asset/<asset_uuid>/', methods=["GET"])
@ingestion_bp.route('/assets/asset/<asset_uuid>/', methods=["GET"])
def magen_get_asset(asset_uuid):
    """
    REST API used to retrieve a single asset from database
    :param asset_uuid: Asset UUID
    :return: HTTP Response with the appropriate payload
    """
    counters.increment(RestRequest.GET, INGESTION)
    success, asset_list, msg = AssetDbApi.get_asset(asset_uuid)
    result = {
        "success": success,
        "asset": asset_list,
        "cause": msg
    }
    if success and asset_list:
        counters.increment(RestResponse.OK, INGESTION)
        return RestServerApis.respond(HTTPStatus.OK, "Get Asset", result)
    else:
        counters.increment(RestResponse.NOT_FOUND, INGESTION)
        return RestServerApis.respond(HTTPStatus.NOT_FOUND, "Get Asset", result)


@ingestion_bp.route('/upload/', methods=["POST"])
def upload_file():
    """
    REST URL used to upload a file for container creation

    If we get a proper file we create a reference to the contents and request
    keying material from keyserver. Keying material is sent in base64 format that
    we need to decode.

    After decoding we create metadata and encrypt the contents. Finally we base64 encode
    the contents and send back to the client.

    :return: HTTP with proper error code
    """
    # Some initialization

    encrypted_stream = None
    # check if the post request has the file part
    if 'file' not in request.files:
        flash('No file part')
        return RestServerApis.respond(HTTPStatus.BAD_REQUEST, "Upload File", {
            "success": False, "cause": "No File Present", "asset": None})
    # file_obj is of type FileStorage that is specific to Flask. it support file operations.
    file_obj = request.files['file']
    if file_obj.filename == '':
        flash('No selected file')
        return RestServerApis.respond(HTTPStatus.BAD_REQUEST, "Upload File", {
            "success": False, "cause": "No File Name", "asset": None})
    filename = secure_filename(file_obj.filename)
    # Debug
    # file_content_ref = file_obj.read()
    asset_dict = {"filename": filename}
    success, message, count = AssetCreationApi.process_asset(asset_dict)
    if success and count:
        # Since we created an asset, now we will request its key
        server_urls_instance = ServerUrls().get_instance()
        key_post_dict = {"asset": {"asset_id": asset_dict["uuid"]}, "format": "json", "ks_type": "local"}


        json_post = json.dumps(key_post_dict)
        post_return_obj = RestClientApis.http_post_and_check_success(server_urls_instance.key_server_asset_url,
                                                                     json_post)
        if post_return_obj.success:
            key_info = post_return_obj.json_body
            key_b64 = key_info["response"]["key"]
            # Debug
            # key_id = key_info["response"]["key_id"]
            key_iv_b64 = key_info["response"]["iv"]
            metadata_byte_array = EncryptionApi.create_meta(asset_dict["uuid"])
            # Decode key material we got from KS
            iv_decoded = base64.b64decode(key_iv_b64)
            # For debugging
            # print("decoded iv is ", iv_decoded, " and is length ", len(iv_decoded))
            key_decoded = base64.b64decode(key_b64)
            # For debugging
            # print("decoded key is ", key_decoded, " and is length ", len(key_decoded))
            encrypted_stream = EncryptionApi.encrypt_stream_with_metadata(key=key_decoded, key_iv=iv_decoded,
                                                                          file_obj=file_obj,
                                                                          metadata_byte_array=metadata_byte_array)
            # We will convert the stream into bytes so it can be b64 encoded and put into a JSON object
            # for reply
            encrypted_stream.seek(0, 0)
            encrypted_contents = encrypted_stream.read()
            encrypted_contents_b64 = base64.b64encode(encrypted_contents)
            # print(encrypted_contents)
        else:
            return RestServerApis.respond(HTTPStatus.INTERNAL_SERVER_ERROR, "Upload File", {
                "success": False, "cause": "KeyServer Error", "asset": None, "file": encrypted_stream})
        counters.increment(RestResponse.CREATED, INGESTION)
    else:
        logger.error(message)
        return RestServerApis.respond(HTTPStatus.INTERNAL_SERVER_ERROR, "Upload File", {
            "success": False, "cause": message, "asset": None, "file": encrypted_stream})
    return RestServerApis.respond(HTTPStatus.OK, "Upload File",
                                  {"success": True, "cause": HTTPStatus.OK.phrase,
                                   "asset": asset_dict["uuid"],
                                   "file": encrypted_contents_b64.decode("utf-8")})


@ingestion_bp_v2.route("/test_counters/increment/", methods=["GET"])
@ingestion_bp.route("/test_counters/increment/", methods=["GET"])
def test_counters_inc():
    counters.increment(RestResponse.OK, "Ingestion")
    counters.increment(RestRequest.GET, "Ingestion")
    return "Test"


@ingestion_bp_v2.route("/test_counters/reset/", methods=["GET"])
@ingestion_bp.route("/test_counters/reset/", methods=["GET"])
def test_counters_reset():
    counters.reset(RestRequest.POST)
    counters.reset(RestResponse.OK)
    return "Test"


@ingestion_bp_v2.route("/test_counters/delete/", methods=["GET"])
@ingestion_bp.route("/test_counters/delete/", methods=["GET"])
def test_counters_delete():
    counters.delete(RestResponse.ACCEPTED)
    counters.delete(RestRequest.GET)
    return "Test"
