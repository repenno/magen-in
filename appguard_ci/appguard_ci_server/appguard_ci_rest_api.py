import logging
import os
from http import HTTPStatus
from flask import request, Blueprint
from magen_logger.logger_config import LogDefaults
from magen_rest_apis.rest_server_apis import RestServerApis
from magen_utils_apis.domain_resolver import inside_docker

project_root = os.path.dirname(__file__)
template_path = os.path.join(project_root, 'templates')
logger = logging.getLogger(LogDefaults.default_log_name)

dir_path = os.path.dirname(os.path.realpath(__file__))

__author__ = "Reinaldo Penno repenno@cisco.com"
__copyright__ = "Copyright(c) 2018, Cisco Systems, Inc."
__version__ = "0.1"
__status__ = "alpha"

APPGUARD_CI = "AppGuardCI"

appguard_ci_bp = Blueprint('appguard_ci', __name__, template_folder=template_path)
configuration = Blueprint('configuration', __name__)


@appguard_ci_bp.route('/check/', methods=["GET"])
def heath_check():
    docker = False
    if inside_docker:
        docker = True
    return RestServerApis.respond(
        HTTPStatus.OK, "Health Check", {
            "docker": docker})


# Creation of Asset
@appguard_ci_bp.route('/event_handler/', methods=["POST"])
def appguard_ci_event_handler():
    """
    REST API used to create a single asset on the database. It will retrieve
    the asset specified in the dowload_url json attribute, encrypt and save in the
    working directory. The file is not returned to the client, just the asset ID and
    other information

    :return: A dictionary with the proper HTTP error code plus other metadata
    """
    post_headers = request.headers
    postdata = request.get_data()
    postJson = request.get_json(force=True)
    return "ok", HTTPStatus.OK
