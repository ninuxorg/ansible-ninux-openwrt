#!/bin/bash
# =============================================================================
# install-jenkins.sh
# Installazione automatica di Jenkins + dipendenze per Ninux OpenWrt Build
# Testato su: Debian 13 (Trixie) - LXC Proxmox
#
# Usage:
#   chmod +x setup/install-jenkins.sh
#   sudo ./setup/install-jenkins.sh [opzioni]
#
# Opzioni:
#   --vault-pass <pass>   Salva la vault password per ansible-vault
#   --skip-jenkins        Salta installazione Jenkins (solo dipendenze)
#   --skip-deps           Salta dipendenze build OpenWrt
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'; BOLD='\033[1m'

log()  { echo -e "${GREEN}[+]${NC} $*"; }
info() { echo -e "${BLUE}[i]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; exit 1; }
ok()   { echo -e "${GREEN}[v]${NC} $*"; }

VAULT_PASS=""
SKIP_JENKINS=false
SKIP_DEPS=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --vault-pass)   VAULT_PASS="$2"; shift 2 ;;
    --skip-jenkins) SKIP_JENKINS=true; shift ;;
    --skip-deps)    SKIP_DEPS=true; shift ;;
    *) err "Argomento sconosciuto: $1" ;;
  esac
done

[[ $EUID -eq 0 ]] || err "Eseguire come root: sudo $0"

if [[ -f /etc/os-release ]]; then
  . /etc/os-release
  info "OS: $PRETTY_NAME"
fi

echo ""
echo -e "${BOLD}============================================${NC}"
echo -e "${BOLD}  Ninux OpenWrt Build - Setup automatico   ${NC}"
echo -e "${BOLD}============================================${NC}"
echo ""

# --------------------------------------------------------------------------
# 1. Sistema
# --------------------------------------------------------------------------
log "Aggiornamento sistema..."
apt-get update -qq && apt-get upgrade -y -qq
ok "Sistema aggiornato"

# --------------------------------------------------------------------------
# 2. Dipendenze base
# --------------------------------------------------------------------------
log "Dipendenze base..."
apt-get install -y -qq \
  curl wget git rsync gnupg2 ca-certificates \
  apt-transport-https lsb-release software-properties-common \
  sudo python3 python3-pip pipx
ok "Dipendenze base OK"

# --------------------------------------------------------------------------
# 3. Java 21
# --------------------------------------------------------------------------
log "Java 21..."
apt-get install -y -qq fontconfig openjdk-21-jre
ok "Java: $(java -version 2>&1 | head -1)"

# --------------------------------------------------------------------------
# 4. Ansible (via pipx - metodo consigliato su Trixie)
# --------------------------------------------------------------------------
log "Ansible..."
if ! command -v ansible &>/dev/null; then
  pipx install --include-deps ansible
  pipx ensurepath
  export PATH="$PATH:/root/.local/bin"
  echo 'export PATH="$PATH:/root/.local/bin"' >> /root/.bashrc
  cat > /etc/profile.d/pipx.sh << 'EOF'
export PATH="$PATH:/root/.local/bin"
EOF
fi
ok "Ansible: $(ansible --version | head -1)"

# --------------------------------------------------------------------------
# 5. Dipendenze build OpenWrt
# --------------------------------------------------------------------------
if [[ "$SKIP_DEPS" == "false" ]]; then
  log "Dipendenze build OpenWrt..."
  apt-get install -y -qq \
    build-essential ccache time subversion g++ bash make \
    libssl-dev patch libncurses-dev zlib1g-dev gawk flex gettext \
    wget unzip xz-utils python3-distutils-extra \
    libsnmp-dev liblzma-dev libpam0g-dev cpio
  ok "Dipendenze OpenWrt OK"
fi

# --------------------------------------------------------------------------
# 6. Jenkins LTS
# --------------------------------------------------------------------------
if [[ "$SKIP_JENKINS" == "false" ]]; then
  log "Jenkins LTS (chiave 2026)..."
  mkdir -p /etc/apt/keyrings
  curl -fsSL https://pkg.jenkins.io/debian-stable/jenkins.io-2026.key \
    -o /etc/apt/keyrings/jenkins-keyring.asc
  echo "deb [signed-by=/etc/apt/keyrings/jenkins-keyring.asc] \
https://pkg.jenkins.io/debian-stable binary/" \
    > /etc/apt/sources.list.d/jenkins.list
  apt-get update -qq
  apt-get install -y -qq jenkins
  systemctl enable jenkins
  systemctl start jenkins

  log "Attesa avvio Jenkins..."
  for _ in $(seq 1 12); do
    systemctl is-active --quiet jenkins && break
    sleep 5
  done
  systemctl is-active --quiet jenkins || err "Jenkins non avviato"
  ok "Jenkins avviato"
fi

# --------------------------------------------------------------------------
# 7. ccache directory persistente
# --------------------------------------------------------------------------
log "ccache directory persistente..."
mkdir -p /var/cache/openwrt-ccache
chmod 777 /var/cache/openwrt-ccache
id jenkins &>/dev/null && chown jenkins:jenkins /var/cache/openwrt-ccache
ok "ccache: /var/cache/openwrt-ccache"

# --------------------------------------------------------------------------
# 8. tmpfs
# --------------------------------------------------------------------------
log "tmpfs per build OpenWrt..."
mkdir -p /mnt/openwrt-tmpfs
chmod 777 /mnt/openwrt-tmpfs
if ! grep -q "openwrt-tmpfs" /etc/fstab; then
  echo "tmpfs /mnt/openwrt-tmpfs tmpfs defaults,size=8G,mode=0777 0 0" >> /etc/fstab
fi
mountpoint -q /mnt/openwrt-tmpfs || mount /mnt/openwrt-tmpfs
ok "tmpfs: /mnt/openwrt-tmpfs (8G)"

# --------------------------------------------------------------------------
# 9. sudo per jenkins
# --------------------------------------------------------------------------
if id jenkins &>/dev/null; then
  log "sudo per utente jenkins..."
  cat > /etc/sudoers.d/jenkins-openwrt << 'SUDO'
# Ninux OpenWrt build - permessi jenkins
jenkins ALL=(ALL) NOPASSWD: /bin/mount
jenkins ALL=(ALL) NOPASSWD: /bin/umount
jenkins ALL=(ALL) NOPASSWD: /usr/bin/apt-get
jenkins ALL=(ALL) NOPASSWD: /usr/bin/apt
SUDO
  chmod 440 /etc/sudoers.d/jenkins-openwrt
  ok "sudo configurato per jenkins"
fi

# --------------------------------------------------------------------------
# 10. Vault password
# --------------------------------------------------------------------------
if [[ -n "$VAULT_PASS" ]] && id jenkins &>/dev/null; then
  log "Vault password..."
  echo "$VAULT_PASS" > /var/lib/jenkins/.vault_pass
  chmod 600 /var/lib/jenkins/.vault_pass
  chown jenkins:jenkins /var/lib/jenkins/.vault_pass
  ok "Vault password: /var/lib/jenkins/.vault_pass"
fi

# --------------------------------------------------------------------------
# 11. NFS mount point firmware
# --------------------------------------------------------------------------
mkdir -p /mnt/nfs-firmware
chmod 777 /mnt/nfs-firmware
info "Directory NFS: /mnt/nfs-firmware"
info "Aggiorna /etc/fstab se il server NFS e' diverso:"
info "  nfs-server:/export/firmware /mnt/nfs-firmware nfs defaults 0 0"

# --------------------------------------------------------------------------
# Riepilogo
# --------------------------------------------------------------------------
echo ""
echo -e "${BOLD}============================================${NC}"
echo -e "${BOLD}  Setup completato!${NC}"
echo -e "${BOLD}============================================${NC}"
echo ""
ok "Java     : $(java -version 2>&1 | head -1)"
ok "Ansible  : $(ansible --version 2>/dev/null | head -1)"
ok "ccache   : $(ccache --version | head -1)"
ok "tmpfs    : $(df -h /mnt/openwrt-tmpfs | tail -1 | awk '{print $2" totale, "$4" liberi"}')"

if [[ "$SKIP_JENKINS" == "false" ]]; then
  INIT_PASS=""
  [[ -f /var/lib/jenkins/secrets/initialAdminPassword ]] && \
    INIT_PASS=$(cat /var/lib/jenkins/secrets/initialAdminPassword)
  ok "Jenkins  : http://$(hostname -I | awk '{print $1}'):8080"
  [[ -n "$INIT_PASS" ]] && \
    echo -e "  ${BOLD}Password iniziale: ${INIT_PASS}${NC}"
fi

echo ""
echo -e "  Prossimo passo: ${BOLD}cat README.md${NC}"
echo ""
