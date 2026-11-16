# -*- coding: utf-8 -*-
import base64
import json
import zlib
_PAYLOAD = (
    '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'
)
_DOC = json.loads(zlib.decompress(base64.b64decode(_PAYLOAD)).decode('utf-8'))
SHELLS = _DOC['shells']
FALLBACK_PACKAGE = _DOC['fallback']
A_NS = 'http://schemas.openxmlformats.org/drawingml/2006/main'
P_NS = 'http://schemas.openxmlformats.org/presentationml/2006/main'
R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG_REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
CORE_PROPS = 'http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties'
CONTENT_PREFIX = 'application/vnd.openxmlformats-officedocument.'
NS_DECL = 'xmlns:a="%s" xmlns:r="%s" xmlns:p="%s"' % (A_NS, R_NS, P_NS)
CANVAS_W, CANVAS_H = 12192000, 6858000
PROLOG = '<?xml version="1.0" encoding="UTF-8"?>\n'

def shells():
    return SHELLS

def fallback_design():
    return FALLBACK_PACKAGE

def fallback_parts():
    return {name: body.encode('utf-8') for name, body in FALLBACK_PACKAGE.items()}
