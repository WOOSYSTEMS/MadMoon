#!/bin/bash
# MadMoon Disaster Recovery — Physical Backup Script
# Run: bash ~/MadMoon/DISASTER_RECOVERY/backup.sh /Volumes/USB_DRIVE_NAME
#
# Creates a complete backup of everything needed to restore on a new Mac.
# INCLUDES sensitive keys — store the USB securely.

set -e

DEST="${1:-/tmp/madmoon-backup}"
DATE=$(date +%Y-%m-%d)
BACKUP_DIR="$DEST/MadMoon-Backup-$DATE"

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  MadMoon Disaster Recovery — Physical Backup ║"
echo "║  Date: $DATE                          ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

mkdir -p "$BACKUP_DIR/keys"
mkdir -p "$BACKUP_DIR/configs"
mkdir -p "$BACKUP_DIR/claude-memory"
mkdir -p "$BACKUP_DIR/databases"
mkdir -p "$BACKUP_DIR/crypto"

# 1. SSH Keys
echo "[1/10] Backing up SSH keys..."
cp -r ~/.ssh/config "$BACKUP_DIR/keys/ssh-config" 2>/dev/null || true
cp ~/.ssh/polymarket-bot-dublin.pem "$BACKUP_DIR/keys/" 2>/dev/null || true
cp ~/.ssh/pocketbase_key "$BACKUP_DIR/keys/" 2>/dev/null || true
cp ~/.ssh/pocketbase_key.pub "$BACKUP_DIR/keys/" 2>/dev/null || true
cp ~/.ssh/known_hosts "$BACKUP_DIR/keys/" 2>/dev/null || true

# 2. AWS Credentials
echo "[2/10] Backing up AWS credentials..."
cp ~/.aws/config "$BACKUP_DIR/keys/aws-config" 2>/dev/null || true
cp ~/.aws/credentials "$BACKUP_DIR/keys/aws-credentials" 2>/dev/null || true

# 3. Shell configs
echo "[3/10] Backing up shell configs..."
cp ~/.zshrc "$BACKUP_DIR/configs/zshrc" 2>/dev/null || true
cp ~/.zprofile "$BACKUP_DIR/configs/zprofile" 2>/dev/null || true
cp ~/.zshenv "$BACKUP_DIR/configs/zshenv" 2>/dev/null || true
cp ~/.profile "$BACKUP_DIR/configs/profile" 2>/dev/null || true
cp ~/.gitconfig "$BACKUP_DIR/configs/gitconfig" 2>/dev/null || true

# 4. Claude — ALL data (memory, transcripts, history, settings)
echo "[4/14] Backing up entire Claude directory (memory + all transcripts)..."
mkdir -p "$BACKUP_DIR/claude-full"
rsync -a --exclude='debug' ~/.claude/ "$BACKUP_DIR/claude-full/" 2>/dev/null || true

# 5. UmmaID crypto keys & databases
echo "[5/10] Backing up UmmaID crypto & databases..."
UMMA="$HOME/MadMoon/UmmaGlobal/Website/ummaglobal"
if [ -d "$UMMA/crypto" ]; then
  cp "$UMMA/crypto/master.key" "$BACKUP_DIR/crypto/" 2>/dev/null || true
  cp "$UMMA/crypto/admin.hash" "$BACKUP_DIR/crypto/" 2>/dev/null || true
  cp -r "$UMMA/crypto/shards" "$BACKUP_DIR/crypto/shards" 2>/dev/null || true
  cp -r "$UMMA/crypto/shards_backup" "$BACKUP_DIR/crypto/shards_backup" 2>/dev/null || true
  cp -r "$UMMA/crypto/shards_offline" "$BACKUP_DIR/crypto/shards_offline" 2>/dev/null || true
  cp -r "$UMMA/crypto/pq-keys" "$BACKUP_DIR/crypto/pq-keys" 2>/dev/null || true
fi
if [ -d "$UMMA/data" ]; then
  cp "$UMMA/data/umma.db" "$BACKUP_DIR/databases/" 2>/dev/null || true
  cp "$UMMA/data/device_shards.db" "$BACKUP_DIR/databases/" 2>/dev/null || true
fi

# 6. Meta hunter config (session cookies)
echo "[6/10] Backing up meta-hunter config..."
cp ~/MadMoon/tools/meta-hunter/config.json "$BACKUP_DIR/configs/meta-hunter-config.json" 2>/dev/null || true

# 7. Thunder client keys
echo "[7/10] Backing up Thunder keys..."
cp -r ~/.thunder/keys "$BACKUP_DIR/keys/thunder-keys" 2>/dev/null || true

# 8. MadMoon codebase (full copy)
echo "[8/10] Backing up MadMoon codebase (this may take a moment)..."
rsync -a --exclude='node_modules' --exclude='.git' ~/MadMoon/ "$BACKUP_DIR/MadMoon/" 2>/dev/null || true

# 9. UmmaGlobal standalone (if separate from MadMoon)
echo "[9/10] Backing up ummaglobal standalone..."
if [ -d "$HOME/ummaglobal" ] && [ ! -L "$HOME/ummaglobal" ]; then
  rsync -a --exclude='node_modules' --exclude='.git' ~/ummaglobal/ "$BACKUP_DIR/ummaglobal/" 2>/dev/null || true
fi

# 10. Personal documents (novel, research, writing, resume)
echo "[10/12] Backing up personal documents..."
mkdir -p "$BACKUP_DIR/documents"
rsync -a --exclude='node_modules' --exclude='.git' ~/Documents/ "$BACKUP_DIR/documents/" 2>/dev/null || true

# 11. Desktop projects and important files
echo "[11/12] Backing up Desktop projects..."
mkdir -p "$BACKUP_DIR/desktop"
rsync -a --exclude='node_modules' --exclude='.git' ~/Desktop/_Projects/ "$BACKUP_DIR/desktop/_Projects/" 2>/dev/null || true
cp ~/Desktop/*.md "$BACKUP_DIR/desktop/" 2>/dev/null || true
cp ~/Desktop/*.docx "$BACKUP_DIR/desktop/" 2>/dev/null || true

# 12. Polymarket / Trading archive (historical — no longer active)
echo "[12/14] Backing up Polymarket & trading archive..."
mkdir -p "$BACKUP_DIR/trading-archive"
for dir in kossinna Heil 11111 polymarket-bot "polymarket-bot 2" "polymarket-bot copy" polymarket-btc-bot Poly222 Bot28 algorithm-129 algorithm-elite-m4626 eth-trader; do
  if [ -d "$HOME/$dir" ]; then
    echo "  → $dir"
    rsync -a --exclude='node_modules' --exclude='.git' --exclude='venv' --exclude='__pycache__' "$HOME/$dir/" "$BACKUP_DIR/trading-archive/$dir/" 2>/dev/null || true
  fi
done
# Documents trading folders
rsync -a --exclude='node_modules' --exclude='venv' "$HOME/Documents/Polybot111/" "$BACKUP_DIR/trading-archive/Polybot111/" 2>/dev/null || true
rsync -a "$HOME/Documents/Kossinna Inc/" "$BACKUP_DIR/trading-archive/Kossinna-Inc/" 2>/dev/null || true
# Downloads trading folders
rsync -a --exclude='node_modules' --exclude='venv' "$HOME/Downloads/polymarket-bot4A/" "$BACKUP_DIR/trading-archive/polymarket-bot4A/" 2>/dev/null || true
rsync -a --exclude='venv' "$HOME/Downloads/polymarket_btc_papertrade_app/" "$BACKUP_DIR/trading-archive/polymarket_btc_papertrade_app/" 2>/dev/null || true

# 13. Other projects on Desktop and home directory
echo "[13/14] Backing up other projects..."
mkdir -p "$BACKUP_DIR/other-projects"
for dir in workout-app dev; do
  if [ -d "$HOME/$dir" ]; then
    echo "  → $dir"
    rsync -a --exclude='node_modules' --exclude='.git' --exclude='venv' --exclude='__pycache__' "$HOME/$dir/" "$BACKUP_DIR/other-projects/$dir/" 2>/dev/null || true
  fi
done

# 14. Academic & immigration documents
echo "[14/16] Backing up academic & immigration documents..."
mkdir -p "$BACKUP_DIR/official-documents"
cp "$HOME/Downloads/Transcript.pdf" "$BACKUP_DIR/official-documents/" 2>/dev/null || true
cp "$HOME/Downloads/Unofficial Transcript-2.pdf" "$BACKUP_DIR/official-documents/" 2>/dev/null || true
cp "$HOME/Downloads/Unofficial Transcript-3.pdf" "$BACKUP_DIR/official-documents/" 2>/dev/null || true
cp "$HOME/Downloads/T00714015 202620 GRAD.pdf" "$BACKUP_DIR/official-documents/TRU_Graduation_Confirmation.pdf" 2>/dev/null || true
cp "$HOME/Documents/Personal/NuwanAmbagahawatteResume.pdf" "$BACKUP_DIR/official-documents/" 2>/dev/null || true
cp "$HOME/Documents/Projects/Co/11111/Nuwan Ambagahawatte Resume.pdf" "$BACKUP_DIR/official-documents/Resume_v2.pdf" 2>/dev/null || true
cp "$HOME/Documents/Projects/Co/11111/Cover letter Nuwan.pdf" "$BACKUP_DIR/official-documents/" 2>/dev/null || true
# Cover letters
find "$HOME/Downloads" -maxdepth 1 -name "*CoverLetter*" -o -name "*coverletter*" 2>/dev/null | while read f; do cp "$f" "$BACKUP_DIR/official-documents/" 2>/dev/null; done
# Immigration form
cp "$HOME/Documents/Projects/Owly/imm5257e.pdf" "$BACKUP_DIR/official-documents/imm5257e_visa_form.pdf" 2>/dev/null || true
# Academic coursework
rsync -a "$HOME/Documents/Academic/" "$BACKUP_DIR/official-documents/Academic/" 2>/dev/null || true

# 15. Published research
echo "[15/16] Backing up published research..."
mkdir -p "$BACKUP_DIR/published-research"
cp "$HOME/Documents/Sialic_Acid_Neonatal_Immunology_Research.pdf" "$BACKUP_DIR/published-research/" 2>/dev/null || true
cp "$HOME/Documents/Sialic_Acid_Neonatal_Immunology_Research.md" "$BACKUP_DIR/published-research/" 2>/dev/null || true
cp "$HOME/Documents/Personal/NanoTechnologyFinalProject.docx" "$BACKUP_DIR/published-research/" 2>/dev/null || true
rsync -a --exclude='node_modules' "$HOME/TRUMicroplasticsResearch/" "$BACKUP_DIR/published-research/TRUMicroplasticsResearch/" 2>/dev/null || true

# 16. Recovery instructions
echo "[16/16] Copying recovery instructions..."
cp ~/MadMoon/DISASTER_RECOVERY/RESTORE.md "$BACKUP_DIR/RESTORE.md"
cp ~/MadMoon/DISASTER_RECOVERY/backup.sh "$BACKUP_DIR/backup.sh"

# Package list for reference
echo "[+] Saving installed packages list..."
brew list --formula > "$BACKUP_DIR/configs/brew-packages.txt" 2>/dev/null || true
npm list -g --depth=0 > "$BACKUP_DIR/configs/npm-global-packages.txt" 2>/dev/null || true

# Summary
echo ""
echo "═══════════════════════════════════════════════"
echo "BACKUP COMPLETE"
echo "═══════════════════════════════════════════════"
echo ""
echo "Location: $BACKUP_DIR"
echo "Size: $(du -sh "$BACKUP_DIR" | cut -f1)"
echo ""
echo "Contents:"
find "$BACKUP_DIR" -maxdepth 2 -type d | sort | while read d; do
  count=$(find "$d" -maxdepth 1 -type f | wc -l | tr -d ' ')
  rel=${d#$BACKUP_DIR/}
  [ "$count" -gt 0 ] && printf "  %-50s %s files\n" "$rel" "$count"
done
echo ""
echo "⚠️  THIS BACKUP CONTAINS SENSITIVE KEYS AND CREDENTIALS"
echo "⚠️  Store the USB drive securely. Do not leave it unattended."
echo "⚠️  To restore: plug in USB, run 'claude' and say:"
echo "    'Read /Volumes/USB/MadMoon-Backup-$DATE/RESTORE.md and follow it step by step'"
echo ""
