🇬🇧 English | [🇮🇹 Italiano](README.it.md)

# ansible-ninux-openwrt

[![CI](https://github.com/mikysal78/ansible-ninux-openwrt/actions/workflows/ci.yml/badge.svg)](https://github.com/mikysal78/ansible-ninux-openwrt/actions/workflows/ci.yml)

Automated **OpenWrt** firmware build system for the nodes of the [Ninux](http://ninux.org) mesh network.

---

## Table of contents

1. [Repository structure](#repository-structure)
2. [Quick setup](#quick-setup)
3. [Installing Jenkins on Debian Trixie](#installing-jenkins-on-debian-trixie)
4. [Jenkins configuration](#jenkins-configuration)
5. [Build configuration](#build-configuration)
6. [Managing secrets with ansible-vault](#managing-secrets-with-ansible-vault)
7. [Adding devices and organizations](#adding-devices-and-organizations)
8. [Command-line usage](#command-line-usage)
9. [Performance and optimizations](#performance-and-optimizations)
10. [OpenWISP Firmware Upgrader](#openwisp-firmware-upgrader)
11. [GitHub Release](#github-release)
12. [Structure of the produced firmware](#structure-of-the-produced-firmware)
13. [Tests and CI](#tests-and-ci)
14. [Troubleshooting](#troubleshooting)

---

## Repository structure

```
ansible-ninux-openwrt/
│
├── ninux.yml                            <- MAIN CONFIGURATION (edit here)
├── ninux.yml.example                    <- Template for new installations
│
├── config/
│   ├── base.config                      <- Packages common to all targets
│   ├── uspot.ext                        <- Captive Portal extension (uspot) — separate build
│   ├── zerotier.ext                     <- ZeroTier VPN extension
│   ├── wireguard.ext                    <- WireGuard VPN extension (includes VXLAN)
│   └── organizations/
│       └── <org>/
│           └── <device>.config          <- Per-device config
│
├── setup/
│   └── install-jenkins.sh               <- Self-install script (Debian Trixie)
│
├── inventory/
│   ├── hosts.yml                        <- Build host (localhost)
│   └── group_vars/build_hosts.yml
│
├── playbooks/
│   ├── build_all.yml                    <- Build all devices (parallel variants)
│   ├── build_firmware.yml               <- Build a single device
│   ├── build_matrix.yml                 <- Custom build matrix
│   ├── build_parallel.yml               <- Parallel build across devices
│   ├── cleanup.yml                      <- Manual disk cleanup
│   └── _build_device_variants.yml       <- Internal helper
│
├── roles/ninux_build_openwrt/
│   ├── defaults/main.yml                <- Role variable defaults
│   └── tasks/
│       ├── main.yml
│       ├── deps.yml                     <- apt install dependencies
│       ├── prepare.yml                  <- Directories, ccache, tmpfs
│       ├── clone_ninux.yml              <- Copy config/ to the build host
│       ├── clone_openwrt.yml            <- Clone/update OpenWrt
│       ├── rootfiles.yml                <- Filesystem overlay + openwisp-config
│       ├── feeds.yml                    <- feeds.conf + update + install
│       ├── dotconfig.yml                <- Assemble .config
│       ├── build.yml                    <- make download + make -jN
│       ├── artifacts.yml                <- Copy firmware to output/ and NFS
│       └── openwisp_upload.yml          <- OpenWISP upload (optional)
│
├── Jenkinsfile
├── ansible.cfg
└── .gitignore
```

**The main file to edit is `ninux.yml`** — it holds all the build variables,
the per-organization openwisp-config settings, and secrets encrypted inline
with `ansible-vault encrypt_string`.

---

## Quick setup

```bash
# 1. Clone the repo
git clone https://github.com/mikysal78/ansible-ninux-openwrt.git
cd ansible-ninux-openwrt

# 2. Create ninux.yml from the template
cp ninux.yml.example ninux.yml

# 3. Edit org, OpenWrt version and openwisp configuration
nano ninux.yml

# 4. Generate the encrypted secrets (shared_secret, OpenWISP credentials)
#    See the "Managing secrets with ansible-vault" section

# 5. Check the available devices (default = example org, not buildable)
ls config/organizations/basilicata/

# 6. Run the build
ansible-playbook playbooks/build_all.yml \
  -e openwrt_org=basilicata \
  --vault-password-file /var/lib/jenkins/.vault_pass
```

---

## Installing Jenkins on Debian Trixie

### Recommended hardware requirements (Proxmox LXC)

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU      | 4 cores | 12 cores    |
| RAM      | 8 GB    | 24 GB       |
| Disk     | 80 GB   | 200 GB      |

> **Proxmox LXC note**: the container must have `nesting=1` enabled to allow
> mounting tmpfs. In `/etc/pve/lxc/<CTID>.conf`:
> ```
> features: nesting=1
> ```
> Then: `pct restart <CTID>`

### Automatic installation (recommended)

```bash
git clone https://github.com/mikysal78/ansible-ninux-openwrt.git
cd ansible-ninux-openwrt
sudo ./setup/install-jenkins.sh

# With a vault password for the openwisp secrets
sudo ./setup/install-jenkins.sh --vault-pass "my-vault-password"

# Dependencies only, Jenkins already installed
sudo ./setup/install-jenkins.sh --skip-jenkins
```

The script automatically installs and configures:

- Java 21 (OpenJDK)
- Ansible (via pipx, the recommended method on Trixie)
- Jenkins LTS with the 2026 GPG key
- All OpenWrt build dependencies
- Persistent ccache in `/var/cache/openwrt-ccache`
- tmpfs in `/mnt/openwrt-tmpfs` (8G, mounted at boot via fstab)
- sudo permissions for the `jenkins` user

### Manual step-by-step installation

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

# Initial password
cat /var/lib/jenkins/secrets/initialAdminPassword
```

#### 4. OpenWrt build dependencies

```bash
apt-get install -y \
  build-essential ccache time git subversion g++ bash make \
  libssl-dev patch libncurses-dev zlib1g-dev gawk flex gettext \
  wget unzip xz-utils python3 python3-distutils-extra \
  rsync curl libsnmp-dev liblzma-dev libpam0g-dev cpio
```

#### 5. Persistent ccache

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

#### 7. sudo for jenkins

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

## Jenkins configuration

### 1. First login

1. Open `http://<SERVER-IP>:8080`
2. Enter the initial password: `cat /var/lib/jenkins/secrets/initialAdminPassword`
3. Choose **"Install suggested plugins"**
4. Create the admin user

### 2. Additional required plugins

Go to **Manage Jenkins → Plugins → Available plugins**:

| Plugin | Notes |
|--------|-------|
| **Ansible** | Ansible integration |
| **Timestamper** | Timestamps in build logs |
| **Build Timeout** | Timeout for long builds |
| **Workspace Cleanup** | Post-build workspace cleanup |

Pipeline and Git are already included in the suggested plugins.

### 3. Configuring Ansible in Jenkins

**Manage Jenkins → Tools → Ansible installations**:

- Name: `ansible`
- Install automatically: **no**
- Path to ansible executables directory: `/root/.local/bin`

### 4. Creating the Pipeline job

1. **New Item** → name `NinuxOpenwrt` → type **Pipeline** → OK
2. **General** tab:
   - Check **"Do not allow concurrent builds"**
   - Build Timeout: **240 minutes**
3. **Pipeline** tab:
   - Definition: **Pipeline script from SCM**
   - SCM: **Git**
   - Repository URL: `https://github.com/mikysal78/ansible-ninux-openwrt.git`
   - Branch Specifier: `*/main`
   - Script Path: `Jenkinsfile`
4. **Save** → **Build with Parameters** for the first run

### 5. Job parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `OPENWRT_ORG` | `default` | Ninux organization |
| `OPENWRT_VERSION` | `v25.12.5` | OpenWrt tag |
| `VPN_VARIANTS` | `ALL` | `ALL` / `NONE` / `ZeroTier` / `WireGuard` / `Dual` |
| `CAPTIVE_PORTAL_VARIANTS` | true | Also build CP variants (like `openwrt_cp_variants` in ninux.yml) |
| `CAPTIVE_PORTAL_ENGINE` | `config` | CP engine: `config` follows ninux.yml (with any per-org override), `uspot` forces it. Currently the only available engine |
| `SKIP_DEPS` | false | Skip `apt install` (after the first run) |
| `TMPFS_ENABLED` | true | RAM disk for `tmp/` (+30% speed) |
| `TMPFS_SIZE` | `8G` | tmpfs size |
| `CCACHE_DIR` | `/var/cache/openwrt-ccache` | Persistent ccache |
| `CCACHE_SIZE` | `20G` | Maximum ccache size |
| `OPENWISP_UPLOAD` | `config` | Upload to OpenWISP: `config` follows ninux.yml, `on`/`off` force it |
| `OPENWISP_TRIGGER_UPGRADE` | false | Trigger an OpenWISP batch upgrade |
| `OPENWISP_URL` | `` | OpenWISP Firmware Upgrader instance URL |

### 6. Vault password file

```bash
# On the Jenkins server — needed to decrypt the secrets in ninux.yml
echo "my-vault-password" > /var/lib/jenkins/.vault_pass
chmod 600 /var/lib/jenkins/.vault_pass
chown jenkins:jenkins /var/lib/jenkins/.vault_pass
```

---

## Build configuration

**Everything lives in `ninux.yml`** at the repo root. For a new installation:

```bash
cp ninux.yml.example ninux.yml
nano ninux.yml
```

Main sections:

```yaml
# Version and org
openwrt_version: "v25.12.5"
openwrt_org: "default"

# Variants to build
openwrt_vpn_variants: [NONE, ZeroTier, WireGuard, Dual]
openwrt_cp_variants: false

# Per-organization variants (override the global list)
openwrt_org_vpn_variants:
  basilicata: [NONE, WireGuard]

# Captive Portal engines: one separate build per engine (never combined)
openwrt_cp_engines: [uspot]

# openwisp-config per org (shared_secret encrypted with encrypt_string)
openwisp_orgs:
  default:
    controller_url: "https://openwisp.ninux-nnxx.it"
    management_interface: "owz12345"
    shared_secret: !vault |
          $ANSIBLE_VAULT;1.1;AES256
          <encrypted string>

# Performance
openwrt_ccache_dir: "/var/cache/openwrt-ccache"
openwrt_tmpfs_enabled: true
openwrt_tmpfs_size: "8G"
```

---

## Managing secrets with ansible-vault

Secrets (openwisp shared_secret, Firmware Upgrader credentials) are encrypted
**inline in `ninux.yml`** with `ansible-vault encrypt_string`. There is no
separate vault file — everything lives in one file, and sensitive values are
unreadable without the vault password.

### Setting up the vault password

```bash
# On the Jenkins server (once)
echo "your-vault-password" > /var/lib/jenkins/.vault_pass
chmod 600 /var/lib/jenkins/.vault_pass
chown jenkins:jenkins /var/lib/jenkins/.vault_pass
```

### Generating an encrypted string

```bash
ansible-vault encrypt_string \
  --vault-password-file /var/lib/jenkins/.vault_pass \
  'VALUE_TO_ENCRYPT' --name 'VARIABLE_NAME'
```

The output is pasted directly into `ninux.yml`.

### Example — shared_secret for a new org

```bash
ansible-vault encrypt_string \
  --vault-password-file /var/lib/jenkins/.vault_pass \
  'SecretRomaXyz' --name 'shared_secret'
```

Output to paste into `ninux.yml`:

```yaml
openwisp_orgs:
  example:
    controller_url: "https://openwisp.ninux-nnxx.it"
    management_interface: "owzABCDE"
    shared_secret: !vault |
          $ANSIBLE_VAULT;1.1;AES256
          66386439653236336462626566653337...
```

### Example — Firmware Upgrader credentials

```bash
ansible-vault encrypt_string \
  --vault-password-file /var/lib/jenkins/.vault_pass \
  'admin' --name 'openwisp_username'

ansible-vault encrypt_string \
  --vault-password-file /var/lib/jenkins/.vault_pass \
  'MyPassword123' --name 'openwisp_password'
```

### Example — default root password in the firmware

Set in the firmware as a hash in `/etc/shadow` (never the plaintext
password), applies to all orgs. Empty/absent = no password is set, same as
before.

```bash
ansible-vault encrypt_string \
  --vault-password-file /var/lib/jenkins/.vault_pass \
  'YOUR_PASSWORD' --name 'openwrt_root_password'
```

Output to paste into `ninux.yml` (a global variable, not under `openwisp_orgs`):

```yaml
openwrt_root_password: !vault |
      $ANSIBLE_VAULT;1.1;AES256
      66386439653236336462626566653337...
```

### Verifying a string is decryptable

```bash
ansible -i inventory/hosts.yml localhost \
  -m debug -a "var=openwisp_orgs.default.shared_secret" \
  -e @ninux.yml \
  --vault-password-file /var/lib/jenkins/.vault_pass
```

---

## Adding devices and organizations

### New device

```bash
# 1. Generate the .config with OpenWrt menuconfig
cd /path/to/openwrt-src
make menuconfig   # select the target and save
cp .config /repo/config/organizations/default/device_name.config

# 2. Commit
git add config/organizations/default/device_name.config
git commit -m "feat: add device_name device"
```

The filename without `.config` is the value of `openwrt_target`.
Autodiscovery will include it automatically in the next build.

### New organization

> **The `default` org is only an example and is not buildable.** Its files
> (`config/organizations/default/`, `config/root_files/default/`) serve as a
> template to copy. A build with `-e openwrt_org=default` stops immediately
> with an error. Example orgs are listed in `openwrt_example_orgs`
> (`ninux.yml`). The real org currently in production is `basilicata`.

**1. Device directory** — one `.config` per device, the filename (without
extension) is the value of `openwrt_target`. Autodiscovery finds them on its
own:

```bash
mkdir -p config/organizations/example
cp config/organizations/default/*.config config/organizations/example/
# then remove the devices the org doesn't use
```

**2. System files overlay** — copied into the firmware as-is:

```bash
mkdir -p config/root_files/example
cp -r config/root_files/default/* config/root_files/example/
```

What it contains and what needs adapting:

| File | Purpose |
|------|---------|
| `etc/uci-defaults/99-hostname` | Hostname prefix for the nodes |
| `etc/uci-defaults/99-dnsmasq`  | Mesh DNS and DNS-rebind whitelist (add the org's domains: without it, the OpenWISP controller can't be resolved if it points to private IPs) |
| `etc/config/watchcat`          | Automatic reboot on connectivity loss |
| `etc/config/zerotier`          | ZeroTier config (ZeroTier/Dual VPN builds only) |
| `etc/config/openwisp`          | **Do not touch**: if the org is in `openwisp_orgs` it's regenerated by the build |

The `99-zerotier` uci-default (ZeroTier/Dual VPN) is generated by the role's
template: it should not be created by hand. **The mesh network and captive
portal don't live in the firmware**: the `br-cp` bridge and the uspot
configuration come from OpenWISP as templates — the firmware only ships the
packages and empty config files.

**3. Variants to build** (`ninux.yml`) — optional, if the org shouldn't build
all the global VPN variants:

```yaml
openwrt_org_vpn_variants:
  example:
    - "NONE"
    - "WireGuard"     # includes VXLAN

# optional: a Captive Portal engine different from the global one
openwrt_org_cp_engines:
  example:
    - "uspot"         # the only available CP engine
```

**4. openwisp-config** (`ninux.yml`) — so the nodes register with the
controller. You need the org's `shared_secret` on OpenWISP and the management
interface (`wg0` with WireGuard, `owzXXXX` with ZeroTier):

```bash
ansible-vault encrypt_string --vault-password-file /var/lib/jenkins/.vault_pass \
  'ORG_SECRET' --name 'shared_secret'
ansible-vault encrypt_string --vault-password-file /var/lib/jenkins/.vault_pass \
  'OPENWISP_API_TOKEN' --name 'api_token'
```

Paste the two encrypted blocks under `openwisp_orgs`:

```yaml
openwisp_orgs:
  example:
    controller_url: "https://openwisp.ninux-nnxx.it"
    management_interface: "wg0"
    shared_secret: !vault |
          $ANSIBLE_VAULT;1.1;AES256
          ...
    api_token: !vault |          # only needed for uploading firmware to OpenWISP
          $ANSIBLE_VAULT;1.1;AES256
          ...
```

The API token is obtained from the controller with:

```bash
curl -s -X POST https://openwisp.ninux-nnxx.it/api/v1/users/token/ \
  -d "username=USER" -d 'password=PASSWORD'
```

**5. Build**:

```bash
ansible-playbook playbooks/build_all.yml \
  -e openwrt_org=example \
  --vault-password-file /var/lib/jenkins/.vault_pass
```

On Jenkins, just set the `OPENWRT_ORG` parameter to `example`.

> If the org isn't defined in `openwisp_orgs`, or `shared_secret` is missing,
> the build continues but skips generating `/etc/config/openwisp`: the nodes
> won't register with the controller.

---

## Command-line usage

```bash
# All devices, all VPN variants
ansible-playbook playbooks/build_all.yml \
  --vault-password-file /var/lib/jenkins/.vault_pass

# With Captive Portal (2x builds per device: no CP + uspot)
ansible-playbook playbooks/build_all.yml \
  -e openwrt_cp_variants=true \
  --vault-password-file /var/lib/jenkins/.vault_pass

# Only some VPN variants
ansible-playbook playbooks/build_all.yml \
  -e '{"openwrt_vpn_variants": ["NONE", "ZeroTier"]}' \
  --vault-password-file /var/lib/jenkins/.vault_pass

# Single device, all variants
ansible-playbook playbooks/build_firmware.yml \
  -e openwrt_target=glinet_gl-mt300n-v2 \
  --vault-password-file /var/lib/jenkins/.vault_pass

# Dependency installation only
ansible-playbook playbooks/build_all.yml --tags deps \
  --vault-password-file /var/lib/jenkins/.vault_pass

# Build only (dependencies already installed)
ansible-playbook playbooks/build_all.yml --skip-tags deps \
  --vault-password-file /var/lib/jenkins/.vault_pass

# Disk cleanup
ansible-playbook playbooks/cleanup.yml                         # temp files only
ansible-playbook playbooks/cleanup.yml -e cleanup_full=true   # everything
ansible-playbook playbooks/cleanup.yml -e cleanup_output=true # output/ only
```

---

## Performance and optimizations

### Build strategy

```
Device 1
  ├── VPN=NONE      ─┐
  ├── VPN=ZeroTier   ├─ parallel (async, share the toolchain)
  ├── VPN=WireGuard  │
  └── VPN=Dual      ─┘
  → clean up staging_dir/build_dir
Device 2
  └── (same)
...
Post: full cleanup + unmount tmpfs + ccache stats
```

Variants of the same device share the already-compiled toolchain and only
recompile the packages that differ (a few MB), so running them in parallel is
efficient without multiplying RAM/disk usage.

### Estimated impact on 12 CPU / 24 GB RAM

| Optimization | Gain |
|---------------|------|
| `make -j14` (nproc+2) | baseline |
| ccache (from the 2nd build on) | **-70%** time |
| tmpfs for `tmp/` | **-30%** I/O |
| 4 variants in parallel | **-60%** per device |

### ImageBuilder (experimental)

Variants of the same device only differ in **which** packages get installed,
not in how they're compiled. Recompiling the toolchain, kernel and packages
for every variant is wasted work.

Enabled by default (`openwrt_use_imagebuilder: true`), the build happens in
two stages:

```
Device 1
  ├── seed  (1 full build, superset of the variants)             ~30-60 min
  │     └── produces openwrt-imagebuilder-*.tar.zst + package repo
  └── per variant: make image from the ImageBuilder                ~1-3 min
```

With basilicata's current matrix (2 VPN × 2 CP = 4 variants/device), this
goes from 4 full builds down to 1 + 4 assemblies.

From Jenkins: the `USE_IMAGEBUILDER` parameter. From the command line:

```bash
ansible-playbook playbooks/build_all.yml -e openwrt_use_imagebuilder=true
```

**One seed per device.** This assumes all engines in `openwrt_cp_engines` can
be built together, which holds for uspot, the only remaining engine. An
engine that forced incompatible build choices (as coova-chilli used to,
requiring firewall3 + legacy iptables against firewall4 + nftables) would
again require a separate seed per engine.

**Cache and `openwrt_ib_force_seed`.** ImageBuilders are kept in
`build/imagebuilder/<version>/<org>/<device>/` and survive the post-build
cleanup, but **`openwrt_ib_force_seed` defaults to `true`**, so the seed is
always rebuilt anyway.

Why: the cache key is `version/org/device` and doesn't account for the
*content* of the configuration. If `base.config`, a device `.config`, or the
feeds change, a build with caching enabled would reuse an ImageBuilder built
with the old configuration and produce firmware with the wrong packages,
with no error at all. Since builds happen rarely and almost always for a new
OpenWrt version — a case where the cache has to be rebuilt anyway — the safe
default wins over the fast one.

Setting it to `false` (Jenkins: uncheck `IB_FORCE_SEED`) turns hours into
minutes, but should only be done knowing that nothing that ends up in the
seed has changed since the last build.

**Variant composition.** `roles/ninux_build_openwrt/files/ib_packages.py`
translates the repo's `.config`/`.ext` files into the `PACKAGES` list for
`make image`, so the composition stays defined in a single place. It
distinguishes explicit removals (`# CONFIG_PACKAGE_x is not set`: deliberate,
always applied) from implicit ones (packages from an extension not used in
this variant), which are filtered against the target's default packages so
base components aren't accidentally dropped.

The produced file names are identical to those from the normal path: GitHub
releases and OpenWISP uploads don't change.

> Experimental path, `false` by default. If an assembly fails, the prime
> suspect is an implicit removal that dropped a dependency: the log shows the
> full `PACKAGES` list right before `make image`.

### Proxmox LXC and tmpfs

```bash
# Proxmox host
echo "features: nesting=1" >> /etc/pve/lxc/<CTID>.conf
pct restart <CTID>
```

---

## OpenWISP Firmware Upgrader

### Configuration

In `ninux.yml`:

```yaml
openwisp_upload_enabled: true
openwisp_url: "https://openwisp.ninux-nnxx.it"
openwisp_org_slug: "default"
openwisp_org_id: !vault |
      $ANSIBLE_VAULT;1.1;AES256
      <encrypted UUID>
openwisp_trigger_upgrade: false   # true = trigger automatic upgrade

openwisp_replace_build: true      # same version = build replaced
openwisp_keep_versions: 3         # OpenWrt versions to keep (0 = keep everything)

openwisp_orgs:
  basilicata:
    controller_url: "https://openwisp.ninux-nnxx.it"
    management_interface: "wg0"
    shared_secret: !vault |
          $ANSIBLE_VAULT;1.1;AES256
          <encrypted string>
    api_token: !vault |
          $ANSIBLE_VAULT;1.1;AES256
          <encrypted API token>
```

### Replacement and retention

On OpenWISP there is **one category per device** (`Ninux Basilicata -
x86_64`) and inside it **one build per variant** (`v25.12.5-x86_64-VPN-WG`).
The build version includes the OpenWrt version, so builds pile up with every
new tag.

- **`openwisp_replace_build: true`** — if you rebuild the *same* OpenWrt
  version, the existing build is deleted and recreated. This is needed:
  reusing it, the image upload would respond `400` (duplicate) and the
  **old** firmware would stay on the controller.
- **`openwisp_keep_versions: 3`** — after uploading, keeps only the builds
  for the 3 most recent OpenWrt versions per device, deleting the older ones
  (images are removed in cascade). Retention is reasoned per *version*, not
  per single build: all VPN/CP variants of the same version stay together.
  `0` disables deletion.

### Flow

```
Build → artifacts.yml → openwisp_upload.yml
  1. Bearer token from api_token (no login, avoids rate limiting)
  2. Resolve the organization UUID from ninux.yml
  3. Find/create the Category (org + device target)
  4. Create the Build (version-target-VPN-CP)
  5. Upload the sysupgrade image (type = filename without the openwrt- prefix)
  6. (optional) Batch upgrade
```

A failed upload does **not** fail the build: the variant ends up in
`output/.openwisp-upload-failed` with the HTTP code and the controller's
response, and Jenkins marks the build UNSTABLE (yellow).

### Boards not recognized by the controller (upload rejected with 400)

The image's `type` field must be one the controller knows about (its
hardware map). If the board is missing — or OpenWrt changed its filename —
the upload responds `400` and the firmware **is not uploaded**: the build
stays empty on OpenWISP even if Jenkins shows all green.

This happened with the basilicata devices: out of 6, only `x86_64` matched.
The controller knew `gl-mt300n-v2` (old name, today `glinet_gl-mt300n-v2`),
expected `sysupgrade.img` for the Linksys (today `.bin`), and didn't know
about the TOTOLINK X5000R, TP-Link C2600 or Zyxel NWA50AX Pro at all.

This is fixed **on the controller**, by adding the missing boards to
OpenWISP's `settings.py`:

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

Then restart OpenWISP. The values in `boards` must match the model reported
by the registered devices (admin → Devices → *Hardware/Board* column): if an
upgrade doesn't start even though the image was uploaded, this field not
matching is almost always the reason. To check which `type` values the
controller accepts:

```bash
curl -s -X OPTIONS -H "Authorization: Bearer $TOKEN" \
  https://openwisp.ninux-nnxx.it/api/v1/firmware-upgrader/build/<build-id>/image/ \
  | python3 -c "import json,sys; [print(c['value']) for c in json.load(sys.stdin)['actions']['POST']['type']['choices']]"
```

**On the repo side**, the `type` sent on upload is no longer derived from the
filename, but taken from `openwisp_image_type_map` (`config/build.yml`),
which maps each `openwrt_target` to the key the controller expects:

```yaml
openwisp_image_type_map:
  glinet_gl-mt300n-v2: "ramips-mt76x8-gl-mt300n-v2-squashfs-sysupgrade.bin"
  linksys_wrt3200acm: "mvebu-cortexa9-linksys_wrt3200acm-squashfs-sysupgrade.img"
  x86_64: "x86-64-generic-squashfs-combined-efi.img.gz"
  totolink_X5000R: "ramips-mt7621-totolink_x5000r-squashfs-sysupgrade.bin"
  tplink_c2600: "ipq806x-generic-tplink_c2600-squashfs-sysupgrade.bin"
  zyxel_nwa50ax-pro: "mediatek-filogic-zyxel_nwa50ax-pro-squashfs-sysupgrade.bin"
```

The first three use OpenWISP's native keys; the last three exist only
thanks to `OPENWISP_CUSTOM_OPENWRT_IMAGES` on the controller (the `openwisp2`
playbook): the `type` on both sides must stay identical. A target missing
from the map is skipped on upload and noted in
`output/.openwisp-unsupported` (the build still shows green).

---

## GitHub Release

After each build, firmware can be published as a GitHub release, making it
directly downloadable from the repository's Releases page.

### Prerequisites

**1. Personal Access Token (PAT) on GitHub**

Go to `https://github.com/settings/tokens` → **Generate new token (fine-grained)**:

| Field | Value |
|-------|-------|
| Repository access | `ansible-ninux-openwrt` only |
| Contents | **Read and write** |
| Metadata | Read (required) |

**2. Jenkins credential**

Go to **Manage Jenkins → Credentials → System → Global → Add Credentials**:

| Field | Value |
|-------|-------|
| Kind | Secret text |
| Secret | the GitHub token |
| ID | `github-release-token` |

### Configuration in ninux.yml

```yaml
github_release_enabled: true
github_repo: "mikysal78/ansible-ninux-openwrt"
github_prerelease: true           # false for official releases
github_release_include_sha256: true
```

### Release structure

Each release is created with the tag `<version>-<org>-build<N>`, e.g.
`v25.12.5-default-build42`. Assets are uploaded with names reflecting their
path:

```
Standard_VPN-NO_x86_64_openwrt-x86-64-generic-squashfs-combined-efi.img.gz
Standard_VPN-ZeroTier_x86_64_openwrt-x86-64-generic-squashfs-combined-efi.img.gz
CaptivePortal_VPN-WireGuard_glinet_gl-mt300n-v2_openwrt-...-squashfs-sysupgrade.bin
...
```

### Enabling it from Jenkins

Set `github_release_enabled: true` in `ninux.yml` to always enable it, or use
the **`GITHUB_RELEASE`** parameter when launching the job: `config` follows
ninux.yml, `on` and `off` force it.

> `GITHUB_RELEASE` and `OPENWISP_UPLOAD` used to be booleans, but a boolean
> can't say "no": with `github_release_enabled: true` in `ninux.yml`, the
> release would still be published even with the parameter unchecked. They
> became three-state for this reason — a test build once published firmware
> to the public repo and the controller while believing it wasn't.

---

## Structure of the produced firmware

```
output/
└── v25.12.5/
    └── default/
        ├── Standard/
        │   ├── VPN-NONE/glinet_gl-mt300n-v2/
        │   ├── VPN-ZeroTier/glinet_gl-mt300n-v2/
        │   ├── VPN-WireGuard/glinet_gl-mt300n-v2/
        │   └── VPN-Dual/glinet_gl-mt300n-v2/
        └── CaptivePortal-uspot/     <- uspot (separate build)
            └── VPN-*/...
```

---

## Tests and CI

On every push and pull request, GitHub Actions (`.github/workflows/ci.yml`)
runs lint and tests. **The actual compilation stays on Jenkins**: building
OpenWrt firmware from source takes hours and tens of GB, well beyond what a
GitHub runner can handle (14 GB of disk). What the CI checks is everything
else — which is where the real bugs came from: which packages end up in
which variant, which config files make it into the image, and what happens
on the OpenWISP controller.

### What runs

| Job | What it does |
|-----|---------------|
| `lint` | `yamllint`, `ansible-lint`, `--syntax-check` on every playbook, `shellcheck` on the uci-defaults and setup scripts |
| `test` | Molecule: runs the role **for real** against a simulated device, then verifies the firmware and the controller. Plus a check that an example org isn't buildable |

### How the simulation works

The role runs in full (overlay, feeds, `.config`, artifacts, upload): only
the two pieces impossible to have in CI are faked.

- **OpenWrt toolchain** (`molecule/default/files/openwrt-stub/`) — a
  `Makefile` that compiles nothing but writes **the assembled `.config`
  inside the fake firmware**. This way the tests verify which packages would
  really have ended up in the image, without compiling.
- **OpenWISP controller** (`molecule/default/files/mock_openwisp.py`) — a
  mock listening on `127.0.0.1:8099` that implements the endpoints the role
  uses, already pre-populated with 4 existing versions. It also reproduces
  the `400` on a duplicate image, which is why builds need to be replaced.

Three variants of a single device (`glinet_gl-mt300n-v2`) get built: no VPN
without a portal, basilicata's real case (**uspot + WireGuard with VXLAN**),
and **Dual + uspot**. The rules being checked are the project's own:

- captive portal and VPN config files end up **only** in the variant that
  uses them (in the past, `/etc/config/chilli` ended up in *every* image);
- the firmware has no network uci-defaults nor autoip packages: the mesh and
  the portal are configured by OpenWISP through its templates;
- the controller keeps **only the last 3 versions**, and rebuilding the same
  version **replaces** it instead of leaving the old firmware online.

The last one matters the most: a bug in retention would wipe the firmware
history off the controller. The test catches it.

### Running them locally

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

molecule test        # full tests (~1 minute, no Docker, no network)
ansible-lint         # playbook lint
yamllint .
```

Molecule uses the `default` driver: it runs on localhost, no Docker needed.
The tests' working directory lives in Molecule's ephemeral directory, the
repo itself is never touched.

To add a variant to the tests, just add it to `t_variants` in
`molecule/default/vars/main.yml` and the matching expectations in
`molecule/default/verify.yml`.

---

## Troubleshooting

### `openwrt_work_dir is undefined`

Make sure you're using the playbooks from `playbooks/` — they load
`ninux.yml` via `vars_files`. Don't call the role directly without loading
the variables.

### `shared_secret is undefined` or firmware without `/etc/config/openwisp`

Check that the org is defined in `openwisp_orgs` in `ninux.yml` with all
three fields (`controller_url`, `management_interface`, `shared_secret`). If
`shared_secret` is missing or can't be decrypted, the build continues
without generating the file and logs a warning.

### `Decryption failed` on `!vault` fields

The `--vault-password-file` doesn't match the password used during
`encrypt_string`. Check that `/var/lib/jenkins/.vault_pass` holds the
correct password.

### `chown failed: Operation not permitted` on NFS

The tasks don't use `owner` on NFS directories. If it persists, check that
the NFS server exports with `no_root_squash`, or adjust permissions on the
server side.

### Jenkins: `git tool does not exist`

**Manage Jenkins → Tools → Git installations**:
- Name: `Default`
- Path: `git`

### Jenkins: timeout on long builds

In **Manage Jenkins → Configure System**, set Build Timeout to 240+ minutes.

### Low ccache hit rate

```bash
CCACHE_DIR=/var/cache/openwrt-ccache ccache --show-stats
```

Hit rate under 50% after the second build: check that `CCACHE_DIR` is the
same across jobs, and that `nesting=1` is enabled (for tmpfs).

### tmpfs: `mount: permission denied` in LXC

Enable `nesting=1` in the container's Proxmox config (see the Performance
section).

---

## License

GPL-3.0
