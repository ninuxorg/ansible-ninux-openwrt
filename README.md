# ansible-ninux-openwrt

Sistema di build automatizzato per firmware **OpenWrt** per i nodi della rete mesh [Ninux](http://ninux.org).


---

## Indice

1. [Struttura del repo](#struttura-del-repo)
2. [Configurazione rapida](#configurazione-rapida)
3. [Installazione Jenkins su Debian Trixie](#installazione-jenkins-su-debian-trixie)
4. [Configurazione Jenkins](#configurazione-jenkins)
5. [Configurazione del build](#configurazione-del-build)
6. [Aggiungere device e organizzazioni](#aggiungere-device-e-organizzazioni)
7. [Uso da riga di comando](#uso-da-riga-di-comando)
8. [Performance e ottimizzazioni](#performance-e-ottimizzazioni)
9. [OpenWISP Firmware Upgrader](#openwisp-firmware-upgrader)
10. [Struttura dei firmware prodotti](#struttura-dei-firmware-prodotti)
11. [Troubleshooting](#troubleshooting)

---

## Struttura del repo

```
ansible-ninux-openwrt/
│
├── config/                              <- CONFIGURAZIONE (modifica qui)
│   ├── build.yml                        <- Tutte le variabili di build
│   ├── base.config                      <- Pacchetti comuni a tutti i target
│   ├── chilli.ext                       <- Estensione Captive Portal
│   ├── zerotier.ext                     <- Estensione ZeroTier VPN
│   ├── wireguard.ext                    <- Estensione WireGuard VPN
│   ├── organizations/
│   │   └── <org>/
│   │       └── <device>.config          <- Config per device
│   └── root_files/
│       └── <org>/                       <- Overlay filesystem per org
│           └── etc/
│               ├── config/
│               └── uci-defaults/
│
├── setup/
│   └── install-jenkins.sh              <- Script autoinstall (Debian Trixie)
│
├── inventory/
│   ├── hosts.yml                        <- Build host (localhost)
│   ├── vault.yml.example               <- Template credenziali cifrate
│   └── group_vars/build_hosts.yml
│
├── playbooks/
│   ├── build_all.yml                    <- Build tutti i device (varianti parallele)
│   ├── build_firmware.yml              <- Build singolo device
│   ├── build_matrix.yml                <- Build matrice personalizzata
│   ├── build_parallel.yml              <- Build parallela tra device
│   ├── cleanup.yml                     <- Pulizia manuale disco
│   └── _build_device_variants.yml      <- Helper interno
│
├── roles/ninux_build_openwrt/
│   ├── defaults/main.yml               <- Default variabili ruolo
│   └── tasks/
│       ├── main.yml
│       ├── deps.yml                    <- apt install dipendenze
│       ├── prepare.yml                 <- Directory, ccache, tmpfs
│       ├── clone_ninux.yml             <- Copia config/ sul build host
│       ├── clone_openwrt.yml           <- Clone/aggiorna OpenWrt
│       ├── rootfiles.yml               <- Overlay filesystem
│       ├── feeds.yml                   <- feeds.conf + update + install
│       ├── dotconfig.yml               <- Assembla .config
│       ├── build.yml                   <- make download + make -jN
│       ├── artifacts.yml               <- Copia firmware output/ e NFS
│       └── openwisp_upload.yml         <- Upload OpenWISP (opzionale)
│
├── Jenkinsfile
├── ansible.cfg
└── .gitignore
```

**Il file principale da modificare e' `config/build.yml`** — contiene tutte le variabili con commenti esplicativi.

---

## Configurazione rapida

```bash
# 1. Clona il repo
git clone https://github.com/ninuxorg/ansible-ninux-openwrt.git
cd ansible-ninux-openwrt

# 2. Modifica la configurazione
nano config/build.yml

# 3. Verifica i device disponibili
ls config/organizations/basilicata/

# 4. Lancia la build
ansible-playbook playbooks/build_all.yml
```

---

## Installazione Jenkins su Debian Trixie

### Requisiti hardware consigliati (LXC Proxmox)

| Risorsa | Minimo | Consigliato |
|---------|--------|-------------|
| CPU     | 4 core | 12 core     |
| RAM     | 8 GB   | 24 GB       |
| Disco   | 80 GB  | 200 GB      |

> **Nota Proxmox LXC**: il container deve avere `nesting=1` abilitato
> per permettere il mount di tmpfs. In `/etc/pve/lxc/<CTID>.conf`:
> ```
> features: nesting=1
> ```
> Dopo: `pct restart <CTID>`

### Installazione automatica (consigliata)

```bash
# Clona il repo
git clone https://github.com/ninuxorg/ansible-ninux-openwrt.git
cd ansible-ninux-openwrt

# Esegui lo script come root
sudo ./setup/install-jenkins.sh

# Con vault password per OpenWISP (opzionale)
sudo ./setup/install-jenkins.sh --vault-pass "mia-password-segreta"

# Solo dipendenze, Jenkins gia' installato
sudo ./setup/install-jenkins.sh --skip-jenkins
```

Lo script installa e configura automaticamente:

- Java 21 (OpenJDK)
- Ansible (via pipx, metodo consigliato su Trixie)
- Jenkins LTS con chiave GPG 2026
- Tutte le dipendenze build OpenWrt
- ccache persistente in `/var/cache/openwrt-ccache`
- tmpfs in `/mnt/openwrt-tmpfs` (8G, montato al boot via fstab)
- Permessi sudo per l'utente `jenkins`

### Installazione manuale passo per passo

#### 1. Java 21

```bash
apt-get update
apt-get install -y fontconfig openjdk-21-jre
java -version
```

#### 2. Ansible

```bash
apt-get install -y pipx
pipx install --include-deps ansible
pipx ensurepath
source ~/.bashrc
ansible --version
```

#### 3. Jenkins LTS

```bash
# Chiave GPG aggiornata (dicembre 2025)
mkdir -p /etc/apt/keyrings
curl -fsSL https://pkg.jenkins.io/debian-stable/jenkins.io-2026.key \
  -o /etc/apt/keyrings/jenkins-keyring.asc

echo "deb [signed-by=/etc/apt/keyrings/jenkins-keyring.asc] \
  https://pkg.jenkins.io/debian-stable binary/" \
  > /etc/apt/sources.list.d/jenkins.list

apt-get update
apt-get install -y jenkins
systemctl enable --now jenkins

# Password iniziale
cat /var/lib/jenkins/secrets/initialAdminPassword
```

#### 4. Dipendenze build OpenWrt

```bash
apt-get install -y \
  build-essential ccache time git subversion g++ bash make \
  libssl-dev patch libncurses-dev zlib1g-dev gawk flex gettext \
  wget unzip xz-utils python3 python3-distutils-extra \
  rsync curl libsnmp-dev liblzma-dev libpam0g-dev cpio
```

#### 5. ccache persistente

```bash
mkdir -p /var/cache/openwrt-ccache
chmod 777 /var/cache/openwrt-ccache
chown jenkins:jenkins /var/cache/openwrt-ccache
```

#### 6. tmpfs

```bash
mkdir -p /mnt/openwrt-tmpfs
echo "tmpfs /mnt/openwrt-tmpfs tmpfs defaults,size=8G,mode=0777 0 0" >> /etc/fstab
mount /mnt/openwrt-tmpfs
df -h /mnt/openwrt-tmpfs
```

#### 7. sudo per jenkins

```bash
cat > /etc/sudoers.d/jenkins-openwrt << 'EOF'
jenkins ALL=(ALL) NOPASSWD: /bin/mount
jenkins ALL=(ALL) NOPASSWD: /bin/umount
jenkins ALL=(ALL) NOPASSWD: /usr/bin/apt-get
jenkins ALL=(ALL) NOPASSWD: /usr/bin/apt
EOF
chmod 440 /etc/sudoers.d/jenkins-openwrt
```

---

## Configurazione Jenkins

### 1. Primo accesso

1. Apri `http://<IP-SERVER>:8080`
2. Inserisci la password iniziale: `cat /var/lib/jenkins/secrets/initialAdminPassword`
3. Scegli **"Install suggested plugins"**
4. Crea l'utente amministratore

### 2. Plugin aggiuntivi richiesti

Vai in **Manage Jenkins → Plugins → Available plugins**:

| Plugin | Note |
|--------|------|
| **Ansible** | Integrazione Ansible |
| **Timestamper** | Timestamp nei log di build |
| **Build Timeout** | Timeout per build lunghe |
| **Workspace Cleanup** | Pulizia workspace post-build |

Pipeline e Git sono gia' inclusi nei plugin suggeriti.

### 3. Configurazione Ansible in Jenkins

**Manage Jenkins → Tools → Ansible installations**:

- Name: `ansible`
- Install automatically: **no**
- Path to ansible executables directory: `/root/.local/bin`

### 4. Creazione del job Pipeline

1. **New Item** → nome `NinuxOpenwrt` → tipo **Pipeline** → OK
2. Tab **General**:
   - Spunta **"Do not allow concurrent builds"**
   - Build Timeout: **240 minuti**
3. Tab **Pipeline**:
   - Definition: **Pipeline script from SCM**
   - SCM: **Git**
   - Repository URL: `https://github.com/mikysal78/ansible-ninux-openwrt.git`
   - Branch Specifier: `*/main`
   - Script Path: `Jenkinsfile`
4. **Save** → **Build with Parameters** per il primo lancio

### 5. Parametri del job

| Parametro | Default | Descrizione |
|-----------|---------|-------------|
| `OPENWRT_ORG` | `basilicata` | Organizzazione Ninux |
| `OPENWRT_VERSION` | `v25.12.4` | Tag OpenWrt |
| `VPN_VARIANTS` | `ALL` | `ALL` / `NO` / `ZeroTier` / `WireGuard` / `DualVPN` |
| `CAPTIVE_PORTAL_VARIANTS` | false | Compila anche varianti con CP |
| `SKIP_DEPS` | false | Salta `apt install` (dopo il primo run) |
| `TMPFS_ENABLED` | true | RAM disk per `tmp/` (+30% velocita') |
| `TMPFS_SIZE` | `8G` | Dimensione tmpfs |
| `CCACHE_DIR` | `/var/cache/openwrt-ccache` | ccache persistente |
| `CCACHE_SIZE` | `20G` | Dimensione massima ccache |
| `OPENWISP_UPLOAD` | false | Upload su OpenWISP |
| `OPENWISP_TRIGGER_UPGRADE` | false | Avvia batch upgrade OpenWISP |
| `OPENWISP_URL` | `` | URL istanza OpenWISP |

### 6. Vault password per OpenWISP

```bash
# Sul server Jenkins
echo "mia-password-vault" > /var/lib/jenkins/.vault_pass
chmod 600 /var/lib/jenkins/.vault_pass
chown jenkins:jenkins /var/lib/jenkins/.vault_pass

# Crea il vault con credenziali
cp inventory/vault.yml.example inventory/vault.yml
nano inventory/vault.yml
ansible-vault encrypt inventory/vault.yml \
  --vault-password-file /var/lib/jenkins/.vault_pass
```

---

## Configurazione del build

**Modifica `config/build.yml`** per personalizzare la build.

Sezioni principali:

```yaml
# --- Versione e org ---
openwrt_version: "v25.12.4"
openwrt_org: "basilicata"

# --- Varianti da compilare ---
openwrt_vpn_variants: [NO, ZeroTier, WireGuard, DualVPN]
openwrt_cp_variants: false

# --- Dove salvare i firmware ---
openwrt_nfs_dir: "/mnt/nfs-firmware"

# --- Performance ---
openwrt_ccache_dir: "/var/cache/openwrt-ccache"
openwrt_ccache_maxsize: "20G"
openwrt_tmpfs_enabled: true
openwrt_tmpfs_size: "8G"

# --- OpenWISP (disabilitato di default) ---
openwisp_upload_enabled: false
openwisp_url: ""
openwisp_org_id: ""
```

Le variabili in `config/build.yml` sovrascrivono i default del ruolo.
Override ulteriore a runtime: `-e variabile=valore`.

---

## Aggiungere device e organizzazioni

### Nuovo device

```bash
# 1. Genera il .config con OpenWrt menuconfig
cd /path/to/openwrt-src
make menuconfig   # seleziona target e salva
cp .config /repo/config/organizations/basilicata/nome_device.config

# 2. Verifica che il file sia stato aggiunto
ls config/organizations/basilicata/

# 3. Commita
git add config/organizations/basilicata/nome_device.config
git commit -m "feat: aggiungi device nome_device"
```

Il nome del file senza `.config` e' il valore di `openwrt_target`.
L'autodiscovery lo includera' automaticamente nella prossima build.

### Nuova organizzazione

```bash
mkdir -p config/organizations/roma
mkdir -p config/root_files/roma/etc/{config,uci-defaults}

# Parti dai config esistenti
cp config/organizations/basilicata/*.config config/organizations/roma/

# Personalizza root_files
cp -r config/root_files/basilicata/. config/root_files/roma/

# Build per la nuova org
ansible-playbook playbooks/build_all.yml -e openwrt_org=roma
```

---

## Uso da riga di comando

```bash
# Tutti i device, tutte le varianti VPN
ansible-playbook playbooks/build_all.yml

# Con Captive Portal (2x build per device)
ansible-playbook playbooks/build_all.yml -e openwrt_cp_variants=true

# Solo alcune varianti VPN
ansible-playbook playbooks/build_all.yml \
  -e '{"openwrt_vpn_variants": ["NO", "ZeroTier"]}'

# Singolo device, tutte le varianti
ansible-playbook playbooks/build_firmware.yml \
  -e openwrt_target=glinet_gl-mt300n-v2

# Singola variante specifica
ansible-playbook playbooks/build_firmware.yml \
  -e openwrt_target=glinet_gl-mt300n-v2 \
  -e '{"openwrt_vpn_variants": ["ZeroTier"]}' \
  -e openwrt_captive_portal=true

# Solo installazione dipendenze
ansible-playbook playbooks/build_all.yml --tags deps

# Solo build (dipendenze gia' installate)
ansible-playbook playbooks/build_all.yml --skip-tags deps

# Pulizia disco
ansible-playbook playbooks/cleanup.yml                        # solo temporanei
ansible-playbook playbooks/cleanup.yml -e cleanup_full=true  # tutto
ansible-playbook playbooks/cleanup.yml -e cleanup_output=true # solo output/
```

---

## Performance e ottimizzazioni

### Strategia di build

```
Device 1
  ├── VPN=NO        ─┐
  ├── VPN=ZeroTier   ├─ parallelo (async, condividono toolchain)
  ├── VPN=WireGuard  │
  └── VPN=DualVPN   ─┘
  → pulizia staging_dir/build_dir
Device 2
  └── (idem)
...
Post: pulizia totale + smonta tmpfs + stats ccache
```

Le varianti dello stesso device condividono la toolchain gia' compilata
e ricompilano solo i pacchetti che differiscono (pochi MB),
quindi il parallelo e' efficiente senza moltiplicare RAM/disco.

### Impatto stimato su 12 CPU / 24 GB RAM

| Ottimizzazione | Guadagno |
|----------------|----------|
| `make -j14` (nproc+2) | baseline |
| ccache (dalla 2a build) | **-70%** tempo |
| ccache SLOPPINESS | hit rate piu' alto |
| tmpfs per `tmp/` | **-30%** I/O |
| 4 varianti in parallelo | **-60%** per device |

### Proxmox LXC e tmpfs

```bash
# Host Proxmox
echo "features: nesting=1" >> /etc/pve/lxc/<CTID>.conf
pct restart <CTID>
```

---

## OpenWISP Firmware Upgrader

### Configurazione

In `config/build.yml`:

```yaml
openwisp_upload_enabled: true
openwisp_url: "https://openwisp.ninux.org"
openwisp_org_slug: "basilicata"
openwisp_org_id: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
openwisp_trigger_upgrade: false   # true = avvia upgrade automatico
```

Credenziali in `inventory/vault.yml`:

```bash
cp inventory/vault.yml.example inventory/vault.yml
# Modifica: openwisp_username e openwisp_password
ansible-vault encrypt inventory/vault.yml \
  --vault-password-file /var/lib/jenkins/.vault_pass
```

### Flusso

```
Build → artifacts.yml → openwisp_upload.yml
  1. Login → token Bearer
  2. Cerca/crea Category (org + device)
  3. Crea Build (versione-target-VPN-CP)
  4. Carica sysupgrade + factory
  5. (opzionale) Batch upgrade
```

---

## Struttura dei firmware prodotti

```
output/                              <- file finali per Jenkins artifacts
└── v25.12.4/
    └── basilicata/
        ├── Standard/
        │   ├── VPN-NO/glinet_gl-mt300n-v2/
        │   ├── VPN-ZeroTier/glinet_gl-mt300n-v2/
        │   ├── VPN-WireGuard/glinet_gl-mt300n-v2/
        │   └── VPN-DualVPN/glinet_gl-mt300n-v2/
        └── CaptivePortal/
            └── VPN-*/...

/mnt/nfs-firmware/                   <- bin/targets/ completo
└── v25.12.4/basilicata/Standard/VPN-ZeroTier/glinet_gl-mt300n-v2/
    ├── openwrt-*-sysupgrade.bin
    ├── openwrt-*-factory.bin
    ├── sha256sums
    └── ...
```

---

## Troubleshooting

### `openwrt_work_dir is undefined`

Assicurati di usare i playbook da `playbooks/` — caricano `config/build.yml`
tramite `vars_files`. Non richiamare il ruolo direttamente senza caricare le variabili.

### `chown failed: Operation not permitted` su NFS

I task non usano `owner` sulle directory NFS. Se persiste, verifica che
il server NFS esporti con `no_root_squash` o adatta i permessi lato server.

### `libncurses5 not available`

Pacchetto rimosso da Debian 13+. Usa `libncurses-dev` (gia' nel repo).
Aggiorna `openwrt_build_deps` in `config/build.yml` se hai un'installazione vecchia.

### Jenkins: `git tool does not exist`

**Manage Jenkins → Tools → Git installations**:
- Name: `Default`
- Path: `git`

### Jenkins: timeout su build lunghe

In **Manage Jenkins → Configure System** imposta Build Timeout a 240+ minuti.

### ccache hit rate basso

```bash
CCACHE_DIR=/var/cache/openwrt-ccache ccache --show-stats
```

Hit rate sotto 50% dopo la seconda build: controlla che `CCACHE_DIR`
sia lo stesso tra i job e che `nesting=1` sia attivo (per tmpfs).

### tmpfs: `mount: permission denied` in LXC

Abilita `nesting=1` nella config Proxmox del container (vedi sezione Performance).

### Log di build per variante fallita

```bash
# In locale
find build/ -name "log-*.log" | xargs ls -lt | head -10

# In Jenkins
find /var/lib/jenkins/workspace/NinuxOpenwrt/build -name "log-*.log" \
  | xargs ls -lt | head -5
```

---

## Licenza

GPL-3.0
