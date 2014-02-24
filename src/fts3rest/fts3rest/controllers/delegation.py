from datetime import datetime
from fts3.model import CredentialCache, Credential
from fts3rest.lib.api import doc
from fts3rest.lib.base import BaseController, Session
from fts3rest.lib.helpers import jsonify
from fts3rest.lib.helpers import voms
from M2Crypto import X509, RSA, EVP, BIO
from pylons.controllers.util import abort
from pylons.decorators import rest
from pylons import request
import json
import pytz
import types
import uuid

def getDNComponents(dn):
    return map(lambda x: tuple(x.split('=')), dn.split('/')[1:])


def populatedName(components):
    x509Name = X509.X509_Name()
    for (field, value) in components:
        x509Name.add_entry_by_txt(field, 0x1000, value,
                                  len=-1, loc=-1, set=0)
    return x509Name


def _muteCallback(*args, **kwargs):
    pass


def generateProxyRequest(dnList):
    # By convention, use the longer representation
    userDN = dnList[-1]

    requestKeyPair = RSA.gen_key(1024, 65537, callback=_muteCallback)
    requestPKey = EVP.PKey()
    requestPKey.assign_rsa(requestKeyPair)
    request = X509.Request()
    request.set_pubkey(requestPKey)
    request.set_subject(populatedName([('O', 'Dummy')]))
    request.set_version(0)
    request.sign(requestPKey, 'md5')

    return (request, requestPKey)

def _validateProxy(proxy_str, priv_key_str):
    x509Proxy           = X509.load_cert_string(proxy_str)
    proxyExpirationTime = x509Proxy.get_not_after().get_datetime().replace(tzinfo = None)
    

    # Validate the subject
    proxySubject = '/' + '/'.join(x509Proxy.get_subject().as_text().split(', '))
    proxyIssuer = '/' + '/'.join(x509Proxy.get_issuer().as_text().split(', '))
    if proxySubject != proxyIssuer + '/CN=proxy':
        raise Exception("The subject and the issuer of the proxy do not match")
    
    # Make sure the certificate corresponds to the private key
    pkey = EVP.load_key_string(str(priv_key_str), callback = _muteCallback)
    if x509Proxy.get_pubkey().get_modulus() != pkey.get_modulus():
        raise Exception("The delegated proxy do not correspond the stored private key")
    
    return proxyExpirationTime


class DelegationController(BaseController):
    """
    Operations to perform the delegation of credentials
    """

    @doc.return_type('dateTime')
    @jsonify
    def view(self, id, start_response):
        """
        Get the termination time of the current delegated credential, if any
        """
        user = request.environ['fts3.User.Credentials']

        if id != user.delegation_id:
            start_response('403 FORBIDDEN', [('Content-Type', 'text/plain')])
            return 'The resquested ID and the credentials ID do not match'

        cred = Session.query(Credential).get((user.delegation_id, user.user_dn))
        if not cred:
            return None
        else:
            return {'termination_time': cred.termination_time}


    @doc.response(403, 'The requested delegation ID does not belong to the user')
    @doc.response(404, 'The credentials do not exist')
    @doc.response(204, 'The credentials were deleted successfully')
    def delete(self, id, start_response):
        """
        Delete the delegated credentials from the database
        """
        user = request.environ['fts3.User.Credentials']
        
        if id != user.delegation_id:
            start_response('403 FORBIDDEN', [('Content-Type', 'text/plain')])
            return ['The resquested ID and the credentials ID do not match']
        
        cred = Session.query(Credential).get((user.delegation_id, user.user_dn))
        if not cred:
            start_response('404 NOT FOUND', [('Content-Type', 'text/plain')])
            return ['Delegated credentials not found']
        else:
            Session.delete(cred)
            Session.commit()
            start_response('204 NO CONTENT', [])
            return ['']


    @doc.response(403, 'The requested delegation ID does not belong to the user')
    @doc.response(200, 'The request was generated succesfully')
    @doc.return_type('PEM encoded certificate request')
    def request(self, id, start_response):
        """
        First step of the delegation process: get a certificate request
        
        The returned certificate request must be signed with the user's original
        credentials.
        """
        user = request.environ['fts3.User.Credentials']

        if id != user.delegation_id:
            start_response('403 FORBIDDEN', [('Content-Type', 'text/plain')])
            return ['The resquested ID and the credentials ID do not match']

        credentialCache = Session.query(CredentialCache)\
            .get((user.delegation_id, user.user_dn))

        if credentialCache is None:
            (proxyRequest, proxyKey) = generateProxyRequest(user.dn)
            credentialCache = CredentialCache(dlg_id = user.delegation_id,
                                              dn = user.user_dn,
                                              cert_request = proxyRequest.as_pem(),
                                              priv_key     = proxyKey.as_pem(cipher = None),
                                              voms_attrs   = ' '.join(user.voms_cred))
            Session.add(credentialCache)
            Session.commit()

        start_response('200 OK', [('X-Delegation-ID', credentialCache.dlg_id),
                                  ('Content-Type', 'text/plain')])
        return credentialCache.cert_request

    def _readX509List(self, pemString):
        x509List = []
        bio = BIO.MemoryBuffer(pemString)
        try:
            while True:
                cert = X509.load_cert_bio(bio)
                x509List.append(cert)
        except X509.X509Error:
            pass
        return x509List

    def _buildFullProxyPEM(self, proxyPEM, privKey):
        x509List = self._readX509List(proxyPEM)
        x509Chain = ''.join(map(lambda x: x.as_pem(), x509List[1:]))
        return x509List[0].as_pem() + privKey + x509Chain


    @doc.input('Signed certificate', 'PEM encoded certificate')
    @doc.response(403, 'The requested delegation ID does not belong to the user')
    @doc.response(400, 'The proxy failed the validation process')
    @doc.response(201, 'The proxy was stored successfully')
    def credential(self, id, start_response):
        """
        Second step of the delegation process: put the generated certificate
        
        The certificate being PUT will have to pass the following validation:
            - There is a previous certificate request done
            - The certificate subject matches the certificate issuer + '/CN=Proxy'
            - The certificate modulus matches the stored private key modulus
        """
        user = request.environ['fts3.User.Credentials']

        if id != user.delegation_id:
            start_response('403 FORBIDDEN', [('Content-Type', 'text/plain')])
            return ['The resquested ID and the credentials ID do not match']

        credentialCache = Session.query(CredentialCache)\
            .get((user.delegation_id, user.user_dn))
        if credentialCache is None:
            start_response('400 BAD REQUEST', [('Content-Type', 'text/plain')])
            return ['No credential cache found']

        x509ProxyPEM = request.body

        try:
            proxyExpirationTime = _validateProxy(x509ProxyPEM, credentialCache.priv_key)
            x509FullProxyPEM    = self._buildFullProxyPEM(x509ProxyPEM, credentialCache.priv_key)
        except Exception, e:
            start_response('400 BAD REQUEST', [('Content-Type', 'text/plain')])
            return ['Could not process the proxy: ' + str(e)]

        credential = Credential(dlg_id           = user.delegation_id,
                                dn               = user.user_dn,
                                proxy            = x509FullProxyPEM,
                                voms_attrs       = credentialCache.voms_attrs,
                                termination_time = proxyExpirationTime)

        Session.merge(credential)
        Session.commit()

        start_response('201 CREATED', [])
        return ['']

    @doc.input('List of voms commands', 'array')
    @doc.response(403, 'The requested delegation ID does not belong to the user')
    @doc.response(400, 'Could not understand the request')
    @doc.response(424, 'The obtention of the VOMS extensions failed')
    @doc.response(203, 'The obtention of the VOMS extensions succeeded')
    def voms(self, id, start_response):
        """
        Generate VOMS extensions for the delegated proxy
        
        The input must be a json-serialized list of strings, where each strings
        is a voms command (i.e. ["dteam", "dteam:/dteam/Role=lcgadmin"])
        """
        user = request.environ['fts3.User.Credentials']
        
        if id != user.delegation_id:
            start_response('403 FORBIDDEN', [('Content-Type', 'text/plain')])
            return ['The resquested ID and the credentials ID do not match']

        try:
            voms_list = json.loads(request.body)
            if type(voms_list) != types.ListType:
                raise Exception('Expecting a list of strings')
        except Exception, e:
            start_response('400 BAD REQUEST', [('Content-Type', 'text/plain')])
            return [str(e)]

        credential = Session.query(Credential)\
            .get((user.delegation_id, user.user_dn))

        if credential.termination_time <= datetime.utcnow():
            start_response('403 FORBIDDEN', [('Content-Type', 'text/plain')])
            return ['Delegated proxy already expired']

        try:
            voms_client = voms.VomsClient(credential.proxy)
            (new_proxy, new_termination_time) = voms_client.init(voms_list)
        except voms.VomsException, e:
            # Error generating the proxy because of the request itself
            start_response('424 METHOD FAILURE', [('Content-Type', 'text/plain')])
            return [str(e)] 
        except Exception, e:
            # Internal error, re-raise it and let it fail
            raise
        
        credential.proxy = new_proxy
        credential.termination_time = new_termination_time
        credential.voms_attrs = ' '.join(voms_list)
        Session.merge(credential)
        Session.commit()
        
        start_response('203 NON-AUTHORITATIVE INFORMATION', [('Content-Type', 'text/plain')])
        return [str(new_termination_time)]
