#!/bin/sh
# One-time setup so the phone's browser allows the microphone.
# Phone browsers only give microphone access to secure (https) pages, so this
# makes a certificate for this Mac that your own devices can trust.
#
# It will ask for your Mac password once (to trust the certificate on this Mac).
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
command -v mkcert >/dev/null || brew install mkcert
mkcert -install
NAME="$(scutil --get LocalHostName).local"
IP=$(ipconfig getifaddr en0 2>/dev/null || true)
mkdir -p "$ROOT/certs"
mkcert -cert-file "$ROOT/certs/cert.pem" -key-file "$ROOT/certs/key.pem" "$NAME" localhost 127.0.0.1 $IP
CA="$(mkcert -CAROOT)/rootCA.pem"
cat <<TXT

Done on the Mac. Now, once, on the phone:

  1. Send this file to the phone (AirDrop is easiest):
       $CA
  2. iPhone: open it, then Settings > General > VPN & Device Management > install the profile.
     Then Settings > General > About > Certificate Trust Settings > switch it on.
     Android: Settings > Security > Encryption & credentials > Install a certificate > CA certificate.
  3. Restart Quote Vault on the Mac, then on the phone open:
       https://$NAME:8766

Keep rootCA-key.pem (in the same folder as rootCA.pem) private; never send it anywhere.
TXT
