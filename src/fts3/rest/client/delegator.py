from datetime import datetime, timedelta
from M2Crypto import X509, ASN1, m2
import json
import pytz
import sys
import time

from exceptions import *


class Delegator(object):

    def __init__(self, context):
        self.context = context

    def _get_delegation_id(self):
        r = json.loads(self.context.get('/whoami'))
        return r['delegation_id']

    def _get_remaining_life(self, delegation_id):
        r = self.get_info(delegation_id)
        if r is None:
            return None
        else:
            expiration_time = datetime.strptime(r['termination_time'], '%Y-%m-%dT%H:%M:%S')
            return expiration_time - datetime.utcnow()

    def _get_proxy_request(self, delegation_id):
        request_url = '/delegation/' + delegation_id + '/request'
        request_pem = self.context.get(request_url)
        x509_request = X509.load_request_string(request_pem)
        if x509_request.verify(x509_request.get_pubkey()) != 1:
            raise ServerError('Error verifying signature on the request')
        # Return
        return x509_request

    def _sign_request(self, x509_request, lifetime):
        not_before = ASN1.ASN1_UTCTIME()
        not_before.set_datetime(datetime.now(pytz.UTC))
        not_after = ASN1.ASN1_UTCTIME()
        not_after.set_datetime(datetime.now(pytz.UTC) + lifetime)

        proxy_subject = X509.X509_Name()
        for c in self.context.x509.get_subject():
            m2.x509_name_add_entry(proxy_subject._ptr(), c._ptr(), -1, 0)
        proxy_subject.add_entry_by_txt('commonName', 0x1000, 'proxy', -1, -1, 0)

        proxy = X509.X509()
        proxy.set_subject(proxy_subject)
        proxy.set_serial_number(int(time.time()))
        proxy.set_version(x509_request.get_version())
        proxy.set_issuer(self.context.x509.get_subject())
        proxy.set_pubkey(x509_request.get_pubkey())

        # X509v3 Basic Constraints
        proxy.add_ext(X509.new_extension('basicConstraints', 'CA:FALSE', critical=True))
        # X509v3 Key Usage
        proxy.add_ext(X509.new_extension('keyUsage', 'Digital Signature, Key Encipherment', critical=True))

        # Make sure the proxy is not longer than any other inside the chain
        any_rfc_proxies = False
        for cert in self.context.x509_list:
            if cert.get_not_after().get_datetime() < not_after.get_datetime():
                not_after = cert.get_not_after()
            try:
                cert.get_ext('1.3.6.1.5.5.7.1.14')
                any_rfc_proxies = True
            except:
                pass

        proxy.set_not_after(not_after)
        proxy.set_not_before(not_before)

        if any_rfc_proxies:
            raise NotImplementedError('RFC proxies not supported yet')

        proxy.set_version(2)
        proxy.sign(self.context.evp_key, 'sha1')

        return proxy

    def _put_proxy(self, delegation_id, x509_proxy):
        self.context.put('/delegation/' + delegation_id + '/credential', x509_proxy)

    def _full_proxy_chain(self, x509_proxy):
        chain = x509_proxy.as_pem()
        for cert in self.context.x509_list:
            chain += cert.as_pem()
        return chain

    def get_info(self, delegation_id=None):
        if delegation_id is None:
            delegation_id = self._get_delegation_id()
        return json.loads(self.context.get('/delegation/' + delegation_id))

    def delegate(self, lifetime=timedelta(hours=7), force=False):
        try:
            delegation_id = self._get_delegation_id()
            self.context.logger.debug("Delegation ID: " + delegation_id)

            remaining_life = self._get_remaining_life(delegation_id)

            if remaining_life is None:
                self.context.logger.debug("No previous delegation found")
            elif remaining_life <= timedelta(0):
                self.context.logger.debug("The delegated credentials expired")
            elif remaining_life >= timedelta(hours=1):
                if not force:
                    self.context.logger.debug("Not bothering doing the delegation")
                    return delegation_id
                else:
                    self.context.logger.debug("Delegation not expired, but this is a forced delegation")

            # Ask for the request
            self.context.logger.debug("Delegating")
            x509_request = self._get_proxy_request(delegation_id)

            # Sign request
            self.context.logger.debug("Signing request")
            x509_proxy = self._sign_request(x509_request, lifetime)
            x509_proxy_pem = self._full_proxy_chain(x509_proxy)

            # Send the signed proxy
            self._put_proxy(delegation_id, x509_proxy_pem)

            return delegation_id
        except FTS3ClientException, e:
            raise e
        except Exception, e:
            raise ClientError(str(e)), None, sys.exc_info()[2]
