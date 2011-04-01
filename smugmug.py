"""
SmugMug-specific stuff for OpenWebApp Photo Connector

exposes an interface that should be generalizable to Flickr, Picasa, etc.
"""

import config
import oauth2 as oauth
import urlparse, urllib
import tornado
import simplejson

REQUEST_TOKEN_URL = 'http://api.smugmug.com/services/oauth/getRequestToken.mg'
AUTHORIZE_URL = 'http://api.smugmug.com/services/oauth/authorize.mg'
ACCESS_TOKEN_URL = 'http://api.smugmug.com/services/oauth/getAccessToken.mg'

CONSUMER = oauth.Consumer(config.KEYS['api_key'], config.KEYS['api_secret'])

API_BASE = 'http://api.smugmug.com/services/api/json/1.3.0/'

def _signed_request(method, url, params, oauth_extra_params, credentials, on_success, on_error):
    """
    sign a request and make it.
    This is an internal method, it should not be called from outside of this file
    
    url is a GET URL without parameters
    params is a dictionary of parameters, either appended to the URL if a GET, or as a form if a POST

    credentials is a dictionary of oauth_token and oauth_token_secret. It can be null.

    The goal is to make this asynchronous at some point soon.
    """

    # do we need an OAuth token, or just the consumer?
    if credentials:
        token = oauth.Token(credentials['oauth_token'], credentials['oauth_token_secret'])
        client = oauth.Client(CONSUMER, token)
    else:
        client = oauth.Client(CONSUMER)

    full_url = url
    body = ''

    # append to the URL if it's a GET, or set the body if it's a POST
    if params:
        encoded_params = urllib.urlencode(params)
        if method == "GET":
            full_url += "?%s" % encoded_params
        else:
            body = encoded_params

    resp, content = client.request(full_url, method, body = body, oauth_extra_params=oauth_extra_params)

    if resp['status'] != '200':
        on_error(content)
    else:
        on_success(content)


def generate_authorize_url(web_handler, url_callback, on_success, on_error):
    """
    When it's time to authorize a connection to a user's photo store,
    this function is called to generate the URL that the user's browser is sent to.

    on_success is called with the URL to redirect to.
    on_error is called with the error message

    this is asynchronous because of the oauth use case, which requires getting a request_token
    """

    def internal_on_success(content):
        request_token = dict(urlparse.parse_qsl(content))
        authorize_url = "%s?%s" % (AUTHORIZE_URL, 
                                   urllib.urlencode({
                    'oauth_token':request_token['oauth_token'],
                    'Access':'Full',
                    'Permissions':'Modify'}))
        on_success(request_token, authorize_url)

    _signed_request("GET", url=REQUEST_TOKEN_URL, params=None,
                    oauth_extra_params={'oauth_callback': url_callback},
                    credentials = None,
                    on_success = internal_on_success,
                    on_error = lambda content: on_error("couldn't get a request token - %s" % content))

def complete_authorization(web_handler, request_token, on_success, on_error):
    """
    The user is returning from authorizing the photo store, and we
    must now extract some parameters from the URL, perform some token exchange,
    which may need to be asynchronous, and continue
    
    on_success will be called with
    user_id, full_name, credentials (a dictionary)

    on_error will be called with an error message
    """

    def internal_on_success(content):
        access_token = dict(urlparse.parse_qsl(content))
        # FIXME: get real name?
        on_success('foo', 'Foo Bar', access_token)

    _signed_request("POST", url=ACCESS_TOKEN_URL, params=None,
                    oauth_extra_params = None,
                    credentials = request_token,
                    on_success = internal_on_success,
                    on_error = lambda content: on_error("couldn't get an access token %s" % content))


def get_photosets(user_id, credentials, on_success, on_error):
    """
    list the user's photosets
    
    on_success is called with a list of dictionaries, each one including
    id, name, num_photos

    on_error called with an error message
    """

    def internal_on_success(content):
        photosets_feed = simplejson.loads(content)

        # because smugmug requires both the album id and album key to access stuff
        # we package them together into the ID to keep the API the same
        photosets = [{'id': "%s/%s" % (photoset['id'], photoset['Key']),
                      'name': photoset['Title'],
                      'num_photos': photoset['ImageCount']} for photoset in photosets_feed['Albums']]

        # navigate to the part of the feed that is needed
        on_success(photosets)

    _signed_request("GET",API_BASE, params= {'method': "smugmug.albums.get", 'Extras': "ImageCount"},
                    oauth_extra_params = None,
                    credentials = credentials,
                    on_success = internal_on_success,
                    on_error = lambda content: on_error("couldn't get photosets: %s" % content))


def get_photos(user_id, credentials, photoset_id, on_success, on_error):
    """
    List a photoset's photos
    
    on_success is called with a list of dictionaries, each one including
    id, name, description, and sizes a list of size dictionaries including: {size, url}

    on_error is called with an error message
    """
        
    def internal_on_success(content):
        photo_feed = simplejson.loads(content)

        photos = [{'id': photo['id'],
                   'name': photo['FileName'],
                   'description': photo['Caption'],
                   # combine the master and content and thumbnails
                   'sizes': [{
                        'size': 'master',
                        'width': photo['Width'],
                        'height': photo['Height'],
                        'url': photo['OriginalURL']},
                             {
                        'size': 'small',
                        'url': photo['SmallURL']},
                             {
                        'size': 'medium',
                        'url': photo['MediumURL']},
                             {
                        'size': 'large',
                        'url': photo['LargeURL']},
                             {
                        'size': 'tiny',
                        'url': photo['TinyURL']},
                             {
                        'size': 'thumbnail',
                        'url': photo['ThumbURL']},
                             ]
                   } for photo in photo_feed['Album']['Images']]

        # navigate to the part of the feed that is needed
        on_success(photos)

    album_id, album_key = photoset_id.split("/")
    _signed_request("GET",API_BASE, params={"method":"smugmug.images.get", "AlbumID": album_id, "AlbumKey": album_key, "Heavy" : "true"},
                    oauth_extra_params = None,
                    credentials = credentials,
                    on_success = internal_on_success,
                    on_error = lambda content: on_error("couldn't get photos: %s" % content))


def store_photo(user_id, credentials, photo, title, description, tags, on_success, on_error):
    """
    this will call on_success with a dictionary of the new image,
    including 'id' and 'url'
    """
    # in smugmug, the base64-encoded photo is what we need to upload
    def internal_on_success(content):
        result = simplejson.loads(content)
        on_success({'id': result['Image']['id'],
                    'url': result['Image']['URL']})

    def after_fetch_photosets(photosets):
        _signed_request("POST",API_BASE, params= {'method': "smugmug.images.upload",
                                                  'Data': photo,
                                                  'AlbumID': photosets[0]['id'].split("/")[0],
                                                  'Caption': title or '',
                                                  'Keywords': tags or ''},
                        oauth_extra_params = None,
                        credentials = credentials,
                        on_success = internal_on_success,
                        on_error = lambda content: on_error("couldn't upload image"))
        
    # for now we'll store in the first album
    # FIXME: we should refactor this
    get_photosets(user_id, credentials,
                  on_success= after_fetch_photosets,
                  on_error= lambda content: on_error("couldn't get photosets to upload image"))


    
