# Tiled on Synology for AFL

This deployment runs Tiled on the Synology NAS and stores its SQLite catalog
and data files on the NAS. The current AFL installation connects directly over
HTTP to a fixed NAS IP and port. Access to that port is restricted in the DSM
firewall to the fixed IP of the AFL computer.

Determine these values for the installation before starting:

| Setting | Placeholder used below |
|---|---|
| Fixed NAS address | `NAS_IP` |
| NAS interface carrying that address | `NAS_INTERFACE` |
| Fixed source address of the AFL computer | `AFL_COMPUTER_IP` |
| Tiled port | `8000/tcp` |
| Synology `afl-tiled` UID/GID | `AFL_TILED_UID:AFL_TILED_GID` |
| Tiled URL | `http://NAS_IP:8000` |

On the NAS, use `ip -4 address` to identify `NAS_IP` and `NAS_INTERFACE`. From
the AFL computer, use `ip route get NAS_IP` and record the address following
`src` as `AFL_COMPUTER_IP`. Reserve both addresses in DHCP or otherwise make
them static. Replace the uppercase placeholders in the examples below; they
are not literal configuration values.

> **Security:** This connection is plain HTTP. The API key and scientific data
> are not encrypted in transit. Use this arrangement only on the trusted lab
> network, allow port 8000 from the AFL computer only, and never forward the
> port from the Internet. Use a VPN if the network is not trusted.

This setup does not use a DSM Login Portal application or a reverse-proxy
rule. After logging in to DSM, the relevant controls are under **Control Panel
> Security > Firewall**.

## 1. Prepare DSM

Install **Container Manager** and create a dedicated, non-admin DSM user named
`afl-tiled`. Confirm its IDs from a NAS shell:

```sh
id afl-tiled
```

Record the reported numeric UID as `AFL_TILED_UID` and GID as
`AFL_TILED_GID`.

Create the persistent directories as NAS root:

```sh
install -d -o AFL_TILED_UID -g AFL_TILED_GID -m 0750 /volume1/docker/afl-tiled/catalog
install -d -o AFL_TILED_UID -g AFL_TILED_GID -m 0750 /volume1/docker/afl-tiled/data
install -d -o AFL_TILED_UID -g AFL_TILED_GID -m 0700 /volume1/docker/afl-tiled-secrets
```

Keep the SQLite catalog on a local Synology volume, not an SMB or NFS mount.
Run only one Tiled container against this catalog.

## 2. Create the API key

Generate the Tiled service credential on the NAS:

```sh
umask 077
openssl rand -hex 32 > /volume1/docker/afl-tiled-secrets/tiled_api_key
chown AFL_TILED_UID:AFL_TILED_GID /volume1/docker/afl-tiled-secrets/tiled_api_key
chmod 0400 /volume1/docker/afl-tiled-secrets/tiled_api_key
```

File-based Compose secrets retain host permissions on DSM, so the container's
runtime UID must be able to read this file. Do not put the key in the image,
Compose file, Git, or a support message, and do not paste the literal key into
shell commands. If it appears in logs, rotate it before connecting AFL.

## 3. Configure direct IP access

Copy `.env.example` to `.env` in the NAS project directory and set:

```dotenv
TILED_DATA_ROOT=/volume1/docker/afl-tiled
TILED_SECRET_FILE=/volume1/docker/afl-tiled-secrets/tiled_api_key
TILED_UID=AFL_TILED_UID
TILED_GID=AFL_TILED_GID
TILED_BIND_ADDRESS=NAS_IP
TILED_PORT=8000
```

Do not use `0.0.0.0` as `TILED_BIND_ADDRESS`. Tiled listens on `0.0.0.0`
*inside* its container, but Docker should publish the port only on the NAS's
specific `NAS_INTERFACE` address.

Make sure the copied deployment files are readable by the image build:

```sh
chmod 0644 Dockerfile compose.yaml config.yml.template
chmod 0755 entrypoint.sh
```

The Dockerfile deliberately makes `/opt/tiled/config.yml.template` readable by
the non-root runtime user. Without that permission, the container repeatedly
restarts with `Permission denied`.

## 4. Allow only the AFL computer in DSM

Configure the two port rules after logging in to DSM:

1. Open **Control Panel > Security > Firewall**.
2. Enable the firewall if it is not already enabled.
3. Select the firewall profile used by `NAS_INTERFACE` (`NAS_IP`) and click
   **Edit Rules**.
4. Before restricting unmatched traffic, confirm that the profile already
   permits access to the DSM web interface from the administration computer.
   Preserve any required rules for DSM HTTPS and SSH so that you do not lock
   yourself out.
5. Click **Create** to add the Tiled allow rule.
6. Under **Ports**, choose **Custom**, select protocol **TCP**, and enter `8000`
   as the destination port.
7. Under **Source IP**, choose **Specific IP** and enter the single host
   `AFL_COMPUTER_IP`. If DSM requests a subnet mask, use `255.255.255.255` so
   the rule matches only that computer.
8. Set **Action** to **Allow** and save the rule.
9. Create a second custom rule for TCP destination port `8000`. Set its source
   to **All** and its action to **Deny**.
10. Move the specific-IP **Allow** rule above the all-sources **Deny** rule,
    then click **Apply**.

The resulting order should be:

| Order | Source | Protocol/port | Action |
|---:|---|---|---|
| 1 | `AFL_COMPUTER_IP` only | TCP `8000` | Allow |
| 2 | All | TCP `8000` | Deny |

DSM processes rules from top to bottom. If the deny rule is first, it also
blocks the AFL computer. If the profile already denies all unmatched traffic,
the explicit second rule is optional, but the specific-IP allow rule is still
required.

Do not add a Login Portal or reverse-proxy entry for Tiled. Also confirm there
is no router port-forward or UPnP mapping for port `8000`. If AFL moves to
another computer or its address changes, update the source IP in the allow
rule; changing the NAS bind address alone is not enough.

After starting Tiled, verify both sides of the rule:

- From `AFL_COMPUTER_IP`, `nc -vz -w 5 NAS_IP 8000` must succeed.
- From a computer not covered by the allow rule, the same connection should
  time out or be rejected. Receiving an HTTP response means port 8000 is still
  reachable and the firewall rule or its ordering needs correction.

## 5. Validate, build, and start

From `/volume1/docker/afl-tiled-project` on the NAS:

```sh
docker compose config
```

Inspect the rendered `ports` section. It must resolve to approximately:

```yaml
host_ip: NAS_IP
published: "8000"
target: 8000
```

Do not continue if it still shows `127.0.0.1`. Correct `.env`, then start the
service:

```sh
docker compose build --pull
docker compose up -d --force-recreate
docker compose ps
```

After the startup period, the expected port and state are:

```text
Up ... (healthy)   NAS_IP:8000->8000/tcp
```

If it remains unhealthy, inspect both application and health-check output:

```sh
docker compose logs --tail=100 --no-color tiled
docker inspect \
  --format='{{range .State.Health.Log}}{{println .ExitCode .Output}}{{end}}' \
  afl-tiled-tiled-1
```

The supported authentication header is `Authorization: Apikey ...`. The old
`X-Tiled-Api-Key` examples are incorrect for the pinned Tiled version and cause
anonymous `401` health checks.

## 6. Test on the NAS

```sh
curl --fail --silent --show-error \
  -H "Authorization: Apikey $(cat /volume1/docker/afl-tiled-secrets/tiled_api_key)" \
  http://NAS_IP:8000/api/v1/metadata/
```

A JSON response confirms that Tiled and its API key are working.

## 7. Copy the key and test from the allowed AFL computer

Before testing authenticated access, copy the current API key from the NAS to
the AFL computer. First prepare its destination on the AFL computer:

```sh
mkdir -p ~/.afl
chmod 0700 ~/.afl
```

Then, from an administrative shell on the NAS, copy the key using the AFL
computer's SSH username and fixed IP:

```sh
scp /volume1/docker/afl-tiled-secrets/tiled_api_key \
  AFL_USERNAME@AFL_COMPUTER_IP:.afl/tiled_api_key
```

Enter the AFL computer account password when prompted. Back on the AFL
computer, restrict the copied file:

```sh
chmod 0600 ~/.afl/tiled_api_key
```

Never paste the key into the terminal command itself or into documentation.
Repeat this copy whenever the NAS key is rotated.

Now verify the port:

```sh
nc -vz -w 5 NAS_IP 8000
```

Then authenticate using the copied key:

```sh
curl --fail --silent --show-error \
  -H "Authorization: Apikey $(cat ~/.afl/tiled_api_key)" \
  http://NAS_IP:8000/api/v1/metadata/
```

JSON confirms the network and credential both work. Interpret failures as:

- Timeout or refused connection: check the `.env` bind address, rendered
  Compose configuration, NAS route, and DSM firewall source IP.
- `401 Unauthorized`: the entered key is stale or incorrect. Compare key
  fingerprints rather than printing either key.
- A successful request from another computer: the firewall is too permissive.

## 8. Connect AFL

Set these fields in the newest entry of `~/.afl/config.json` on each AFL server
that reads or writes data:

```json
{
  "tiled_server": "http://NAS_IP:8000",
  "tiled_api_key": "REPLACE_WITH_THE_CURRENT_SERVICE_KEY"
}
```

Protect the file and restart the AFL services:

```sh
chmod 0600 ~/.afl/config.json
```

For Andon, select the external Tiled YAML profile. Its connection fields are:

```yaml
uri: "http://NAS_IP:8000"
api_key: "REPLACE_WITH_THE_CURRENT_SERVICE_KEY"
structure_clients: "dask"
```

Because this YAML contains the service key, keep it out of Git and set mode
`0600`. The profile may also contain Andon's `management` section for remote
Docker Compose lifecycle controls.

If Tiled is unreachable during an AFL write, `DataTiled` writes a JSON fallback
under `~/.afl/json-backup` on that AFL host. These files are not automatically
replayed into Tiled, so monitor and back up this directory.

## Backup and recovery

The catalog database and `/data` directory form one logical dataset. Back them
up together. For an application-consistent snapshot or Hyper Backup job:

```sh
docker compose stop tiled
# Take the Btrfs snapshot or run the configured Hyper Backup task here.
docker compose start tiled
```

Keep an encrypted off-NAS backup and periodically test restoring both
directories to a separate path. Never run two Tiled containers against the
same SQLite catalog.

## Updates

Back up first. Tiled `0.2.4` is pinned to match the current AFL Docker client.
Test newer server/client versions against a restored copy before changing the
build argument.
