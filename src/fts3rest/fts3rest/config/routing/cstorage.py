#   Copyright notice:
#   Copyright  Members of the EMI Collaboration, 2013.
#
#   See www.eu-emi.eu for details on the copyright holders
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


def do_connect(config, map):
    """
    Cloud Storage
    """
    map.connect('/cs/registered/{service}', controller='cloudStorage', action='is_registered',
                conditions=dict(method=['GET']))
    map.connect('/cs/access_request/{service}', controller='cloudStorage', action='is_access_requested',
                conditions=dict(method=['GET']))
    map.connect('/cs/access_request/{service}/', controller='cloudStorage', action='is_access_requested',
                conditions=dict(method=['GET']))
    map.connect('/cs/access_grant/{service}', controller='cloudStorage', action='remove_token',
                conditions=dict(method=['DELETE']))
    map.connect('/cs/access_request/{service}/request', controller='cloudStorage', action='get_access_requested',
                conditions=dict(method=['GET']))
    map.connect('/cs/access_grant/{service}', controller='cloudStorage', action='get_access_granted',
                conditions=dict(method=['GET']))
    map.connect('/cs/remote_content/{service}', controller='cloudStorage', action='get_folder_content',
                conditions=dict(method=['GET']))
    map.connect('/cs/file_urllink/{service}/{path}', controller='cloudStorage', action='get_file_link',
                conditions=dict(method=['GET']))
