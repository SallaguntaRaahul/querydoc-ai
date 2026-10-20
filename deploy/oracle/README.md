# Deploy QueryDoc AI for free on Oracle Cloud

Oracle's **Always Free** tier includes an ARM virtual machine with up to 4 cores and
24 GB of RAM at no cost, with no time limit. That is enough to run QueryDoc AI with the
Qwen2.5-1.5B model on CPU for real users: search well under a second, generated answers in
roughly 20–60 seconds.

You do the account and VM steps (about 15 minutes). The setup script does the rest.

## 1. Create the account

1. Go to <https://www.oracle.com/cloud/free/> and click **Start for free**.
2. Fill in your details. Pick a **home region** close to your users. It cannot be changed
   later, and larger regions (e.g. US East Ashburn, Frankfurt) more often have free ARM capacity.
3. Add a credit/debit card. It is used only to verify your identity; Always Free resources
   are never charged. Stay on the **Free Tier** account type, which cannot bill you.
4. Wait for the "account is ready" email (minutes, sometimes longer).

## 2. Create the virtual machine

In the Oracle Cloud console: **☰ → Compute → Instances → Create instance**.

| Setting | Choose |
|---|---|
| Name | `querydoc-ai` |
| Image | **Change image → Ubuntu → Canonical Ubuntu 24.04** (not "Minimal") |
| Shape | **Change shape → Ampere → VM.Standard.A1.Flex**, set **4 OCPUs** and **24 GB** memory |
| Networking | Keep "Create new virtual cloud network" and "Create new public subnet"; **Assign a public IPv4 address: Yes** |
| SSH keys | **Paste public keys**, then paste the key you were given (one line starting with `ssh-ed25519`) |
| Boot volume | Default is fine (~47 GB); up to 200 GB total is free |

Click **Create**. When the state is **Running**, copy the **Public IP address**.

> **"Out of capacity for shape VM.Standard.A1.Flex"?** Free ARM capacity is limited. Try another
> *Availability domain* in the Placement section, or try again later (early morning often works).

## 3. Open the web ports

The VM is created behind a cloud firewall that only allows SSH.

1. On the instance page, click the **subnet** link under *Primary VNIC*.
2. Open **Security** (or *Security Lists*) → **Default Security List**.
3. **Add Ingress Rules** twice:
   - Source CIDR `0.0.0.0/0`, IP protocol **TCP**, destination port **80**
   - Source CIDR `0.0.0.0/0`, IP protocol **TCP**, destination port **443**

## 4. Install QueryDoc AI

Over SSH on the VM (`ssh ubuntu@<public-ip>`):

```bash
curl -fsSL https://raw.githubusercontent.com/SallaguntaRaahul/querydoc-ai/master/deploy/oracle/setup.sh -o setup.sh
bash setup.sh you@example.com      # optional: the account allowed to change server settings
```

The script installs Docker, opens ports 80/443 in the VM's own firewall, builds the image (the
first build downloads ~4 GB of models and takes 15–30 minutes) and starts the app behind Caddy,
which gets a free HTTPS certificate. Without a domain name, the address is
`https://<ip-with-dashes>.sslip.io`, e.g. `https://203-0-113-7.sslip.io`.

To update later, run `bash setup.sh` again. Data lives in the Docker volume `querydoc-data`
and survives restarts and rebuilds.

## Good to know

- Oracle may reclaim Always Free VMs that stay almost completely idle for 7 days. The loaded
  model keeps memory use well above Oracle's idle threshold, but check the console occasionally.
- To use your own domain, point an `A` record at the VM's IP, set `DOMAIN=` in
  `/opt/querydoc-ai/deploy/oracle/.env` and run `bash setup.sh` again.
- Logs: `sudo docker compose -f /opt/querydoc-ai/deploy/oracle/docker-compose.yml logs -f app`
