#   Copyright notice:
#   Copyright CERN, 2018
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.


import logging
import json
import time
import socket
from fts3.model import Host
from threading import Thread
from fts3.rest.client.request import Request
from datetime import datetime, timedelta

from fts3.model import Credential
from fts3rest.lib.base import Session

log = logging.getLogger(__name__)


class IAMTokenRefresher(Thread):
    """
    Keeps running on the background updating the db marking the process as alive
    """

    def __init__(self, interval, config):
        """
        Constructor
        """
        Thread.__init__(self)
        self.interval = interval
        self.daemon = True
        self.config = config

    def _refresh_token(self, credential):
        # Request a new access token based on the refresh token
        requestor = Request(None, None)  # VERIFY:TRUE

        refresh_token = credential.proxy.split(':')[1]
        body = {'grant_type': 'refresh_token',
                'refresh_token': refresh_token,
                'client_id': self.config['fts3.ClientId'],
                'client_secret': self.config['fts3.ClientSecret']}

        new_credential = json.loads(
            requestor.method('POST', self.config['fts3.AuthorizationProviderTokenEndpoint'], body=body,
                             user=self.config['fts3.ClientId'],
                             passw=self.config['fts3.ClientSecret']))

        credential.proxy = new_credential['access_token'] + ':' + new_credential['refresh_token']
        credential.termination_time = datetime.utcfromtimestamp(new_credential['exp'])

        return credential

    def run(self):
        """
        Thread logic
        """

        # verify that no other fts-rest is running on this machine so as to make sure that no two token-refreshers run simultaneously
        host = Session.query(Host).filter(Host.hostname == socket.getfqdn()).first()
        #write on the hostfile instead of checking the host
        if not host or (datetime.utcnow() - host.beat) > timedelta(seconds=int(self.config.get('fts3.IAMTokenRefreshTimedeltaInSeconds',800))):
            while self.interval:
                credentials = Session.query(Credential).filter(Credential.proxy.notilike("%CERTIFICATE%")).all()

                for c in credentials:
                    try:
                        c = self._refresh_token(c)
                        Session.merge(c)
                        Session.commit()
                    except Exception, e:
                        log.warning("Failed to refresh token for dn: %s because: %s" % (str(c.dn), str(e)))
                time.sleep(self.interval)
