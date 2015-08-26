#   Copyright notice:
#
#   Copyright CERN 2013-2015
#
#   Copyright Members of the EMI Collaboration, 2013.
#       See www.eu-emi.eu for details on the copyright holders
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

try:
    import simplejson as json
except:
    import json
import logging
from pylons import request

from fts3.model import *
from fts3rest.lib.api import doc
from fts3rest.lib.base import BaseController, Session
from fts3rest.lib.helpers import jsonify, accept, get_input_as_dict
from fts3rest.lib.http_exceptions import *
from fts3rest.lib.middleware.fts3auth import authorize, require_certificate
from fts3rest.lib.middleware.fts3auth.constants import *


__controller__ = 'CloudConfigController'
log = logging.getLogger(__name__)


class CloudConfigController(BaseController):
    """
    Configuration of cloud storages
    """

    @doc.response(403, 'The user is not allowed to modify the configuration')
    @require_certificate
    @authorize(CONFIG)
    @accept(html_template='/config/cloud_storages.html')
    def get_cloud_storages(self):
        """
        Get a list of cloud storages registered
        """
        storages = Session.query(CloudStorage).all()
        storage_list = list()
        for storage in storages:
            storage_list.append(dict(
                storage_name=storage.cloudStorage_name,
                service_api_url=storage.service_api_url
            ))
        return storage_list

    @doc.response(403, 'The user is not allowed to modify the configuration')
    @require_certificate
    @authorize(CONFIG)
    @jsonify
    def set_cloud_storage(self, start_response):
        """
        Add or modify a cloud storage entry
        """
        input_dict = get_input_as_dict(request)
        if 'name' not in input_dict:
            raise HTTPBadRequest('Missing storage name')

        storage = CloudStorage(
            cloudStorage_name=input_dict.get('name'),
            app_key=input_dict.get('key', None),
            app_secret=input_dict.get('secret', None),
            service_api_url=input_dict.get('service_api_url', None)
        )
        try:
            Session.merge(storage)
            Session.commit()
        except:
            Session.rollback()
            raise
        start_response('201 Created', [])
        return storage.cloudStorage_name

    @doc.response(403, 'The user is not allowed to modify the configuration')
    @require_certificate
    @authorize(CONFIG)
    @jsonify
    def get_cloud_storage(self, storage_name):
        """
        Get a list of users registered for a given storage name
        """
        storage = Session.query(CloudStorage).get(storage_name)
        if not storage:
            raise HTTPNotFound('The storage does not exist')

        users = Session.query(CloudStorageUser).filter(CloudStorageUser.cloudStorage_name == storage_name)
        user_list = list()
        for user in users:
            user_list.append(dict(
                user_dn=user.user_dn,
                vo_name=user.vo_name
            ))
        return user_list


    @doc.response(403, 'The user is not allowed to modify the configuration')
    @require_certificate
    @authorize(CONFIG)
    def remove_cloud_storage(self, storage_name, start_response):
        """
        Remove a registered cloud storage
        """
        storage = Session.query(CloudStorage).get(storage_name)
        if not storage:
            raise HTTPNotFound('The storage does not exist')

        try:
            Session.query(CloudStorageUser).filter(CloudStorageUser.cloudStorage_name == storage_name).delete()
            Session.delete(storage)
            Session.commit()
        except:
            Session.rollback()
            raise

        start_response('204 No Content', [])
        return storage.cloudStorage_name

    @doc.response(403, 'The user is not allowed to modify the configuration')
    @require_certificate
    @authorize(CONFIG)
    @jsonify
    def add_user_to_cloud_storage(self, storage_name, start_response):
        """
        Add a user or a VO credentials to the storage
        """
        storage = Session.query(CloudStorage).get(storage_name)
        if not storage:
            raise HTTPNotFound('The storage does not exist')

        input_dict = get_input_as_dict(request)
        user_dn = request.environ['fts3.User.Credentials'].user_dn
        if 'vo_name' in input_dict:
            user_dn = ''

        cuser = CloudStorageUser(
            user_dn=user_dn,
            cloudStorage_name=storage_name,
            access_token=input_dict.get('access_key', input_dict.get('access_token', None)),
            access_token_secret=input_dict.get('secret_key', input_dict.get('access_token_secret', None)),
            request_token=input_dict.get('request_token'),
            request_token_secret=input_dict.get('request_token_secret'),
            vo_name=input_dict.get('vo_name', None),
        )

        try:
            Session.merge(cuser)
            Session.commit()
        except:
            Session.rollback()
            raise

        start_response('201 Created', [])
        return dict(storage_name=cuser.cloudStorage_name, user_dn=cuser.user_dn, vo_name=cuser.vo_name)

    @doc.response(403, 'The user is not allowed to modify the configuration')
    @require_certificate
    @authorize(CONFIG)
    def remove_user_from_cloud_storage(self, storage_name, id, start_response):
        """
        Delete credentials for a given user/vo
        """
        storage = Session.query(CloudStorage).get(storage_name)
        if not storage:
            raise HTTPNotFound('The storage does not exist')

        users = Session.query(CloudStorageUser)\
            .filter(CloudStorageUser.cloudStorage_name == storage_name)\
            .filter((CloudStorageUser.vo_name == id) | (CloudStorageUser.user_dn == id))

        try:
            for user in users:
                Session.delete(user)
            Session.commit()
        except:
            Session.rollback()
            raise

        start_response('204 No Content', [])
        return ['']
