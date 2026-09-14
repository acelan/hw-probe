# hw-probe

A script to check which Linux kernel versions and modules support specific
PCI/USB/ACPI hardware IDs.

It can generate its own support database from a local kernel source tree, or
download a pre-generated one from this repository.

## Features

- Query the database for a hardware ID (PCI/USB vendor:device or full
  modalias) to see which kernel versions/modules support it.
- Generate a database from a local kernel git tree (`db gen`).
- Add/remove individual kernel entries in the database (`db add` / `db
  remove`).
- Self-update the script and database from GitHub (`update`).

## Usage

```
# Query for a device (will auto-download DB if missing)
./hw-probe.py query "8086:51ab"

# Generate a database for a specific kernel
./hw-probe.py db gen 6.5.0-rc1-custom

# Add a kernel to the database (automatically syncs hw-support.db and .md5 to ./)
./hw-probe.py db add 6.5.0-rc1-custom

# Force an update of the script and database from GitHub
./hw-probe.py update
```

By default the database is stored at `~/.local/share/hw-probe/hw-support.db`
and the kernel source tree is expected at `~/workspace/linux`; both can be
overridden with `--db-file` and `--kernel-source`. When running `db gen`,
`db add`, or `db remove`, the updated database and its `.md5` file are
automatically copied to the current directory (`./`) for convenient git
commits (can be disabled with `--no-sync-cwd`).

## Updating

`hw-probe.py update` downloads the latest `hw-probe.py` and `hw-support.db`
(plus their `.md5` checksums) from the `main` branch of this repository
(https://github.com/acelan/hw-probe) and updates the local copies if they've
changed.

## Requirements

- Python 3
- the `requests` Python package (only needed for `update`)

## License

See [LICENSE](LICENSE).
