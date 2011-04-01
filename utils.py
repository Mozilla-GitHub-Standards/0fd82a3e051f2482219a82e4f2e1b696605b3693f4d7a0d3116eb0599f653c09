"""
some common utilities
"""

import mimetools
import cStringIO
import os

def multipart_encode(vars, files, vars_with_types= [], boundary = None, buf = None):
    if boundary is None:
        boundary = mimetools.choose_boundary()
    if buf is None:
        buf = cStringIO.StringIO()
    for(key, value) in vars:
        buf.write('--%s\r\n' % boundary)
        buf.write('Content-Disposition: form-data; name="%s"' % key)
        buf.write('\r\n\r\n' + value + '\r\n')
    for (contenttype, content) in vars_with_types:
        buf.write('--%s\r\n' % boundary)
        buf.write('Content-Type: %s\r\n\r\n' % contenttype)
        buf.write('%s\r\n' % content)
    for(name, filename, file, contenttype) in files:
        file.seek(os.SEEK_END)
        file_size = file.tell()
        file.seek(os.SEEK_SET)
        buf.write('--%s\r\n' % boundary)
        buf.write('Content-Disposition: form-data; name="%s"; filename="%s"\r\n' % (name, filename))
        buf.write('Content-Type: %s\r\n' % contenttype)
        # buffer += 'Content-Length: %s\r\n' % file_size
        buf.write('\r\n' + file.read() + '\r\n')
    buf.write('--' + boundary + '--\r\n\r\n')
    buf = buf.getvalue()
    return boundary, buf

