#!/bin/bash

cd /home/travismagaluk/garagewatch

echo "🔄 Pulling latest code from GitHub..."
git pull origin main

echo "🔁 Restarting garage_logger systemd service..."
sudo systemctl restart garage_logger

echo "✅ Deploy complete!"
