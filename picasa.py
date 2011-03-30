"""
SmugMug-specific stuff for OpenWebApp Photo Connector

exposes an interface that should be generalizable to Flickr, Picasa, etc.
"""

import config
import oauth2 as oauth
import urlparse, urllib
import tornado

REQUEST_TOKEN_URL = 'https://www.google.com/accounts/OAuthGetRequestToken'
AUTHORIZE_URL = 'https://www.google.com/accounts/OAuthAuthorizeToken'
ACCESS_TOKEN_URL = 'https://www.google.com/accounts/OAuthGetAccessToken'

CONSUMER = oauth.Consumer(config.KEYS['api_key'], config.KEYS['api_secret'])


def _signed_request(method, url, params, api_key, api_secret, on_success, on_error):
    """
    sign a request and make it.
    This is an internal method, it should not be called from outside of smugmug.py
    """
    pass

def generate_authorize_url(web_handler, on_success, on_error):
    """
    When it's time to authorize a connection to a user's photo store,
    this function is called to generate the URL that the user's browser is sent to.

    on_success is called with the URL to redirect to.
    on_error is called with the error message

    this is asynchronous because of the oauth use case, which requires getting a request_token
    """
    # FIXME: make this asynchronous!
    client = oauth.Client(CONSUMER)
    resp, content = client.request("%s?%s" % (REQUEST_TOKEN_URL, urllib.urlencode({'scope': 'https://picasaweb.google.com/data/'})) , "GET", oauth_extra_params = {'oauth_callback': 'http://localhost:8411/connect/done'})

    if resp['status'] != '200':
        on_error("unable to get a request token")
        return

    # parse the request token and we are done
    request_token = dict(urlparse.parse_qsl(content))
    authorize_url = "%s?oauth_token=%s" % (AUTHORIZE_URL, request_token['oauth_token'])
    on_success(request_token, authorize_url)

def complete_authorization(web_handler, request_token, on_success, on_error):
    """
    The user is returning from authorizing the photo store, and we
    must now extract some parameters from the URL, perform some token exchange,
    which may need to be asynchronous, and continue
    
    on_success will be called with
    user_id, full_name, credentials (a dictionary)

    on_error will be called with an error message
    """
    # http = tornado.httpclient.AsyncHTTPClient()
    # http.fetch(url,  callback=self.on_response)
    token = oauth.Token(request_token['oauth_token'], request_token['oauth_token_secret'])
    token.set_verifier(web_handler.get_argument('oauth_verifier'))
    client = oauth.Client(CONSUMER, token)
    resp, content = client.request(ACCESS_TOKEN_URL, "POST")

    if resp['status'] != '200':
        on_error("unable to get an access token")
        return

    access_token = dict(urlparse.parse_qsl(content))
    on_success('foo', 'Foo Bar', access_token)

def get_photosets(user_id, credentials, on_success, on_error):
    """
    list the user's photosets
    
    on_success is called with a list of dictionaries, each one including
    id, name, num_photos

    on_error called with an error message
    """
    return None

def get_photos(user_id, credentials, photoset_id, on_success, on_error):
    """
    List a photoset's photos
    
    on_success is called with a list of dictionaries, each one including
    id, name, description, and sizes a list of size dictionaries including: {size, url}

    on_error is called with an error message
    """
    return None

##
## no write API yet
##

