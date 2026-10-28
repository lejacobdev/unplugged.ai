#!/bin/bash
# One-time: makes unplugged.ai reachable over HTTPS on your home network so the iPhone can install it as an app
# (iOS only allows offline-capable web apps over HTTPS).
# Creates a private certificate authority that may ONLY vouch for local names (*.local, localhost, private IP ranges),
# then a certificate for this Mac. The CA key never leaves the certs/ folder.
cd "$(dirname "$0")"
mkdir -p certs && cd certs
HOST="$(scutil --get LocalHostName 2>/dev/null || hostname -s)"
IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)"

if [ ! -f ca.pem ]; then
  openssl genrsa -out ca.key 4096 2>/dev/null
  openssl req -x509 -new -key ca.key -sha256 -days 3650 -subj "/CN=unplugged.ai Local CA" -out ca.pem \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "nameConstraints=critical,permitted;DNS:local,permitted;DNS:localhost,permitted;IP:127.0.0.0/255.0.0.0,permitted;IP:10.0.0.0/255.0.0.0,permitted;IP:172.16.0.0/255.240.0.0,permitted;IP:192.168.0.0/255.255.0.0" || exit 1
  chmod 600 ca.key
fi

SAN="DNS:localhost,DNS:${HOST}.local,IP:127.0.0.1"
[ -n "$IP" ] && SAN="$SAN,IP:$IP"
cat > server.ext <<EXT
subjectAltName=$SAN
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
EXT
openssl genrsa -out server.key 2048 2>/dev/null
openssl req -new -key server.key -subj "/CN=${HOST}.local" -out server.csr
openssl x509 -req -in server.csr -CA ca.pem -CAkey ca.key -CAcreateserial -out server.pem -days 800 -sha256 -extfile server.ext 2>/dev/null || exit 1
chmod 600 server.key
openssl verify -CAfile ca.pem server.pem

echo
echo "Done. Restart the server (.venv/bin/python server.py). It then also serves https://${HOST}.local:8443"
echo
echo "On the iPhone (same Wi-Fi):"
echo " 1. Safari: open http://${IP:-<mac-ip>}:8000/ca.pem  and tap Allow, then Settings > Profile Downloaded > Install."
echo " 2. Settings > General > About > Certificate Trust Settings: switch on 'unplugged.ai Local CA'."
echo " 3. Safari: open https://${HOST}.local:8443 , sign in, tap Share > Add to Home Screen."
