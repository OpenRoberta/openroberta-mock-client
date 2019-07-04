__version__ = "0.0.1"

__copyright__ = "Copyright 2017-2019, Fraunhofer IAIS"
__author__ = 'Artem Vinokurov'
__email__ = 'artem.vinokurov@iais.fraunhofer.de'

'''
robot-mockup.client -- shortdesc
robot-mockup.client is an OpenRoberta RESR client for robot-server interaction mockup

@author:     Artem Vinokurov
@copyright:  2017-2019 Fraunhofer IAIS.
@license:    GPL 3.0
@contact:    artem.vinokurov@iais.fraunhofer.de
@deffield    updated: 4 July 2019
'''

import json
from simplejson.decoder import JSONDecodeError
import random
import string
from requests import Request, Session
from requests.exceptions import ConnectionError
import datetime
import time
import zipfile
from ConfigParser import SafeConfigParser
import os
import sys

class RestClient():
    '''
    REST endpoints:
    /rest/pushcmd (controlling the workflow of the system)
    /rest/download (the user program can be downloaded here)
    /rest/update/ (updates for libraries on the robot can be downloaded here)
    /update/nao/2-8/hal - GET new hal
    /update/nao/2-8/hal/checksum - GET hal checksum
    '''
    REGISTER = 'register'
    PUSH = 'push'
    REPEAT = 'repeat'
    ABORT = 'abort'
    UPDATE = 'update'
    DOWNLOAD = 'download'
    CONFIGURATION = 'configuration'  # not yet used

    def __init__(self, token_length=8, lab_address='https://lab.open-roberta.org', firmware_version='2-8', robot_name='nao'):
        self.working_directory = sys.path[0] + '/'
        os.chdir(self.working_directory)
        self.DEBUG = True
        self.SSL_VERIFY = True
        self.token_length = token_length
        self.lab_address = lab_address
        self.firmware_name = 'Nao'
        self.firmware_version = firmware_version
        self.brick_name = "brick_name"
        self.robot_name = robot_name
        self.update_url = '/update/nao/' + self.firmware_version + '/hal'
        self.menu_version = __version__
        self.mac_address = "00:00:00:00:00:00"
        self.robot_session = Session()
        self.token = self.generate_token()
        self.last_exit_code = '0'
        self.update_attempts = 36  # 6 minutes of attempts
        self.debug_log_file = open(self.working_directory + 'ora_client.debug', 'w')
        self.command = {
            'firmwarename': self.firmware_name,
            'robot': self.robot_name,
            'macaddr': self.mac_address,
            'cmd': self.REGISTER,
            'firmwareversion': self.firmware_version,
            'token': self.token,
            'brickname': self.brick_name,
            'battery': self.get_battery_level(),
            'menuversion': self.menu_version,
            'nepoexitvalue': self.last_exit_code
        }

    def get_checksum(self, attempts_left):
        if (attempts_left < 1):
            self.log('update server unavailable (cannot get checksum), re-setting number of attempts and continuing further')
            attempts_left = 36  # 6 minutes more of attempts
        try:
            robot_request = Request('GET', self.lab_address + '/update/nao/' + self.firmware_version + '/hal/checksum')
            robot_prepared_request = robot_request.prepare()
            server_response = self.robot_session.send(robot_prepared_request, verify=self.SSL_VERIFY)
            return server_response.content
        except ConnectionError:
            self.log('update server unavailable, sleeping for 10 seconds before next attempt')
            time.sleep(10)
            return self.get_checksum(attempts_left - 1)

    def update_firmware(self):
        checksum = self.get_checksum(self.update_attempts)
        hash_file_name = self.working_directory + 'firmware.hash'
        try:
            f = open(hash_file_name, 'r')
        except IOError:
            f = open(hash_file_name, 'w')
            f.write('NOHASH')
        f = open(hash_file_name, 'r')
        hash_value = f.readline()
        if hash_value != checksum:
            self.log('updating hal library')
            robot_request = Request('GET', self.lab_address + self.update_url)
            robot_prepared_request = robot_request.prepare()
            server_response = self.robot_session.send(robot_prepared_request, verify=self.SSL_VERIFY)
            try:
                with open(server_response.headers['Filename'], 'w') as f:
                    f.write(server_response.content)
            except KeyError:
                if hash_value != 'NOHASH':
                    self.log('no update file was found on the server, however server is up, continuing with old hal')
                    return
                else:
                    self.log('no update file was found on the server and no hal present, shutting down client')
                    exit(0)
            zip_ref = zipfile.ZipFile(server_response.headers['Filename'], 'r')
            zip_ref.extractall(self.working_directory)
            zip_ref.close()
            f = open(hash_file_name, 'w')
            f.write(checksum)
            self.log('hal library updated, checksum written: ' + checksum)
        else:
            self.log('hal library up to date')

    def log(self, message):
        if self.DEBUG:
            print '[DEBUG] - ' + str(datetime.datetime.now()) + ' - ' + message
            self.debug_log_file.write('[DEBUG] - ' + str(datetime.datetime.now()) + ' - ' + message + '\n')

    def generate_token(self):
        return "AABBCCDD"

    def get_battery_level(self):
        return 0

    def send_post(self, command, endpoint):
        robot_request = Request('POST', self.lab_address + endpoint)
        robot_request.data = command
        robot_request.headers['Content-Type'] = 'application/json'
        robot_prepared_request = robot_request.prepare()
        return self.robot_session.send(robot_prepared_request, verify=self.SSL_VERIFY)

    def download_and_execute_program(self):
        self.command['cmd'] = self.DOWNLOAD
        self.command['nepoexitvalue'] = '0'
        download_command = json.dumps(self.command)
        server_response = self.send_post(download_command, '/download')
        program_name = self.working_directory + server_response.headers['Filename']
        with open(program_name, 'w') as f:
            f.write(server_response.content)
        self.log('program downloaded, filename: ' + server_response.headers['Filename'])

    def send_push_request(self):
        self.log('started polling at ' + str(datetime.datetime.now()))
        self.command['cmd'] = self.PUSH
        self.command['nepoexitvalue'] = self.last_exit_code
        push_command = json.dumps(self.command)
        try:
            server_response = self.send_post(push_command, '/pushcmd')
            if server_response.json()['cmd'] == 'repeat':
                self.log('received response at ' + str(datetime.datetime.now()))
            elif server_response.json()['cmd'] == 'download':
                self.log('download issued')
                self.download_and_execute_program()
            elif server_response.json()['cmd'] == 'abort':
                pass
            else:
                pass
        except ConnectionError:
            self.log('Server unavailable, waiting 10 seconds to reconnect.')
            time.sleep(10)
            self.connect()
        self.send_push_request()

    def connect(self):
        self.log('Robot token: ' + self.token)
        self.command['cmd'] = self.REGISTER
        register_command = json.dumps(self.command)
        try:
            server_response = self.send_post(register_command, '/pushcmd')
            if server_response.json()['cmd'] == 'repeat':
                self.send_push_request()
            elif server_response.json()['cmd'] == 'abort':
                pass
            else:
                pass
        except ConnectionError:
            self.log('Server unavailable, reconnecting in 10 seconds...')
            time.sleep(10)
            self.connect()
        except JSONDecodeError:
            self.log('JSON decoding error (robot was not registered within timeout), reconnecting in 10 seconds...')
            time.sleep(10)
            self.connect()


if __name__ == "__main__":
    rc = RestClient()
    rc.log('selected robot: ' + rc.robot_name)
    rc.update_firmware()
    rc.connect()
