#! /usr/bin/python3

import unittest

# noinspection PyUnresolvedReferences
import uuid

from appguard_ci.appguard_ci_server.appguard_ci_globals import AppGuardCiGlobals
from appguard_ci.appguard_ci_server.appguard_ci_rest_api import appguard_ci_bp
from appguard_ci.tests.appguard_ci_env import *

from appguard_ci.appguard_ci_server.appguard_ci_app import AppGuardApp

__author__ = "Reinaldo Penno"
__copyright__ = "Copyright(c) 2015, Cisco Systems, Inc."
__license__ = "New-style BSD"
__version__ = "0.1"
__email__ = "rapenno@gmail.com"


class TestRestApi(unittest.TestCase):

    @classmethod
    def setUpClass(cls):

        cls.appguard_ci_globals = AppGuardCiGlobals()
        # current_path comes from appguard_ci_env
        cls.appguard_ci_globals.data_dir = current_path

        cls.appguard_ci = AppGuardApp().app
        cls.appguard_ci.config['TESTING'] = True
        cls.appguard_ci.register_blueprint(appguard_ci_bp, url_prefix='/appguard/ci/v1')
        cls.app = cls.appguard_ci.test_client()

    def setUp(self):
        """
        This function prepares the system for running tests
        """
        pass

    def tearDown(self):
        pass
