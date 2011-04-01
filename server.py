#!/usr/bin/env python
#
import tornado.httpserver
import tornado.auth
import tornado.ioloop
import tornado.web
import os, sys
import base64
import json
import hashlib
import urllib
import cStringIO
import mimetools
import simplejson

# search for server configuration (API keys and such)
CONFIG_FILE_NAME = 'config.py'
if os.path.exists(CONFIG_FILE_NAME):
  import config
elif os.path.exists(os.path.join("..", CONFIG_FILE_NAME)):
  sys.path.append('..')
  import config
  sys.path.pop()
else:
  raise RuntimeError('no configuration file found: %s' % CONFIG_FILE_NAME)

# photo provider stuff
# dynamically import the right module

APP_NAME = config.PHOTO_SITE.lower() 
DOMAIN = "https://%s.mozillalabs.com" % APP_NAME

photosite = __import__(config.PHOTO_SITE.lower())

class WebHandler(tornado.web.RequestHandler):
  "base handler for this entire app"

  def get_error_html(self, status_code, **kwargs):
    return """
<html><title>Error!</title><style>.box {margin:16px;padding:8px;border:1px solid black;font:14pt Helvetica,arial}
.small {text-align:right;color:#888;font:italic 8pt Helvetica;}</style>
<body><div class='box'>We're sorry, something went wrong!<br><br>Perhaps
you should <a href='/'>return to the front page.</a><br><br><div class='small'>%s %s</div></div>
""" % (status_code, kwargs['exception'])

  def get_user_id_and_credentials(self):
    user_id = self.get_argument("user_id", None)
    credentials_json = self.get_argument("credentials", None)
    if not user_id or not credentials_json:
      raise Exception("missing user_id and credentials")

    try:
      credentials = simplejson.loads(credentials_json)
    except:
      raise Exception("bad credentials -- JSON")
      
    return user_id, credentials
    
  def render_platform(self, file, templates=False, **kwargs):
    target_file = file

    if  "User-Agent" in self.request.headers:
      UA = self.request.headers["User-Agent"]
      if UA.find("iPhone") >= 0:
        target_file = target_file + "_iphone"
    if self.get_argument("cloak", None):
      target_file = file + "_" + self.get_argument("cloak", None)

    # is this dead code? Not sure what this is used for (Ben 2011-03-29)
    tmpl = None
    if templates:
      f = open(target_file + ".tmpl", "r")
      tmpl = f.read()
      f.close() # cache this

    self.render(target_file + ".html", templates=tmpl, **kwargs)

  # Put auth_token in before you call this
  def sign_request(self, request):
    sigval = config.KEYS["flickrSecret"]
    keys = request.keys()
    keys.sort()
    for k in keys:
      sigval += unicode(k)
      sigval += unicode(request[k])
    sighash = hashlib.md5(sigval).hexdigest()
    return sighash
            
# General, and user administration, handlers
class MainHandler(WebHandler):
  def get(self):
    self.set_header("X-XRDS-Location", "%s/xrds" % DOMAIN)
    self.render_platform("index", app_name=APP_NAME, errorMessage=None)

class XRDSHandler(WebHandler):
  def get(self):
    self.set_header("Content-Type", "application/xrds+xml")
    self.write("""<?xml version="1.0" encoding="UTF-8"?>"""\
      """<xrds:XRDS xmlns:xrds="xri://$xrds" xmlns:openid="http://openid.net/xmlns/1.0" xmlns="xri://$xrd*($v*2.0)">"""\
      """<XRD><Service priority="1"><Type>https://specs.openid.net/auth/2.0/return_to</Type>"""\
      """<URI>%s/login</URI>"""\
      """</Service></XRD></xrds:XRDS>""" % DOMAIN)

class Connect(WebHandler):
  @tornado.web.asynchronous
  def get(self):
    photosite.generate_authorize_url(self, "%s/connect/done" % config.URL_BASE, self.on_response, self.on_error)

  def on_response(self, request_token, authorize_url):
    if request_token:
      # a token to store for closing the connection loop
      self.set_secure_cookie('request_token', simplejson.dumps(request_token))

    self.redirect(authorize_url)
  
  def on_error(self, error):
    self.write("error: " + error)
    self.finish()

class ConnectDone(WebHandler):
  @tornado.web.asynchronous
  def get(self):
    request_token = simplejson.loads(self.get_secure_cookie('request_token'))
    photosite.complete_authorization(self, request_token, self.on_success, self.on_error)

  def on_success(self, user_id, full_name, credentials):
    self.render_platform("setcredentials", user_info={'user_id': user_id, 'full_name' : full_name, 'credentials' : simplejson.dumps(credentials)}, app_name=APP_NAME)
  
  def on_error(self, message):
    self.write(message)
    self.finish()

class Photosets(WebHandler):
  @tornado.web.asynchronous
  def get(self):
    user_id, credentials = self.get_user_id_and_credentials()
    photosite.get_photosets(user_id, credentials, self.on_success, self.on_error)

  def on_success(self, photosets):
    self.write(simplejson.dumps(photosets))
    self.finish()

  def on_error(self, message):
    import logging
    logging.log("error: %s" % message)
    self.write("error: %s" % message)
    self.finish()

class Photos(WebHandler):
  @tornado.web.asynchronous
  def get(self):
    user_id, credentials = self.get_user_id_and_credentials()
    photoset_id = self.get_argument("photoset_id", None)
    if not photoset_id:
      raise Exception("Missing required photosetid")
      
    photosite.get_photos(user_id, credentials, photoset_id, self.on_success, self.on_error)

  def on_success(self, photos):
    self.write(simplejson.dumps(photos))
    self.finish()

  def on_error(self, message):
    self.write("error: %s" % message)
    self.finish()


class GetPhotoSizes(WebHandler):
  @tornado.web.asynchronous
  def get(self):
    photoID = self.get_argument("photoid", None)
    if not photoid:
      raise Exception("Missing required photoid")
    authToken = self.get_argument("token", None)
    if not authToken:
      raise Exception("Missing required token")
      
    http = tornado.httpclient.AsyncHTTPClient()
    request = {
      "auth_token":authToken,
      "api_key": config.KEYS["flickrAPIKey"],
      "method":"flickr.photos.getSizes",
      "photo_id": photoID,
      "format":"json",
      "nojsoncallback":1,
    }
    signature = self.sign_request(request)
    request["api_sig"] = signature
    req = ["%s=%s" % (key, request[key]) for key in request.keys()] # XX urlescape
    url = "http://api.flickr.com/services/rest/?%s" % "&".join(req)
    http.fetch(url,  callback=self.on_response)

  def on_response(self, response):
    if response.error: raise tornado.web.HTTPError(500)
    json = tornado.escape.json_decode(response.body)
    self.write(response.body)
    self.finish()

class PostPhoto(WebHandler):
  @tornado.web.asynchronous
  def post(self):
    user_id, credentials = self.get_user_id_and_credentials()

    photo = self.get_argument("photo", None) #base64ed?
    photo_url = self.get_argument("photo_url", None) #base64ed?
    title = self.get_argument("title", None)
    description = self.get_argument("description", None)
    tags = self.get_argument("tags", None) # space-separated
    
    # did we get a photo_url instead?
    if not photo and not photo_url:
      raise Exception("no photo")

    if photo and photo_url:
      raise Exception("only submit photo or photo_url")

    def do_it(photo_data):
      photosite.store_photo(user_id, credentials, photo_data, title, description, tags,
                            on_success= self.on_success,
                            on_error= self.on_error)
    
    if photo_url:
      # we have to go fetch it
      http = tornado.httpclient.AsyncHTTPClient()
      
      # assume success for now
      http.fetch(photo_url, callback=lambda response: do_it(base64.b64encode(response.body)))
    else:
      do_it(photo)

  def on_success(self, response_xml):
    self.write(response_xml)
    self.finish()

  def on_error(self, message):
    self.write("error: %s" % message)
    self.finish()


class Service_GetImage(WebHandler):
  def get(self):
    self.render("service_getImage.html")

class Service_SendImage(WebHandler):
  def get(self):
    self.render("service_sendImage.html")

class WebAppManifestHandler(WebHandler):
  def get(self):
    self.set_header("Content-Type", "application/x-web-app-manifest+json")
    self.render("%s.webapp" % APP_NAME)


##################################################################
# Main Application Setup
##################################################################

settings = {
    "static_path": os.path.join(os.path.dirname(__file__), "static"),
    "login_url": "/login",
    "cookie_secret": config.COOKIE_SECRET,
    "debug":True,
    "xheaders":True,
#    "xsrf_cookies": True,
}

application = tornado.web.Application([
    (r"/%s.webapp" % APP_NAME, WebAppManifestHandler),
    (r"/connect/done", ConnectDone),
    (r"/connect/start", Connect),
    (r"/get/photosets", Photosets),
    (r"/get/photos", Photos),
    (r"/get/photosizes", GetPhotoSizes),
    (r"/post/photo", PostPhoto),
    (r"/service/getImage", Service_GetImage),
    (r"/service/sendImage", Service_SendImage),
    (r"/xrds", XRDSHandler),
    (r"/", MainHandler),
 
	], **settings)


def run():
    http_server = tornado.httpserver.HTTPServer(application)
    http_server.listen(config.PORT)
    
    print "Starting server on %s" % config.PORT
    tornado.ioloop.IOLoop.instance().start()
		
import logging
import sys
if __name__ == '__main__':
	if '-test' in sys.argv:
		import doctest
		doctest.testmod()
	else:
		logging.basicConfig(level = logging.DEBUG)
		run()
	
	
