#!/bin/bash

# Pflegekreuzer Auto-Deploy Script
# Wird von GitHub Actions aufgerufen

set -e  # Exit on any error

echo "🚀 Starting Pflegekreuzer deployment..."

# Wechsle zum Projekt-Verzeichnis
cd /opt/pflegeweb

# Backup der aktuellen Version (falls Rollback nötig)
BACKUP_DIR="/opt/pflegeweb.backups/$(date +%Y%m%d_%H%M%S)"
echo "💾 Creating backup in $BACKUP_DIR..."
mkdir -p "$BACKUP_DIR"
cp -r . "$BACKUP_DIR/" 2>/dev/null || true

# Pull latest changes
echo "📥 Pulling latest changes from GitHub..."
git pull origin main

# Install dependencies
echo "📦 Installing Python dependencies..."
source venv/bin/activate
pip install -r requirements.txt

# Test import before restarting
echo "🧪 Testing application import..."
if ! python3 -c "import app.main; print('✅ Import successful')"; then
    echo "❌ Import failed! Rolling back..."
    cp -r "$BACKUP_DIR"/* . 2>/dev/null || true
    exit 1
fi

# Restart application
echo "🔄 Restarting FastAPI application..."
pkill -f uvicorn || true
sleep 3

# Start new instance
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > /opt/pflegeweb/app.log 2>&1 &

# Wait for startup
echo "⏳ Waiting for application to start..."
for i in {1..30}; do
    if curl -s -f http://localhost:8000 > /dev/null 2>&1; then
        echo "✅ Deployment successful! App is responding."
        exit 0
    fi
    sleep 2
done

echo "❌ Deployment failed! App not responding after 60 seconds."
echo "📋 Check logs with: tail -f /opt/pflegeweb/app.log"
exit 1