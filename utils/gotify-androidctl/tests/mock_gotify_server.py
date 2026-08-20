import base64, json, re, sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
PORT=int(sys.argv[1]); state_path=sys.argv[2]
apps=[]; next_id=1; rotate_counter=0; create_counter=0; image_upload_counter=0

def dump():
    with open(state_path,'w') as f:
        json.dump({'apps':apps,'create_counter':create_counter,'rotate_counter':rotate_counter,'image_upload_counter':image_upload_counter},f,indent=2)
def auth_kind(h):
    a=h.headers.get('Authorization',''); x=h.headers.get('X-Gotify-Key','')
    if a.startswith('Basic '):
        try: v=base64.b64decode(a[6:]).decode()
        except Exception: return None
        if v=='admin:secret': return 'basic'
    if x=='C-elevated': return 'client-elevated'
    if x=='C-non': return 'client'
    return None
class H(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*a): pass
    def sendj(self,status,obj):
        b=json.dumps(obj).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def readb(self):
        n=int(self.headers.get('Content-Length','0') or 0); return self.rfile.read(n)
    def readj(self): return json.loads(self.readb() or b'{}')
    def do_GET(self):
        if self.path=='/version': return self.sendj(200,{'version':'3.0.0','commit':'mock','buildDate':'2026-08-20T00:00:00Z'})
        if self.path=='/application':
            if not auth_kind(self): return self.sendj(401,{'error':'unauthorized'})
            return self.sendj(200,[{k:v for k,v in a.items() if k!='token'} for a in apps])
        return self.sendj(404,{'error':'not found'})
    def do_POST(self):
        global next_id, create_counter, image_upload_counter
        if self.path=='/application':
            if not auth_kind(self): return self.sendj(401,{'error':'unauthorized'})
            body=self.readj(); name=body.get('name')
            if not name: return self.sendj(400,{'error':'name required'})
            create_counter+=1; token=f'gtfya.create{create_counter:02d}.ABCDEFGHIJKLMNOPQRSTUVWX'
            app={'id':next_id,'name':name,'description':body.get('description',''),'defaultPriority':body.get('defaultPriority',0),'internal':False,'image':'','createdAt':'2026-08-20T08:00:00Z','sortKey':f'a{next_id}','lastUsed':None,'token':token}
            next_id+=1; apps.append(app); dump(); return self.sendj(200,app)
        m=re.fullmatch(r'/application/(\d+)/image',self.path)
        if m:
            if not auth_kind(self): return self.sendj(401,{'error':'unauthorized'})
            content_type=self.headers.get('Content-Type','')
            if 'multipart/form-data' not in content_type: return self.sendj(400,{'error':'multipart required'})
            self.readb(); aid=int(m.group(1)); app=next((a for a in apps if a['id']==aid),None)
            if not app: return self.sendj(404,{'error':'not found'})
            image_upload_counter+=1; app['image']=f'image/mock-{aid}.png'; dump(); return self.sendj(200,{k:v for k,v in app.items() if k!='token'})
        if self.path=='/message':
            if not auth_kind(self): return self.sendj(401,{'error':'unauthorized'})
            body=self.readj(); return self.sendj(200,{'id':123,'appid':body.get('appid',1),'message':body.get('message',''),'title':body.get('title',''),'priority':body.get('priority',0)})
        return self.sendj(404,{'error':'not found'})
    def do_PUT(self):
        global rotate_counter
        m=re.fullmatch(r'/application/(\d+)/security',self.path)
        if m:
            kind=auth_kind(self)
            if not kind: return self.sendj(401,{'error':'unauthorized'})
            if kind=='client': return self.sendj(403,{'error':'elevation required'})
            body=self.readj()
            if body != {'regenerateToken': True}: return self.sendj(400,{'error':'bad action'})
            aid=int(m.group(1)); app=next((a for a in apps if a['id']==aid),None)
            if not app: return self.sendj(404,{'error':'not found'})
            rotate_counter+=1; token=f'gtfya.rotate{rotate_counter:02d}.ZYXWVUTSRQPONMLKJIHGFEDC'; app['token']=token; dump(); return self.sendj(200,{'regenerateToken':{'token':token}})
        m=re.fullmatch(r'/application/(\d+)',self.path)
        if m:
            if not auth_kind(self): return self.sendj(401,{'error':'unauthorized'})
            body=self.readj(); aid=int(m.group(1)); app=next((a for a in apps if a['id']==aid),None)
            if not app: return self.sendj(404,{'error':'not found'})
            for k in ('name','description','defaultPriority'):
                if k in body: app[k]=body[k]
            dump(); return self.sendj(200,{k:v for k,v in app.items() if k!='token'})
        return self.sendj(404,{'error':'not found'})
    def do_DELETE(self): return self.sendj(200,{})
dump(); ThreadingHTTPServer(('127.0.0.1',PORT),H).serve_forever()
