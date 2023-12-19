#!/bin/sh

set -e

# Step 1: Define the location of Mitmproxy's CA certificate
MITMPROXY_CA="/root/.mitmproxy/mitmproxy-ca-cert.pem"

# Step 2: Check if the certificate exists
if [ ! -f "$MITMPROXY_CA" ]; then
    echo "Mitmproxy CA certificate not found at $MITMPROXY_CA"
    exit 1
fi

# Step 3: Convert PEM to CRT and copy to CA certificates directory (if required)
CRT_DEST="/usr/local/share/ca-certificates/mitmproxy-ca-cert.crt"
openssl x509 -in "$MITMPROXY_CA" -inform PEM -out "$CRT_DEST"

# Check if the CA store update was successful
if [ $? -eq 0 ]; then
    echo "Mitmproxy CA certificate installed successfully."
else
    echo "Failed to install Mitmproxy CA certificate."
fi