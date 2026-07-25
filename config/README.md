# config/

Contiene i file di configurazione OpenWrt per tutte le organizzazioni Ninux.

## Struttura

```
config/
├── base.config                          # Pacchetti comuni a tutti i target
├── zerotier.ext                         # Estensione ZeroTier
├── wireguard.ext                        # Estensione WireGuard
├── organizations/
│   └── <org>/
│       └── <device>.config              # Config per device specifico
│           (nome = valore di openwrt_target)
└── root_files/
    └── <org>/                           # Overlay filesystem per org
        └── etc/
            ├── config/                  # UCI config files
            └── uci-defaults/            # Script eseguiti al primo boot
```

## Aggiungere un nuovo device

1. Genera il `.config` con `make menuconfig` nella buildroot OpenWrt
2. Salvalo in `config/organizations/<org>/<device>.config`
3. Usalo con `-e openwrt_target=<device>`

## Aggiungere una nuova organizzazione

1. Crea `config/organizations/<nuova_org>/`
2. Crea `config/root_files/<nuova_org>/`
3. Usa `-e openwrt_org=<nuova_org>`
