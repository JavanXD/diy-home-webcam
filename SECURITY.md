# Security

## Report a problem

Open a private GitHub security advisory on this repository, or email **mail@javan.de**. Do not file a public issue that includes live hostnames, tokens, or unpublished images.

## How this appliance is meant to be exposed

| Surface | Who should reach it |
|---------|---------------------|
| `:8080` camera and `:8090` pipeline | Your LAN only. There is no login on purpose: the home network is the trust boundary. |
| Originals and `visibility: private` variants | LAN only. They are not uploaded. |
| Public JPEG on R2 / the Worker | Anyone with the URL. |

Do not port-forward `:8080` or `:8090` to the internet. The maintenance switch and the variants editor can change what the public JPEG shows.

**DIY threat model, SSH, setup AP, and hardening checklist:** [docs/diy/SECURITY.md](docs/diy/SECURITY.md).

## Secrets

R2 credentials belong in `/etc/webcam-pipeline/env` on the Pi (mode `640`, owner `root`, group `webcam`). The template is [`examples/pi/r2.env`](examples/pi/r2.env). Never commit keys, SSH private keys, or Wi-Fi PSKs. The Setup UI reports whether a secret is set; it never returns the secret value.

The optional first-boot setup AP (`Webcam-Setup`) uses a **published temporary WPA2 password** (`webcam-setup` in the DIY docs). Anyone nearby who knows it can open Setup and change Wi-Fi. It starts only when no home Wi-Fi profile exists; a successful Setup join tears it down and writes `/var/lib/webcam-pipeline/setup-ap.disabled`. Operator forever-off: `/etc/webcam-pipeline/setup-ap.disabled`. Flashable images do not bake R2 keys.

## Privacy masks

Public variants ship with placeholder rectangles. Tune them on a real frame in the variants UI before you enable publish. A mask that is slightly too small still publishes the rest of the frame.
