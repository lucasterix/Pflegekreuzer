# Pflegekreuzer - Auto-Deploy Setup

## 🚀 Automatisches Deployment

Dieses Repository verwendet GitHub Actions für automatisches Deployment auf den Hetzner-Server.

### 📋 GitHub Secrets einrichten

Gehe zu deinem GitHub Repository → Settings → Secrets and variables → Actions

Füge diese Secrets hinzu:

#### `SSH_PRIVATE_KEY`
```
-----BEGIN OPENSSH PRIVATE KEY-----
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
-----END OPENSSH PRIVATE KEY-----
```

#### `SERVER_HOST`
```
188.245.172.75
```

### 🔄 Wie es funktioniert

1. **Push auf main Branch** → GitHub Action wird automatisch gestartet
2. **SSH-Verbindung** → Sichere Verbindung zum Hetzner-Server
3. **Backup** → Aktuelle Version wird gesichert
4. **Update** → Code wird gepullt, Dependencies installiert
5. **Test** → App-Import wird getestet
6. **Restart** → App wird neugestartet
7. **Verify** → HTTP-Response wird geprüft

### 📊 Monitoring

- **Logs**: `tail -f /opt/pflegeweb/app.log`
- **Backups**: `/opt/pflegeweb.backups/`
- **Status**: GitHub Actions Tab im Repository

### 🛠️ Manuelles Deployment

Falls nötig, kannst du auch manuell deployen:

```bash
ssh root@188.245.172.75 "cd /opt/pflegeweb && bash deploy.sh"
```

### 🔒 Sicherheit

- SSH-Key ist nur für Deployment gedacht
- Keine Passwörter im Code
- Automatische Backups vor jedem Update
- Rollback bei Fehlern