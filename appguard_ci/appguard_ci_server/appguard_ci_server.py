#! /usr/local/bin/python3

#
# Copyright (c) 2015 Cisco Systems, Inc. and others.  All rights reserved.
#

import argparse
import sys
import os
from pathlib import Path
from flask_login import LoginManager

import errno
from magen_rest_apis.magen_app import MagenApp

src_ver = MagenApp.app_source_version(__name__)
if src_ver:
    # noinspection PyUnresolvedReferences
    import dev.magen_env

from magen_rest_apis.server_urls import ServerUrls

from magen_statistics_server.source_counter_rest_api import sourced_counters

from magen_logger.logger_config import LogDefaults, initialize_logger

from appguard_ci.appguard_ci_server.appguard_ci_rest_api import appguard_ci_bp
from appguard_ci.appguard_ci_server.appguard_ci_app import AppGuardApp
from appguard_ci.appguard_ci_server.appguard_ci_globals import AppGuardCiGlobals
from magen_utils_apis.domain_resolver import inside_docker
from prometheus_client import start_http_server

__author__ = "Reinaldo Penno repenno@cisco.com"
__copyright__ = "Copyright(c) 2018, Cisco Systems, Inc."
__version__ = "0.1"
__status__ = "alpha"

APPGUARD_CI_SERVER_PORT = 6020


# We need to return time in ISO format


def main(args):
    # ret = sys.argv[1:]
    server_urls_instance = ServerUrls.get_instance()
    #: setup parser -----------------------------------------------------------
    parser = argparse.ArgumentParser(description='Magen Ingestion Server',
                                     usage=("\npython3 server.py "
                                            "--database "
                                            "--mongo-ip-port "
                                            "--log-dir"
                                            "--console-log-level"
                                            "--clean-init"
                                            "--key-server-ip-port"
                                            "--data-dir"
                                            "--unittest"
                                            "\n\nnote:\n"
                                            "root privileges are required "))

    if inside_docker():
        ingestion_data_dir = os.path.join("/opt", "data")
    else:
        home_dir = str(Path.home())
        ingestion_data_dir = os.path.join(home_dir, "magen_data", "appguard_ci")

    parser.add_argument('--data-dir', default=ingestion_data_dir,
                        help='Set directory for data files'
                             'Default is %s' % ingestion_data_dir)

    parser.add_argument('--log-dir', default=LogDefaults.default_dir,
                        help='Set directory for log files.'
                             'Default is %s' % LogDefaults.default_dir)

    parser.add_argument('--console-log-level', choices=['debug', 'info', 'error'],
                        default='error',
                        help='Set log level for console output.'
                             'Default is %s' % 'error')

    parser.add_argument('--clean-init', action='store_false',
                        help='Clean All data when initializing'
                             'Default is to clean)')

    parser.add_argument('--unittest', action='store_true',
                        help='Unit Test Mode'
                             'Default is production)')

    parser.add_argument('--test', action='store_true',
                        help='Run server in test mode. Used for unit tests'
                             'Default is to run in production mode)')

    #: parse CMD arguments ----------------------------------------------------
    # args = parser.parse_args()
    args, _ = parser.parse_known_args(args)

    logger = initialize_logger(console_level=args.console_log_level, output_dir=args.log_dir)

    if args.clean_init:
        pass

    appguard_ci_globals = AppGuardCiGlobals()
    appguard_ci_globals.data_dir = args.data_dir
    try:
        os.makedirs(args.data_dir)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise

    print("\n\n\n\n ====== STARTING APPGUARD CI SERVER  ====== \n")

    appguard = AppGuardApp().app
    # Since Ingestion blueprint is used by appguard-io that uses login_required, we need
    # to disable globally here when running stand-alone
    appguard.config["LOGIN_DISABLED"] = True
    login_manager = LoginManager()
    login_manager.init_app(appguard)

    appguard.register_blueprint(sourced_counters)
    appguard.register_blueprint(appguard_ci_bp, url_prefix='/appguard/ci/v1')

    if args.test:
        appguard.run(host='0.0.0.0', port=APPGUARD_CI_SERVER_PORT, debug=True, use_reloader=False)
    elif args.unittest:
        pass
    else:
        start_http_server(8000)
        appguard.run(host='0.0.0.0', port=APPGUARD_CI_SERVER_PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main(sys.argv[1:])
else:
    pass
