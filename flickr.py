"""
Picasa-specific stuff for OpenWebApp Photo Connector

exposes an interface that should be generalizable to Flickr, Picasa, etc.
"""

import config
import urlparse, urllib
import tornado
import simplejson
import hashlib
import cStringIO
import logging
import base64

import utils

def _sign_request(request):
    "now returns the full set of parameters ready for URL embedding"

    sigval = config.KEYS["flickrSecret"]

    full_request =  {'api_key' : config.KEYS["flickrAPIKey"]}
    full_request.update(request)

    keys = full_request.keys()
    keys.sort()
    for k in keys:
      sigval += unicode(k)
      sigval += unicode(full_request[k])
    full_request['api_sig'] = hashlib.md5(sigval).hexdigest()

    return full_request, urllib.urlencode(full_request)

def _sign_request_url_only(request):
    return _sign_request(request)[1]

def generate_authorize_url(web_handler, url_callback, on_success, on_error):
    """
    When it's time to authorize a connection to a user's photo store,
    this function is called to generate the URL that the user's browser is sent to.

    on_success is called with the URL to redirect to.
    on_error is called with the error message

    this is asynchronous because of the oauth use case, which requires getting a request_token
    """
    request = {
        'perms' : "write",
        }

    # url_callback is ignored, it needs to be set in the Flickr app itself

    # no request token, so None
    on_success(None,"http://flickr.com/services/auth/?%s" % _sign_request_url_only(request))


def complete_authorization(web_handler, request_token, on_success, on_error):
    """
    The user is returning from authorizing the photo store, and we
    must now extract some parameters from the URL, perform some token exchange,
    which may need to be asynchronous, and continue
    
    on_success will be called with
    user_id, full_name, credentials (a dictionary)

    on_error will be called with an error message
    """

    frob = web_handler.get_argument("frob", None)
    if not frob:
      on_error("Failed Flickr authentication - no frob")
      return

    request = {
        'method' : 'flickr.auth.getToken',
        'frob' : frob,
        'format' : 'json',
        'nojsoncallback': "1"
        }
        
    url = "http://api.flickr.com/services/rest/?%s" % _sign_request_url_only(request)

    def on_response(response):
        if response.error:
            on_error(response.error)
            return
        
        # response body looks like this:   {"auth":{"token":{"_content":"72157626196623223-9271de4a076fd149"}, "perms":{"_content":"read"}, 
        # "user":{"nsid":"48465434@N07", "username":"michaelrhanson", "fullname":""}}, "stat":"ok"}
        try:
            result = simplejson.loads(response.body)
            if result["stat"] != "ok":
                on_error("Whoops, sorry, something didn't work right.  There was an error returned by Flickr.")
                logging.error(response.body)
            else:
                # user_id, user name, credentials
                on_success(result['auth']['user']['nsid'], result['auth']['user']['username'], result['auth']['token']['_content'])
        except Exception, e:
            on_error("Whoops, sorry, something didn't work right.  There was an error in our application: %s" % e)
            logging.error(e)

    http = tornado.httpclient.AsyncHTTPClient()
    http.fetch(url, callback=on_response)

def get_photosets(user_id, credentials, on_success, on_error):
    """
    list the user's photosets
    
    on_success is called with a list of dictionaries, each one including
    id, name, num_photos

    on_error called with an error message
    """

    request = {
        'method' : 'flickr.photosets.getList',
        'user_id' : user_id,
        'format' : 'json',
        'nojsoncallback': "1",
        'auth_token': credentials,
        }
        
    url = "http://api.flickr.com/services/rest/?%s" % _sign_request_url_only(request)

    def on_response(response):
        if response.error:
            on_error(response.error)
            return

        photosets_feed = simplejson.loads(response.body)

        photosets = [{'id': photoset['id'],
                      'name': photoset['title']['_content'],
                      'num_photos': int(photoset['photos'])} for photoset in photosets_feed['photosets']['photoset']]

        on_success(photosets)

    http = tornado.httpclient.AsyncHTTPClient()
    http.fetch(url, callback=on_response)


def get_photos(user_id, credentials, photoset_id, on_success, on_error):
    """
    List a photoset's photos
    
    on_success is called with a list of dictionaries, each one including
    id, name, description, and sizes a list of size dictionaries including: {size, url}

    on_error is called with an error message
    """

    request = {
        'method' : 'flickr.photosets.getPhotos',
        'user_id' : user_id,
        "photoset_id": photoset_id,
        "extras": "url_sq,url_t,url_s,url_m,url_z,url_l,url_o,icon_server,tags",
        'format' : 'json',
        'nojsoncallback': "1",
        'auth_token': credentials,
        }
        
    url = "http://api.flickr.com/services/rest/?%s" % _sign_request_url_only(request)

    def on_response(response):
        if response.error:
            on_error(response.error)
            return

        photos_feed = simplejson.loads(response.body)

        photos = [{
                'id': photo['id'],
                'name': photo['title'],
                'sizes': [
                    {
                        'size': 'thumbnail',
                        'height': photo['height_t'],
                        'width': photo['width_t'],
                        'url' : photo['url_t']
                        },
                    {
                        'size': 'small',
                        'height': photo['height_s'],
                        'width': photo['width_s'],
                        'url' : photo['url_s']
                        },
                    {
                        'size': 'medium',
                        'height': photo['height_m'],
                        'width': photo['width_m'],
                        'url' : photo['url_m']
                        },
                    {
                        'size': 'master',
                        'height': photo['height_o'],
                        'width': photo['width_o'],
                        'url' : photo['url_o']
                        },
                    ]
                } for photo in photos_feed['photoset']['photo']]

        on_success(photos)

    http = tornado.httpclient.AsyncHTTPClient()
    http.fetch(url, callback=on_response)

def store_photo(user_id, credentials, photo, title, description, tags, on_success, on_error):
    photoFile = cStringIO.StringIO(base64.b64decode(photo));

    request = {
        "auth_token": credentials
        }

    if description: request["description"] = description
    if title: request["title"] = title
    if tags: request["tags"] = tags

    full_request, full_request_urlencoded = _sign_request(request)

    boundary, body = utils.multipart_encode(full_request.items(), [ ("photo", "thefile.jpg", photoFile, "image/jpg" ) ])

    headers = { "Content-Type": "multipart/form-data; boundary=" + boundary }

    httpRequest = tornado.httpclient.HTTPRequest(
        "http://api.flickr.com/services/upload/",
        method = "POST",
        headers = headers,
        body = body
        )

    def on_response(response):
        if response.error:
            on_error(response.error)
            return
        
        on_success(response.body)

    http = tornado.httpclient.AsyncHTTPClient()      
    http.fetch(httpRequest, callback=on_response)
    
