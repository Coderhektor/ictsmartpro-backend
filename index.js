const http = require('http');
const port = process.env.PORT || 3000;

http.createServer((req, res) => {
  res.writeHead(200, { 'Content-Type': 'text/plain' });
  res.end('ICTSmartPro Backend ŞİMDİ ÇALIŞIYOR! 🚀\nPort: ' + port + '\nZaman: ' + new Date());
}).listen(port, () => {
  console.log('Server aktif → port ' + port);
});
