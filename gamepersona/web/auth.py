"""Library-verified OpenID 2.0, restricted to the documented Steam provider."""
import hashlib
import re
import time
from urllib.parse import urlencode

import httpx
from openid.consumer.consumer import GenericConsumer, SUCCESS
from openid.consumer.discover import OpenIDServiceEndpoint, OPENID_2_0_TYPE
from openid.message import Message
from openid.store.interface import OpenIDStore

STEAM_OP = 'https://steamcommunity.com/openid/login'
OPENID_NS = 'http://specs.openid.net/auth/2.0'
IDENTIFIER_SELECT = OPENID_NS+'/identifier_select'


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


class NonceStore(OpenIDStore):
    def __init__(self, db):
        self.db = db

    def getAssociation(self,*args):
        return None  # Deliberately use direct check_authentication over HTTPS.

    def removeAssociation(self,*args):
        return False

    def useNonce(self,server_url,timestamp,salt):
        if abs(time.time()-timestamp)>600 or server_url!=STEAM_OP:
            return False
        with self.db.connect() as con:
            con.execute('DELETE FROM openid_nonces WHERE expires_at<now()')
            return bool(con.execute("INSERT INTO openid_nonces VALUES(%s,now()+interval '20 minutes') ON CONFLICT DO NOTHING RETURNING nonce_hash",
                (token_hash(f'{server_url}:{timestamp}:{salt}'),)).fetchone())


class SteamConsumer(GenericConsumer):
    def __init__(self, db, client_factory=httpx.Client):
        super().__init__(NonceStore(db))
        self.client_factory = client_factory

    def _checkAuth(self,message,server_url):
        if server_url!=STEAM_OP:
            return False
        request = self._createCheckAuthRequest(message)
        if request is None:
            return False
        try:
            with self.client_factory(follow_redirects=False,timeout=20) as client:
                response = client.post(STEAM_OP,data=request.toPostArgs())
            values = dict(line.split(':',1) for line in response.text.splitlines() if ':' in line)
            return response.status_code==200 and values.get('is_valid')=='true' and values.get('ns')==OPENID_NS
        except httpx.HTTPError:
            return False


class SteamOpenID:
    def __init__(self, db, client_factory=httpx.Client):
        self.consumer = SteamConsumer(db,client_factory)

    def login_url(self, origin, return_to):
        return STEAM_OP+'?'+urlencode({'openid.ns':OPENID_NS,'openid.mode':'checkid_setup',
             'openid.return_to':return_to,'openid.realm':origin+'/',
             'openid.identity':IDENTIFIER_SELECT,'openid.claimed_id':IDENTIFIER_SELECT})

    def verify(self, parameters, return_to):
        claimed = parameters.get('openid.claimed_id','')
        match = re.fullmatch(r'https?://steamcommunity\.com/openid/id/(\d{17})',claimed)
        if (not match or parameters.get('openid.identity')!=claimed or parameters.get('openid.ns')!=OPENID_NS
                or parameters.get('openid.op_endpoint')!=STEAM_OP or parameters.get('openid.return_to')!=return_to):
            return None
        # Steam's fixed account namespace and OP endpoint replace generic discovery.
        # The library still verifies signed fields, direct signature, return_to and nonce.
        endpoint = OpenIDServiceEndpoint()
        endpoint.claimed_id = endpoint.local_id = claimed
        endpoint.server_url = STEAM_OP
        endpoint.type_uris = [OPENID_2_0_TYPE]
        response = self.consumer.complete(Message.fromPostArgs(parameters),endpoint,return_to)
        return match[1] if response.status==SUCCESS else None
