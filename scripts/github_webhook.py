#!/usr/bin/env python3

import os
import hmac
import hashlib
from flask import Flask, request, abort
from subprocess import run
from datetime import datetime

app = Flask(__name__)

# === Load secret from environment or fallback ===
GITHUB_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "changeme")

LOG_FILE = "/home/travismagaluk/garagewatch/webhook.log"

@app.route("/github-webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Hub-Signature-256", "")
    raw_body = request.data

    expected = "sha256=" + hmac.new(
        GITHUB_SECRET.encode(), raw_body, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        write_log("❌ INVALID signature — rejected")
        abort(403)

    write_log("✅ Valid webhook received. Deploying...")
    result = run(["/home/travismagaluk/garagewatch/deploy.sh"])
    write_log(f"📦 Deploy exited with code {result.returncode}")
    return "OK", 200

def write_log(message):
    now = datetime.now().isoformat()
    with open(LOG_FILE, "a") as f:
        f.write(f"{now} - {message}\n")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)