import http from 'node:http';
import {readFileSync} from 'node:fs';
const snapshot=new URL('./observe.html',import.meta.url);
const server=http.createServer((req,res)=>{
 if(req.url==='/' || req.url==='/observe'){
  res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});
  res.end(readFileSync(snapshot));return;
 }
 const upstream=http.request({hostname:'127.0.0.1',port:3002,path:req.url,method:req.method,headers:{...req.headers,host:'localhost:3002'}},r=>{res.writeHead(r.statusCode,r.headers);r.pipe(res)});
 upstream.on('error',()=>{res.writeHead(502);res.end('Preview unavailable')});req.pipe(upstream);
});
server.listen(3003,'127.0.0.1',()=>console.log('Rendered Observe snapshot at http://127.0.0.1:3003'));
