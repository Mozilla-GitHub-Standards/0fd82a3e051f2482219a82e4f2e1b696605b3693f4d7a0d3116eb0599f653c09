"""
Picasa-specific stuff for OpenWebApp Photo Connector

exposes an interface that should be generalizable to Flickr, Picasa, etc.
"""

import config
import oauth2 as oauth
import urlparse, urllib
import tornado
import simplejson
import cStringIO, base64
import utils

from xml.sax.saxutils import escape as xml_escape

REQUEST_TOKEN_URL = 'https://www.google.com/accounts/OAuthGetRequestToken'
AUTHORIZE_URL = 'https://www.google.com/accounts/OAuthAuthorizeToken'
ACCESS_TOKEN_URL = 'https://www.google.com/accounts/OAuthGetAccessToken'

CONSUMER = oauth.Consumer(config.KEYS['api_key'], config.KEYS['api_secret'])

def _signed_request(method, url, params, oauth_extra_params, credentials, on_success, on_error, headers={}):
    """
    sign a request and make it.
    This is an internal method, it should not be called from outside of this file
    
    url is a GET URL without parameters
    params is a dictionary of parameters, either appended to the URL if a GET, or as a form if a POST

    if url is POST and params is a string, then treat it as raw body.

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

    # append to the URL if it's a GET, or set the body if it's a POST
    if params:
        if type(params) == dict:
            encoded_params = urllib.urlencode(params)
            
            if method == "GET":
                body = ''
                full_url += "?%s" % encoded_params
            else:
                body = encoded_params
        else:
            if method == "GET":
                raise Exception("on a GET, params must be a dictionary")
            else:
                body = params
            
    resp, content = client.request(full_url, method, body = body,
                                   headers = headers,
                                   oauth_extra_params=oauth_extra_params)

    if resp['status'] not in ['200', '201', '202']:
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
        authorize_url = "%s?oauth_token=%s" % (AUTHORIZE_URL, request_token['oauth_token'])
        on_success(request_token, authorize_url)

    _signed_request("GET", url=REQUEST_TOKEN_URL, params={'scope': 'https://picasaweb.google.com/data/'},
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
        on_success('foo', 'Foo Bar', access_token)

    _signed_request("POST", url=ACCESS_TOKEN_URL, params={'oauth_verifier': web_handler.get_argument('oauth_verifier')},
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

        photosets = [{'id': photoset['gphoto$id']['$t'],
                      'name': photoset['gphoto$name']['$t'],
                      'num_photos': photoset['gphoto$numphotos']['$t']} for photoset in photosets_feed['feed']['entry']]

        # navigate to the part of the feed that is needed
        on_success(photosets)

    _signed_request("GET","https://picasaweb.google.com/data/feed/api/user/default", params={"alt":"json"},
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

    # higher value always first, doesn't matter if landscape or portrait
    PICASA_SIZE_TAGS = {
        '1600x1066' : 'medium',
        '72x48' : 'thumbnail',
        '144x96' : 'tiny',
        '288x192' : 'small',
        }
    
    def picasa_size_tag(photo_el):
        first = max(photo_el['width'], photo_el['height'])
        second = min(photo_el['width'], photo_el['height'])
        return PICASA_SIZE_TAGS.get("%sx%s" % (first,second), 'width-%s' % photo_el['width'])
        
    def internal_on_success(content):
        photo_feed = simplejson.loads(content)

        photos = [{'id': photo['gphoto$id']['$t'],
                   'name': photo['summary']['$t'],
                   'description': photo['summary']['$t'],
                   # combine the master and content and thumbnails
                   'sizes': [{
                        'size': 'master',
                        'width': photo['gphoto$width']['$t'],
                        'height': photo['gphoto$height']['$t'],
                        'url': photo['content']['src']}] + [{
                        'size': picasa_size_tag(content),
                        'width': content['width'],
                        'height': content['height'],
                        'url' : content['url']
                        } for content in photo['media$group']['media$content']] + [{
                        'size': picasa_size_tag(thumbnail),
                        'width': thumbnail['width'],
                        'height': thumbnail['height'],
                        'url' : thumbnail['url']
                        } for thumbnail in photo['media$group']['media$thumbnail']]
                   } for photo in photo_feed['feed']['entry']]
        
        # navigate to the part of the feed that is needed
        on_success(photos)

    _signed_request("GET","https://picasaweb.google.com/data/feed/api/user/default/albumid/%s" % photoset_id, params={"alt":"json"},
                    oauth_extra_params = None,
                    credentials = credentials,
                    on_success = internal_on_success,
                    on_error = lambda content: on_error("couldn't get photos: %s" % content))

def store_photo(user_id, credentials, photoset_id, photo, title, description, tags, on_success, on_error):
    """
    this will call on_success with a dictionary of the new image,
    including 'id' and 'url'
    """
    # in smugmug, the base64-encoded photo is what we need to upload
    def internal_on_success(content):
        "it's XML, let's just pass it for now"
        on_success(content)
    
    def internal_on_error(error):
        on_error("couldn't upload image: %s" % error)

    # prepare a multipart-mime message
        
    # first the Atom description (FIXME: XML inline is kinda ugly)
    metadata = """
<entry xmlns='http://www.w3.org/2005/Atom'>
  <title>%s</title>
  <summary>%s</summary>
  <category scheme="http://schemas.google.com/g/2005#kind"
    term="http://schemas.google.com/photos/2007#photo"/>
</entry>
""" % (xml_escape(title), xml_escape(description))

    # treat the photo as a file
    photo_file = cStringIO.StringIO(base64.b64decode(photo))

    boundary, body = utils.multipart_encode(
        vars={},
        vars_with_types= [("application/atom+xml", metadata)],
        files= [("photo", "thefile.jpg", photo_file, "image/jpg")]
        )

    # prepend a bogus line, as per picasa spec (is this MIME?)
    full_body = """
Media multipart posting
%s""" % body

    headers = { "Content-Type": "multipart/related; boundary=" + boundary,
                "Content-Length": str(len(full_body)),
                "MIME-Version": "1.0",}

    _signed_request("POST",
                    "https://picasaweb.google.com/data/feed/api/user/default/albumid/%s" % photoset_id,
                    params=full_body,
                    oauth_extra_params = None,
                    credentials = credentials,
                    on_success = internal_on_success,
                    on_error = internal_on_error,
                    headers = headers)
        


    

