#!/usr/bin/env python3
"""Calcola la lista PACKAGES da passare a `make image` dell'ImageBuilder.

L'ImageBuilder non compila nulla: installa pacchetti gia' presenti nel suo
repository. La selezione va quindi espressa come lista di nomi, non come
simboli kconfig. Questo script traduce i .config/.ext del repo (unica fonte
di verita' della composizione delle varianti) in quella lista.

  --add FILE...    estensioni e config di QUESTA variante
  --del FILE...    estensioni compilate nel seed ma non volute in questa
                   variante (es. zerotier.ext in una variante WireGuard)
  --seed FILE      .config del seed DOPO `make defconfig`
  --info FILE      output di `make info` dell'ImageBuilder
  --profile NAME   profilo device, per leggere da --info i pacchetti di
                   default del target

=y e =m NON sono la stessa cosa: =y installa il pacchetto nell'immagine, =m lo
compila soltanto, rendendolo disponibile ma fuori dal firmware. Trattarli allo
stesso modo rompe l'immagine. Caso reale: base.config chiede sia
wpad-mesh-wolfssl sia wpad-openssl, ma `make defconfig` risolve il conflitto
lasciando =y solo il primo e degradando l'altro a =m. Installandoli entrambi
apk si ferma con "unable to select packages".

Il .config del seed dopo defconfig e' quindi l'autorita' su cosa la build da
sorgente installerebbe davvero: le richieste dei file --add valgono solo se li'
risultano =y.

Da quello discendono anche le rimozioni. Sono di tre tipi:

  esplicite  `# CONFIG_PACKAGE_x is not set` in un file --add: scelta
             deliberata di chi ha scritto il .ext, vale anche contro un
             pacchetto di default (era il caso di chilli.ext, che disattivava
             firewall4 perche' coova-chilli richiedeva iptables legacy).

  implicite  pacchetti di un'estensione non usata in questa variante. Vanno
             filtrate contro i default del target: un'estensione elenca anche
             dipendenze che sono gia' base OpenWrt (uspot.ext tira dentro
             firewall4, uhttpd e ucode) e negando l'estensione intera si
             produrrebbe un'immagine senza firewall.

  di default pacchetti che l'ImageBuilder installerebbe da solo ma che il seed
             marca =m o disattivati: la build da sorgente non li mette
             nell'immagine, quindi vanno tolti. E' cosi' che sparisce
             wpad-basic-mbedtls, che altrimenti confligge con wpad-mesh-wolfssl.

--add vince su tutto: un pacchetto richiesto dalla variante resta installato.
"""

import argparse
import re
import sys

# CONFIG_PACKAGE_<nome>=y|m  oppure  # CONFIG_PACKAGE_<nome> is not set
RE_SET = re.compile(r"^CONFIG_PACKAGE_([^=\s]+)=([ym])\s*$")
RE_UNSET = re.compile(r"^#\s*CONFIG_PACKAGE_([^=\s]+) is not set\s*$")

# I nomi dei pacchetti OpenWrt sono minuscoli. Sotto CONFIG_PACKAGE_ vivono
# pero' anche opzioni di build interne a un pacchetto (CONFIG_PACKAGE_MAC80211_
# DEBUGFS, CONFIG_PACKAGE_MAC80211_MESH): passarle a `make image` come nomi di
# pacchetto lo farebbe fallire. Si riconoscono dal maiuscolo.
RE_PKGNAME = re.compile(r"^[a-z0-9][a-z0-9._+-]*$")


def parse_config(path):
    """Stato di ogni pacchetto in un .config o .ext: 'y', 'm' o 'n'."""
    state = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = RE_SET.match(line)
            if m:
                state[m.group(1)] = m.group(2)
                continue
            m = RE_UNSET.match(line)
            if m:
                state[m.group(1)] = "n"
    return state


def picked(state, want):
    return {p for p, s in state.items() if s == want}


def parse_info(path, profile):
    """Pacchetti installati di default dall'ImageBuilder per questo profilo.

    Formato di `make info`:

        Default Packages: base-files ca-bundle dropbear ...
        Available Profiles:
        <profilo>:
            <descrizione>
            Packages: kmod-usb3 ...
    """
    defaults = set()
    in_profile = False
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("Default Packages:"):
                defaults |= set(line.split(":", 1)[1].split())
                continue
            if re.match(r"^\S+:\s*$", line):
                in_profile = line.split(":", 1)[0] == profile
                continue
            if in_profile and line.strip().startswith("Packages:"):
                defaults |= set(line.split(":", 1)[1].split())
    return defaults


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--add", nargs="*", default=[], metavar="FILE")
    ap.add_argument("--del", nargs="*", default=[], metavar="FILE", dest="delete")
    ap.add_argument("--seed", metavar="FILE", required=True)
    ap.add_argument("--info", metavar="FILE")
    ap.add_argument("--profile", metavar="NAME")
    args = ap.parse_args()

    seed = parse_config(args.seed)
    seed_installed = picked(seed, "y")

    wanted, rm_explicit, from_del = set(), set(), set()
    for path in args.add:
        st = parse_config(path)
        wanted |= picked(st, "y")
        rm_explicit |= picked(st, "n")
    for path in args.delete:
        from_del |= picked(parse_config(path), "y")

    # Solo cio' che la build da sorgente installerebbe davvero.
    install = wanted & seed_installed
    dropped = sorted(p for p in wanted - seed_installed if RE_PKGNAME.match(p))

    rm_explicit -= install
    rm_implicit = from_del - install - rm_explicit
    rm_default = set()

    if args.info and args.profile:
        defaults = parse_info(args.info, args.profile)
        # Un default che il seed compila senza installarlo (=m) o disattiva non
        # deve finire nell'immagine: e' cosi' che si evita il conflitto wpad.
        rm_default = {p for p in defaults if seed.get(p) in ("m", "n")}
        # Le rimozioni implicite invece non devono toccare i default: sono
        # dipendenze condivise, non roba dell'estensione.
        spared = sorted(rm_implicit & defaults)
        rm_implicit -= defaults
        if spared:
            print("ib_packages: non rimossi (default del target): " + " ".join(spared),
                  file=sys.stderr)

    remove = (rm_explicit | rm_implicit | rm_default) - install
    install = {p for p in install if RE_PKGNAME.match(p)}
    remove = {p for p in remove if RE_PKGNAME.match(p) and p in seed}

    if dropped:
        print("ib_packages: non installati (nel seed non sono =y): " + " ".join(dropped),
              file=sys.stderr)
    if rm_default:
        print("ib_packages: default del target rimossi (nel seed =m/off): "
              + " ".join(sorted(rm_default)), file=sys.stderr)

    print(" ".join(sorted(install) + ["-" + p for p in sorted(remove)]))


if __name__ == "__main__":
    main()
