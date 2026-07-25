# ansible-ninux-openwrt

Sistema di build automatizzato per firmware **OpenWrt** per i nodi della rete mesh [Ninux](http://ninux.org).

---

## Indice

1. [Struttura del repo](#struttura-del-repo)
2. [Configurazione rapida](#configurazione-rapida)
3. [Installazione Jenkins su Debian Trixie](#installazione-jenkins-su-debian-trixie)
4. [Configurazione Jenkins](#configurazione-jenkins)
5. [Configurazione del build](#configurazione-del-build)
6. [Gestione segreti con ansible-vault](#gestione-segreti-con-ansible-vault)
7. [Aggiungere device e organizzazioni](#aggiungere-device-e-organizzazioni)
8. [Uso da riga di comando](#uso-da-riga-di-comando)
9. [Performance e ottimizzazioni](#performance-e-ottimizzazioni)
10. [OpenWISP Firmware Upgrader](#openwisp-firmware-upgrader)
11. [GitHub Release](#github-release)
12. [Struttura dei firmware prodotti](#struttura-dei-firmware-prodotti)
13. [Test e CI](#test-e-ci)
14. [Troubleshooting](#troubleshooting)

---

## Struttura del repo

```
ansible-ninux-openwrt/
│
├── ninux.yml                            <- CONFIGURAZIONE PRINCIPALE (modifica qui)
├── ninux.yml.example                    <- Template per nuove installazioni
│
├── config/
│   ├── base.config                      <- Pacchetti comuni a tutti i target
│   ├── uspot.ext                        <- Estensione Captive Portal (uspot) — build separata
│   ├── zerotier.ext                     <- Estensione ZeroTier VPN
│   ├── wireguard.ext                    <- Estensione WireGuard VPN (include VXLAN)
│   └── organizations/
│       └── <org>/
│           └── <device>.config          <- Config per device
│
├── setup/
│   └── install-jenkins.sh               <- Script autoinstall (Debian Trixie)
│
├── inventory/
│   ├── hosts.yml                        <- Build host (localhost)
│   └── group_vars/build_hosts.yml
│
├── playbooks/
│   ├── build_all.yml                    <- Build tutti i device (varianti parallele)
│   ├── build_firmware.yml               <- Build singolo device
│   ├── build_matrix.yml                 <- Build matrice personalizzata
│   ├── build_parallel.yml               <- Build parallela tra device
│   ├── cleanup.yml                      <- Pulizia manuale disco
│   └── _build_device_variants.yml       <- Helper interno
│
├── roles/ninux_build_openwrt/
│   ├── defaults/main.yml                <- Default variabili ruolo
│   └── tasks/
│       ├── main.yml
│       ├── deps.yml                     <- apt install dipendenze
│       ├── prepare.yml                  <- Directory, ccache, tmpfs
│       ├── clone_ninux.yml              <- Copia config/ sul build host
│       ├── clone_openwrt.yml            <- Clone/aggiorna OpenWrt
│       ├── rootfiles.yml                <- Overlay filesystem + openwisp-config
│       ├── feeds.yml                    <- feeds.conf + update + install
│       ├── dotconfig.yml                <- Assembla .config
│       ├── build.yml                    <- make download + make -jN
│       ├── artifacts.yml                <- Copia firmware output/ e NFS
│       └── openwisp_upload.yml          <- Upload OpenWISP (opzionale)
│
├── Jenkinsfile
├── ansible.cfg
└── .gitignore
```

**Il file principale da modificare è `ninux.yml`** — contiene tutte le variabili di build,
la configurazione openwisp-config per organizzazione e i segreti cifrati inline con `ansible-vault encrypt_string`.

---

## Configurazione rapida

```bash
# 1. Clona il repo
git clone https://github.com/mikysal78/ansible-ninux-openwrt.git
cd ansible-ninux-openwrt

# 2. Crea ninux.yml dal template
cp ninux.yml.example ninux.yml

# 3. Modifica org, versione OpenWrt e configurazione openwisp
nano ninux.yml

# 4. Genera i segreti cifrati (shared_secret, credenziali OpenWISP)
#    Vedi sezione "Gestione segreti con ansible-vault"

# 5. Verifica i device disponibili (default = org di esempio, non compilabile)
ls config/organizations/basilicata/

# 6. Lancia la build
ansible-playbook playbooks/build_all.yml \
  -e openwrt_org=basilicata \
  --vault-password-file /var/lib/jenkins/.vault_pass
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
git clone https://github.com/mikysal78/ansible-ninux-openwrt.git
cd ansible-ninux-openwrt
sudo ./setup/install-jenkins.sh

# Con vault password per i segreti openwisp
sudo ./setup/install-jenkins.sh --vault-pass "mia-password-vault"

# Solo dipendenze, Jenkins già installato
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
chown jenkins:jenkins /var/cache/openwrt-ccache
```

#### 6. tmpfs

```bash
mkdir -p /mnt/openwrt-tmpfs
echo "tmpfs /mnt/openwrt-tmpfs tmpfs defaults,size=8G,mode=0777 0 0" >> /etc/fstab
mount /mnt/openwrt-tmpfs
```

#### 7. sudo per jenkins

```bash
cat > /etc/sudoers.d/jenkins-openwrt << 'SUDOEOF'
jenkins ALL=(ALL) NOPASSWD: /bin/mount
jenkins ALL=(ALL) NOPASSWD: /bin/umount
jenkins ALL=(ALL) NOPASSWD: /usr/bin/apt-get
jenkins ALL=(ALL) NOPASSWD: /usr/bin/apt
SUDOEOF
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

Pipeline e Git sono già inclusi nei plugin suggeriti.

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
| `OPENWRT_ORG` | `default` | Organizzazione Ninux |
| `OPENWRT_VERSION` | `v25.12.5` | Tag OpenWrt |
| `VPN_VARIANTS` | `ALL` | `ALL` / `NONE` / `ZeroTier` / `WireGuard` / `Dual` |
| `CAPTIVE_PORTAL_VARIANTS` | true | Compila anche varianti con CP (come `openwrt_cp_variants` in ninux.yml) |
| `CAPTIVE_PORTAL_ENGINE` | `config` | Motore CP: `config` usa ninux.yml (con eventuali override per org), `uspot` lo forza. Unico motore disponibile |
| `SKIP_DEPS` | false | Salta `apt install` (dopo il primo run) |
| `TMPFS_ENABLED` | true | RAM disk per `tmp/` (+30% velocità) |
| `TMPFS_SIZE` | `8G` | Dimensione tmpfs |
| `CCACHE_DIR` | `/var/cache/openwrt-ccache` | ccache persistente |
| `CCACHE_SIZE` | `20G` | Dimensione massima ccache |
| `OPENWISP_UPLOAD` | `config` | Upload su OpenWISP: `config` segue ninux.yml, `on`/`off` forzano |
| `OPENWISP_TRIGGER_UPGRADE` | false | Avvia batch upgrade OpenWISP |
| `OPENWISP_URL` | `` | URL istanza OpenWISP Firmware Upgrader |

### 6. Vault password file

```bash
# Sul server Jenkins — necessario per decifrare i segreti in ninux.yml
echo "mia-password-vault" > /var/lib/jenkins/.vault_pass
chmod 600 /var/lib/jenkins/.vault_pass
chown jenkins:jenkins /var/lib/jenkins/.vault_pass
```

---

## Configurazione del build

**Tutto in `ninux.yml`** nella root del repo. Per una nuova installazione:

```bash
cp ninux.yml.example ninux.yml
nano ninux.yml
```

Sezioni principali:

```yaml
# Versione e org
openwrt_version: "v25.12.5"
openwrt_org: "default"

# Varianti da compilare
openwrt_vpn_variants: [NONE, ZeroTier, WireGuard, Dual]
openwrt_cp_variants: false

# Varianti per organizzazione (vincono sulla lista globale)
openwrt_org_vpn_variants:
  basilicata: [NONE, WireGuard]

# Motori Captive Portal: una build separata per ognuno (mai insieme)
openwrt_cp_engines: [uspot]

# openwisp-config per org (shared_secret cifrata con encrypt_string)
openwisp_orgs:
  default:
    controller_url: "https://openwisp.ninux-nnxx.it"
    management_interface: "owz12345"
    shared_secret: !vault |
          $ANSIBLE_VAULT;1.1;AES256
          <stringa cifrata>

# Performance
openwrt_ccache_dir: "/var/cache/openwrt-ccache"
openwrt_tmpfs_enabled: true
openwrt_tmpfs_size: "8G"
```

---

## Gestione segreti con ansible-vault

I segreti (shared_secret openwisp, credenziali Firmware Upgrader) sono cifrati
**inline in `ninux.yml`** con `ansible-vault encrypt_string`. Non esiste un vault
file separato — tutto sta in un file solo, i valori sensibili sono illeggibili
senza la vault password.

### Setup vault password

```bash
# Sul server Jenkins (una volta sola)
echo "la-tua-password-vault" > /var/lib/jenkins/.vault_pass
chmod 600 /var/lib/jenkins/.vault_pass
chown jenkins:jenkins /var/lib/jenkins/.vault_pass
```

### Generare una stringa cifrata

```bash
ansible-vault encrypt_string \
  --vault-password-file /var/lib/jenkins/.vault_pass \
  'VALORE_DA_CIFRARE' --name 'NOME_VARIABILE'
```

L'output va incollato direttamente in `ninux.yml`.

### Esempio — shared_secret per una nuova org

```bash
ansible-vault encrypt_string \
  --vault-password-file /var/lib/jenkins/.vault_pass \
  'SecretRomaXyz' --name 'shared_secret'
```

Output da incollare in `ninux.yml`:

```yaml
openwisp_orgs:
  esempio:
    controller_url: "https://openwisp.ninux-nnxx.it"
    management_interface: "owzABCDE"
    shared_secret: !vault |
          $ANSIBLE_VAULT;1.1;AES256
          66386439653236336462626566653337...
```

### Esempio — credenziali Firmware Upgrader

```bash
ansible-vault encrypt_string \
  --vault-password-file /var/lib/jenkins/.vault_pass \
  'admin' --name 'openwisp_username'

ansible-vault encrypt_string \
  --vault-password-file /var/lib/jenkins/.vault_pass \
  'MyPassword123' --name 'openwisp_password'
```

### Verificare che una stringa sia decifrabile

```bash
ansible -i inventory/hosts.yml localhost \
  -m debug -a "var=openwisp_orgs.default.shared_secret" \
  -e @ninux.yml \
  --vault-password-file /var/lib/jenkins/.vault_pass
```

---

## Aggiungere device e organizzazioni

### Nuovo device

```bash
# 1. Genera il .config con OpenWrt menuconfig
cd /path/to/openwrt-src
make menuconfig   # seleziona target e salva
cp .config /repo/config/organizations/default/nome_device.config

# 2. Commita
git add config/organizations/default/nome_device.config
git commit -m "feat: aggiungi device nome_device"
```

Il nome del file senza `.config` è il valore di `openwrt_target`.
L'autodiscovery lo includerà automaticamente nella prossima build.

### Nuova organizzazione

> **L'org `default` è solo un esempio e non è compilabile.** I suoi file
> (`config/organizations/default/`, `config/root_files/default/`) servono da
> template da copiare. Una build con `-e openwrt_org=default` si ferma subito
> con un errore. Le org di esempio sono elencate in `openwrt_example_orgs`
> (`ninux.yml`). L'org reale attualmente in produzione è `basilicata`.

**1. Directory dei device** — un `.config` per device, il nome del file (senza
estensione) è il valore di `openwrt_target`. L'autodiscovery li trova da solo:

```bash
mkdir -p config/organizations/esempio
cp config/organizations/default/*.config config/organizations/esempio/
# poi rimuovi i device che l'org non usa
```

**2. Overlay dei file di sistema** — copiato dentro il firmware così com'è:

```bash
mkdir -p config/root_files/esempio
cp -r config/root_files/default/* config/root_files/esempio/
```

Cosa contiene e cosa va adattato:

| File | A cosa serve |
|------|--------------|
| `etc/uci-defaults/99-hostname` | Prefisso hostname dei nodi |
| `etc/uci-defaults/99-dnsmasq`  | DNS della mesh e whitelist DNS-rebind (aggiungi i domini dell'org: senza, il controller OpenWISP non si risolve se punta a IP privati) |
| `etc/config/watchcat`          | Riavvio automatico su perdita connettività |
| `etc/config/zerotier`          | Config ZeroTier (solo build con VPN ZeroTier/Dual) |
| `etc/config/openwisp`          | **Non toccare**: se l'org è in `openwisp_orgs` viene rigenerato dalla build |

L'uci-default `99-zerotier` (VPN ZeroTier/Dual) è generato dal template del
ruolo: non va creato a mano. **Rete mesh e captive portal non stanno nel
firmware**: bridge `br-cp` e configurazione di uspot arrivano da
OpenWISP come template, il firmware porta solo i pacchetti e i file di config
vuoti.

**3. Varianti da compilare** (`ninux.yml`) — opzionale, se l'org non deve
compilare tutte le varianti VPN globali:

```yaml
openwrt_org_vpn_variants:
  esempio:
    - "NONE"
    - "WireGuard"     # include VXLAN

# opzionale: motore Captive Portal diverso dal globale
openwrt_org_cp_engines:
  esempio:
    - "uspot"         # unico motore CP disponibile
```

**4. openwisp-config** (`ninux.yml`) — perché i nodi si registrino al controller.
Servono la `shared_secret` dell'org su OpenWISP e l'interfaccia di management
(`wg0` con WireGuard, `owzXXXX` con ZeroTier):

```bash
ansible-vault encrypt_string --vault-password-file /var/lib/jenkins/.vault_pass \
  'SECRET_DELL_ORG' --name 'shared_secret'
ansible-vault encrypt_string --vault-password-file /var/lib/jenkins/.vault_pass \
  'TOKEN_API_OPENWISP' --name 'api_token'
```

Incolla i due blocchi cifrati sotto `openwisp_orgs`:

```yaml
openwisp_orgs:
  esempio:
    controller_url: "https://openwisp.ninux-nnxx.it"
    management_interface: "wg0"
    shared_secret: !vault |
          $ANSIBLE_VAULT;1.1;AES256
          ...
    api_token: !vault |          # serve solo per l'upload firmware su OpenWISP
          $ANSIBLE_VAULT;1.1;AES256
          ...
```

Il token API si ottiene dal controller con:

```bash
curl -s -X POST https://openwisp.ninux-nnxx.it/api/v1/users/token/ \
  -d "username=UTENTE" -d 'password=PASSWORD'
```

**5. Build**:

```bash
ansible-playbook playbooks/build_all.yml \
  -e openwrt_org=esempio \
  --vault-password-file /var/lib/jenkins/.vault_pass
```

Su Jenkins basta scrivere `esempio` nel parametro `OPENWRT_ORG`.

> Se l'org non è definita in `openwisp_orgs` o manca la `shared_secret`, la build
> continua ma salta la generazione di `/etc/config/openwisp`: i nodi non si
> registrano al controller.

---

## Uso da riga di comando

```bash
# Tutti i device, tutte le varianti VPN
ansible-playbook playbooks/build_all.yml \
  --vault-password-file /var/lib/jenkins/.vault_pass

# Con Captive Portal (2x build per device: senza CP + uspot)
ansible-playbook playbooks/build_all.yml \
  -e openwrt_cp_variants=true \
  --vault-password-file /var/lib/jenkins/.vault_pass

# Solo alcune varianti VPN
ansible-playbook playbooks/build_all.yml \
  -e '{"openwrt_vpn_variants": ["NONE", "ZeroTier"]}' \
  --vault-password-file /var/lib/jenkins/.vault_pass

# Singolo device, tutte le varianti
ansible-playbook playbooks/build_firmware.yml \
  -e openwrt_target=glinet_gl-mt300n-v2 \
  --vault-password-file /var/lib/jenkins/.vault_pass

# Solo installazione dipendenze
ansible-playbook playbooks/build_all.yml --tags deps \
  --vault-password-file /var/lib/jenkins/.vault_pass

# Solo build (dipendenze già installate)
ansible-playbook playbooks/build_all.yml --skip-tags deps \
  --vault-password-file /var/lib/jenkins/.vault_pass

# Pulizia disco
ansible-playbook playbooks/cleanup.yml                         # solo temporanei
ansible-playbook playbooks/cleanup.yml -e cleanup_full=true   # tutto
ansible-playbook playbooks/cleanup.yml -e cleanup_output=true # solo output/
```

---

## Performance e ottimizzazioni

### Strategia di build

```
Device 1
  ├── VPN=NONE      ─┐
  ├── VPN=ZeroTier   ├─ parallelo (async, condividono toolchain)
  ├── VPN=WireGuard  │
  └── VPN=Dual      ─┘
  → pulizia staging_dir/build_dir
Device 2
  └── (idem)
...
Post: pulizia totale + smonta tmpfs + stats ccache
```

Le varianti dello stesso device condividono la toolchain già compilata
e ricompilano solo i pacchetti che differiscono (pochi MB),
quindi il parallelo è efficiente senza moltiplicare RAM/disco.

### Impatto stimato su 12 CPU / 24 GB RAM

| Ottimizzazione | Guadagno |
|----------------|----------|
| `make -j14` (nproc+2) | baseline |
| ccache (dalla 2a build) | **-70%** tempo |
| tmpfs per `tmp/` | **-30%** I/O |
| 4 varianti in parallelo | **-60%** per device |

### ImageBuilder (sperimentale)

Le varianti dello stesso device differiscono solo per **quali** pacchetti sono
installati, non per come sono compilati. Ricompilare toolchain, kernel e
pacchetti a ogni variante è lavoro buttato.

Attivo di default (`openwrt_use_imagebuilder: true`), la build è a due tempi:

```
Device 1
  ├── seed  (1 compilazione completa, superset delle varianti)  ~30-60 min
  │     └── produce openwrt-imagebuilder-*.tar.zst + repo pacchetti
  └── per ogni variante: make image dall'ImageBuilder            ~1-3 min
```

Con la matrice attuale di basilicata (2 VPN × 2 CP = 4 varianti/device) si
passa da 4 compilazioni complete a 1 + 4 assemblaggi.

Da Jenkins: parametro `USE_IMAGEBUILDER`. Da riga di comando:

```bash
ansible-playbook playbooks/build_all.yml -e openwrt_use_imagebuilder=true
```

**Un seed per device.** Presuppone che tutti i motori in `openwrt_cp_engines`
siano compilabili insieme: vale con uspot, unico motore rimasto. Un motore che
imponesse scelte di compilazione incompatibili (com'era coova-chilli, che
richiedeva firewall3 + iptables legacy contro firewall4 + nftables)
richiederebbe di nuovo un seed separato per motore.

**Cache e `openwrt_ib_force_seed`.** Gli ImageBuilder restano in
`build/imagebuilder/<versione>/<org>/<device>/` e sopravvivono alla pulizia
post-build, ma **`openwrt_ib_force_seed` è `true` di default**, quindi il seed
viene comunque ricompilato.

Il motivo: la chiave di cache è `versione/org/device` e non tiene conto del
*contenuto* della configurazione. Modificando `base.config`, un `.config` di
device o i feed, una build con la cache attiva riuserebbe un ImageBuilder
costruito con la configurazione vecchia e produrrebbe firmware con i pacchetti
sbagliati, senza alcun errore. Dato che si compila di rado e quasi sempre per
una nuova versione OpenWrt — caso in cui la cache è comunque da rifare — il
default sicuro vince sul default veloce.

Mettendolo a `false` (Jenkins: `IB_FORCE_SEED` deselezionato) si passa da ore a
minuti, ma va fatto solo sapendo che nulla di ciò che finisce nel seed è
cambiato dall'ultima compilazione.

**Composizione delle varianti.** `roles/ninux_build_openwrt/files/ib_packages.py`
traduce i `.config`/`.ext` del repo nella lista `PACKAGES` per `make image`, così
la composizione resta definita in un posto solo. Distingue rimozioni esplicite
(`# CONFIG_PACKAGE_x is not set`: deliberate, sempre applicate) da quelle
implicite (pacchetti di un'estensione non usata in questa variante), che vengono filtrate contro i pacchetti di default del target
per non togliere per sbaglio componenti base.

I nomi dei file prodotti sono identici a quelli del percorso normale: release
GitHub e upload OpenWISP non cambiano.

> Percorso sperimentale, `false` di default. Se un assemblaggio fallisce, il
> sospetto numero uno è una rimozione implicita che ha tolto una dipendenza:
> il log mostra la lista `PACKAGES` completa prima di `make image`.

### Proxmox LXC e tmpfs

```bash
# Host Proxmox
echo "features: nesting=1" >> /etc/pve/lxc/<CTID>.conf
pct restart <CTID>
```

---

## OpenWISP Firmware Upgrader

### Configurazione

In `ninux.yml`:

```yaml
openwisp_upload_enabled: true
openwisp_url: "https://openwisp.ninux-nnxx.it"
openwisp_org_slug: "default"
openwisp_org_id: !vault |
      $ANSIBLE_VAULT;1.1;AES256
      <UUID cifrato>
openwisp_trigger_upgrade: false   # true = avvia upgrade automatico

openwisp_replace_build: true      # stessa versione = build sostituita
openwisp_keep_versions: 3         # versioni OpenWrt da tenere (0 = tieni tutto)

openwisp_orgs:
  basilicata:
    controller_url: "https://openwisp.ninux-nnxx.it"
    management_interface: "wg0"
    shared_secret: !vault |
          $ANSIBLE_VAULT;1.1;AES256
          <stringa cifrata>
    api_token: !vault |
          $ANSIBLE_VAULT;1.1;AES256
          <token API cifrato>
```

### Sostituzione e retention

Su OpenWISP c'è una **category per device** (`Ninux Basilicata - x86_64`) e dentro
una **build per variante** (`v25.12.5-x86_64-VPN-WG`). La versione della build
contiene la versione OpenWrt, quindi le build si accumulano a ogni nuovo tag.

- **`openwisp_replace_build: true`** — se ricompili la *stessa* versione OpenWrt,
  la build esistente viene cancellata e ricreata. Serve: riusandola, l'upload
  dell'immagine risponderebbe `400` (duplicato) e sul controller resterebbe il
  firmware **vecchio**.
- **`openwisp_keep_versions: 3`** — dopo l'upload tiene solo le build delle 3
  versioni OpenWrt più recenti per ogni device, cancellando le più vecchie (le
  immagini vengono rimosse in cascata). La retention ragiona per *versione*, non
  per singola build: tutte le varianti VPN/CP della stessa versione restano
  insieme. `0` disattiva la cancellazione.

### Flusso

```
Build → artifacts.yml → openwisp_upload.yml
  1. Token Bearer da api_token (nessun login, evita rate limiting)
  2. Risolvi UUID organizzazione da ninux.yml
  3. Cerca/crea Category (org + device target)
  4. Crea Build (versione-target-VPN-CP)
  5. Carica immagine sysupgrade (type = nome file senza prefisso openwrt-)
  6. (opzionale) Batch upgrade
```

Un upload fallito **non** fa fallire la build: la variante finisce in
`output/.openwisp-upload-failed` con il codice HTTP e la risposta del
controller, e Jenkins marca la build UNSTABLE (gialla).

### Board non riconosciute dal controller (upload rifiutato con 400)

Il campo `type` dell'immagine deve essere tra quelli che il controller conosce
(la sua mappa hardware). Se la board manca — o OpenWrt ne ha cambiato il nome
file — l'upload risponde `400` e il firmware **non viene caricato**: la build
resta vuota su OpenWISP anche se su Jenkins è tutto verde.

È successo con i device basilicata: dei 6 solo `x86_64` combaciava. Il
controller conosceva `gl-mt300n-v2` (nome vecchio, oggi `glinet_gl-mt300n-v2`),
si aspettava `sysupgrade.img` per il Linksys (oggi `.bin`), e non aveva affatto
TOTOLINK X5000R, TP-Link C2600 e Zyxel NWA50AX Pro.

Si risolve **sul controller**, aggiungendo le board mancanti in
`settings.py` di OpenWISP:

```python
OPENWISP_CUSTOM_OPENWRT_IMAGES = (
    ('ramips-mt76x8-glinet_gl-mt300n-v2-squashfs-sysupgrade.bin', {
        'label': 'GL.iNet GL-MT300N-V2',
        'boards': ('GL.iNet GL-MT300N-V2',),
    }),
    ('mvebu-cortexa9-linksys_wrt3200acm-squashfs-sysupgrade.bin', {
        'label': 'Linksys WRT3200ACM',
        'boards': ('Linksys WRT3200ACM',),
    }),
    ('ramips-mt7621-totolink_x5000r-squashfs-sysupgrade.bin', {
        'label': 'TOTOLINK X5000R',
        'boards': ('TOTOLINK X5000R',),
    }),
    ('ipq806x-generic-tplink_c2600-squashfs-sysupgrade.bin', {
        'label': 'TP-Link Archer C2600',
        'boards': ('TP-Link Archer C2600',),
    }),
    ('mediatek-filogic-zyxel_nwa50ax-pro-squashfs-sysupgrade.bin', {
        'label': 'Zyxel NWA50AX Pro',
        'boards': ('Zyxel NWA50AX Pro',),
    }),
)
```

Poi riavviare OpenWISP. I valori in `boards` devono corrispondere al modello
riportato dai device registrati (admin → Devices → colonna *Hardware/Board*):
se un upgrade non parte pur con l'immagine caricata, è quasi sempre questo
campo che non combacia. Per verificare i `type` accettati dal controller:

```bash
curl -s -X OPTIONS -H "Authorization: Bearer $TOKEN" \
  https://openwisp.ninux-nnxx.it/api/v1/firmware-upgrader/build/<build-id>/image/ \
  | python3 -c "import json,sys; [print(c['value']) for c in json.load(sys.stdin)['actions']['POST']['type']['choices']]"
```

**Lato repo** il `type` inviato in upload non è più derivato dal nome file, ma
preso da `openwisp_image_type_map` (`config/build.yml`), che mappa ogni
`openwrt_target` alla chiave attesa dal controller:

```yaml
openwisp_image_type_map:
  glinet_gl-mt300n-v2: "ramips-mt76x8-gl-mt300n-v2-squashfs-sysupgrade.bin"
  linksys_wrt3200acm: "mvebu-cortexa9-linksys_wrt3200acm-squashfs-sysupgrade.img"
  x86_64: "x86-64-generic-squashfs-combined-efi.img.gz"
  totolink_X5000R: "ramips-mt7621-totolink_x5000r-squashfs-sysupgrade.bin"
  tplink_c2600: "ipq806x-generic-tplink_c2600-squashfs-sysupgrade.bin"
  zyxel_nwa50ax-pro: "mediatek-filogic-zyxel_nwa50ax-pro-squashfs-sysupgrade.bin"
```

I primi tre usano le chiavi native di OpenWISP; gli ultimi tre esistono solo
grazie a `OPENWISP_CUSTOM_OPENWRT_IMAGES` sul controller (playbook `openwisp2`):
i `type` delle due parti devono restare identici. Un target assente dalla mappa
viene saltato in upload e annotato in `output/.openwisp-unsupported` (build
comunque verde).

---

## GitHub Release

Dopo ogni build è possibile pubblicare i firmware come release GitHub,
rendendoli scaricabili direttamente dalla pagina Releases del repository.

### Prerequisiti

**1. Personal Access Token (PAT) su GitHub**

Vai su `https://github.com/settings/tokens` → **Generate new token (fine-grained)**:

| Campo | Valore |
|-------|--------|
| Repository access | solo `ansible-ninux-openwrt` |
| Contents | **Read and write** |
| Metadata | Read (obbligatorio) |

**2. Credenziale Jenkins**

Vai su **Manage Jenkins → Credentials → System → Global → Add Credentials**:

| Campo | Valore |
|-------|--------|
| Kind | Secret text |
| Secret | il token GitHub |
| ID | `github-release-token` |

### Configurazione in ninux.yml

```yaml
github_release_enabled: true
github_repo: "mikysal78/ansible-ninux-openwrt"
github_prerelease: true           # false per release ufficiali
github_release_include_sha256: true
```

### Struttura della release

Ogni release viene creata con tag `<versione>-<org>-build<N>`, es. `v25.12.5-default-build42`.
Gli asset vengono caricati con nome che riflette il percorso:

```
Standard_VPN-NO_x86_64_openwrt-x86-64-generic-squashfs-combined-efi.img.gz
Standard_VPN-ZeroTier_x86_64_openwrt-x86-64-generic-squashfs-combined-efi.img.gz
CaptivePortal_VPN-WireGuard_glinet_gl-mt300n-v2_openwrt-...-squashfs-sysupgrade.bin
...
```

### Attivazione da Jenkins

Imposta `github_release_enabled: true` in `ninux.yml` per abilitarlo sempre,
oppure usa il parametro **`GITHUB_RELEASE`** al lancio del job: `config` segue
ninux.yml, `on` e `off` lo forzano.

> `GITHUB_RELEASE` e `OPENWISP_UPLOAD` erano booleani, ma un booleano non sa
> dire "no": con `github_release_enabled: true` in `ninux.yml` la release
> partiva comunque, anche a parametro deselezionato. Sono diventati a tre stati
> per questo — una build di prova pubblicava firmware sul repo pubblico e sul
> controller credendo di non farlo.

---

## Struttura dei firmware prodotti

```
output/
└── v25.12.5/
    └── default/
        ├── Standard/
        │   ├── VPN-NONE/glinet_gl-mt300n-v2/
        │   ├── VPN-ZeroTier/glinet_gl-mt300n-v2/
        │   ├── VPN-WireGuard/glinet_gl-mt300n-v2/
        │   └── VPN-Dual/glinet_gl-mt300n-v2/
        ├── CaptivePortal-uspot/     <- uspot
        │   └── VPN-*/...
        └── CaptivePortal-uspot/     <- uspot (build separata)
            └── VPN-*/...
```

---

## Test e CI

Su ogni push e pull request, GitHub Actions (`.github/workflows/ci.yml`) esegue
lint e test. **La compilazione vera resta su Jenkins**: un firmware OpenWrt da
sorgenti sono ore di build e decine di GB, fuori dalla portata di un runner
GitHub (14 GB di disco). Quello che la CI prova è tutto il resto — cioè dove
sono nati gli errori veri: quali pacchetti finiscono in quale variante, quali
file di config entrano nell'immagine, e cosa succede sul controller OpenWISP.

### Cosa gira

| Job | Cosa fa |
|-----|---------|
| `lint` | `yamllint`, `ansible-lint`, `--syntax-check` di ogni playbook, `shellcheck` sugli uci-defaults e sugli script di setup |
| `test` | Molecule: esegue il ruolo **per davvero** su un device simulato, poi verifica firmware e controller. Più il controllo che un'org di esempio non sia compilabile |

### Come funziona la simulazione

Il ruolo gira integralmente (overlay, feeds, `.config`, artefatti, upload):
sono finti solo i due pezzi impossibili da avere in CI.

- **Toolchain OpenWrt** (`molecule/default/files/openwrt-stub/`) — un `Makefile`
  che non compila niente ma scrive **dentro il finto firmware il `.config`
  assemblato**. Così i test verificano quali pacchetti sarebbero davvero finiti
  nell'immagine, senza compilare.
- **Controller OpenWISP** (`molecule/default/files/mock_openwisp.py`) — un mock
  in ascolto su `127.0.0.1:8099` che implementa gli endpoint usati dal ruolo e
  parte già popolato con 4 versioni preesistenti. Riproduce anche il `400` su
  immagine duplicata, che è il motivo per cui le build vanno sostituite.

Vengono compilate tre varianti di un solo device (`glinet_gl-mt300n-v2`): nessuna
VPN senza portale, il caso reale di basilicata (**uspot + WireGuard con VXLAN**)
e **Dual + uspot**. Le regole verificate sono quelle del progetto:

- i config di captive portal e VPN entrano **solo** nella variante che li usa
  (in passato `/etc/config/chilli` finiva in *tutte* le immagini);
- nel firmware non ci sono uci-defaults di rete né i pacchetti autoip: mesh e
  portale li configura OpenWISP con i suoi template;
- sul controller restano **solo le ultime 3 versioni**, e ricompilare la stessa
  versione la **sostituisce** invece di lasciare online il firmware vecchio.

L'ultima è la più importante: un errore nella retention cancella lo storico dei
firmware dal controller. Il test lo intercetta.

### Lanciarli in locale

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

molecule test        # test completi (~1 minuto, nessun Docker, nessuna rete)
ansible-lint         # lint dei playbook
yamllint .
```

Molecule usa il driver `default`: gira su localhost, non serve Docker. La work
dir dei test sta nella directory effimera di Molecule, il repo non viene toccato.

Per aggiungere una variante ai test basta aggiungerla a `t_variants` in
`molecule/default/vars/main.yml` e le attese corrispondenti in
`molecule/default/verify.yml`.

---

## Troubleshooting

### `openwrt_work_dir is undefined`

Assicurati di usare i playbook da `playbooks/` — caricano `ninux.yml`
tramite `vars_files`. Non richiamare il ruolo direttamente senza caricare le variabili.

### `shared_secret is undefined` o firmware senza `/etc/config/openwisp`

Verifica che l'org sia definita in `openwisp_orgs` in `ninux.yml` con tutti e tre
i campi (`controller_url`, `management_interface`, `shared_secret`). Se `shared_secret`
manca o non è decifrabile, la build continua senza generare il file e logga un avviso.

### `Decryption failed` sui campi `!vault`

Il `--vault-password-file` non corrisponde alla password usata durante `encrypt_string`.
Verifica che `/var/lib/jenkins/.vault_pass` contenga la password corretta.

### `chown failed: Operation not permitted` su NFS

I task non usano `owner` sulle directory NFS. Se persiste, verifica che
il server NFS esporti con `no_root_squash` o adatta i permessi lato server.

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

---

## Licenza

GPL-3.0
