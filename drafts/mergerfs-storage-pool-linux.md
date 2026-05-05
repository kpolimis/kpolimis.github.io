Title: Building a NAS-Like Storage Pool on Linux Without a NAS: mergerfs + Systemd
Date: 2026-05-11
Category: How-to
Tags: linux, mergerfs, storage, homelab, nas, systemd, fstab, docker, scrutiny
Slug: mergerfs-storage-pool-linux-without-nas
Summary: I run four drives (8TB + 14TB + 14TB + 20TB = 56TB) as a unified storage pool on a Lenovo ThinkCentre M70q using mergerfs and systemd mount units. No dedicated NAS hardware required. Here's the architecture, the configuration, and the gotchas.

---

A NAS (Network Attached Storage) device is the conventional answer to "I have too many drives and I want them to look like one thing." A Synology or QNAP gives you a nice web UI, RAID options, and a proprietary OS managing everything.

I don't have a dedicated NAS. I have a Lenovo ThinkCentre M70q — a tiny PC about the size of a thick paperback book — running Ubuntu 24.04 as my home server. Four drives are plugged into a TerraMaster D6-320 USB enclosure connected to it.

`mergerfs` turns those four independent filesystems into one.

---

## What mergerfs Is (and Isn't)

`mergerfs` is a FUSE-based union filesystem. It takes multiple mount points ("branches") and presents them as a single directory. When you write to `/mnt/unified`, mergerfs decides which underlying drive to actually write to, based on a configurable policy.

What mergerfs is **not**:

- **Not RAID.** If a drive fails, you lose what's on that drive. No redundancy.
- **Not SnapRAID.** No parity. No recovery from drive failure.
- **Not ZFS.** No checksumming, no copy-on-write semantics.

If you need redundancy, you want SnapRAID (or ZFS, or a real RAID card) in addition to mergerfs. I run mergerfs alone because my backup strategy handles redundancy: nightly rsync to a local backup drive plus Restic to a remote destination.

What mergerfs gives you: a unified namespace across drives with different sizes, different filesystems (as long as the OS can mount them), and no wasted space from RAID overhead.

---

## My Storage Topology

| Drive | Mount | Size | Filesystem | Device |
|---|---|---|---|---|
| mercury | `/mnt/mercury` | 7.3TB | ext4 | `/dev/sdb1` |
| venus | `/mnt/venus` | 14.6TB | ext4 | `/dev/sdd` |
| mars | `/mnt/mars` | 14.6TB | ext4 | `/dev/sde` |
| jupiter | `/mnt/jupiter` | 20TB | ext4 | `/dev/sdc` |
| backup-local | `/mnt/backup-local` | 3.6TB | ext4 | `/dev/sda` |
| unified | `/mnt/unified` | 56.5TB | mergerfs | all of the above |

The backup drive is intentionally excluded from the mergerfs pool — it's not part of the working storage, it's the target for local backups.

---

## Step 1: Format and Mount Individual Drives

Before mergerfs can pool the drives, each drive needs to be formatted and given a stable UUID-based mount point.

```bash
# Format (ONLY on new/empty drives — this destroys data)
sudo mkfs.ext4 -L mercury /dev/sdb1
sudo mkfs.ext4 -L venus /dev/sdd
sudo mkfs.ext4 -L mars /dev/sde
sudo mkfs.ext4 -L jupiter /dev/sdc

# Get UUIDs
sudo blkid | grep -E "sdb1|sdc|sdd|sde"
```

Example output:
```
/dev/sdb1: UUID="a1b2c3d4-..." TYPE="ext4" LABEL="mercury"
/dev/sdc:  UUID="e5f6g7h8-..." TYPE="ext4" LABEL="jupiter"
/dev/sdd:  UUID="i9j0k1l2-..." TYPE="ext4" LABEL="venus"
/dev/sde:  UUID="m3n4o5p6-..." TYPE="ext4" LABEL="mars"
```

---

## Step 2: Systemd Mount Units

I use systemd mount units instead of `/etc/fstab` entries because they compose better with Docker containers (which can declare dependencies on specific mounts) and they're easier to debug.

Each drive gets its own unit file. The naming convention is strict: the unit filename must match the mount point path with `/` replaced by `-` and without the leading `-`.

`/etc/systemd/system/mnt-mercury.mount`:
```ini
[Unit]
Description=Mercury - 8TB Storage
After=local-fs-pre.target

[Mount]
What=UUID=a1b2c3d4-e5f6-7890-abcd-ef1234567890
Where=/mnt/mercury
Type=ext4
Options=defaults,noatime,nodiratime

[Install]
WantedBy=multi-user.target
```

The `noatime` option prevents the OS from updating access timestamps on every read, which reduces unnecessary write activity on spinning drives.

Repeat for venus, mars, jupiter, and backup-local with their respective UUIDs.

---

## Step 3: Install mergerfs

```bash
# Ubuntu 24.04
sudo apt install mergerfs

# Verify
mergerfs --version
```

---

## Step 4: The mergerfs Systemd Mount Unit

`/etc/systemd/system/mnt-unified.mount`:
```ini
[Unit]
Description=mergerfs /mnt/unified
After=mnt-mercury.mount mnt-venus.mount mnt-mars.mount mnt-jupiter.mount
Wants=mnt-mercury.mount mnt-venus.mount mnt-mars.mount mnt-jupiter.mount

[Mount]
What=/mnt/mercury:/mnt/venus:/mnt/mars:/mnt/jupiter
Where=/mnt/unified
Type=fuse.mergerfs
Options=defaults,allow_other,use_ino,cache.files=auto-full,category.create=mfs,minfreespace=50G,fsname=mergerfsPool,uid=1000,gid=1000,statfs=sum,direct_io

[Install]
WantedBy=multi-user.target
```

The options are worth explaining:

**`allow_other`** — allows users other than the mounting user to access the filesystem. Required for Docker containers to read/write through the pool.

**`use_ino`** — uses the underlying filesystem's inode numbers rather than generating new ones. Required for `rsync` to work correctly (rsync uses inode numbers to detect hard links). **Only safe when no two branches share a physical disk.** If you have two filesystem branches on the same physical drive (e.g., two partitions), disable `use_ino`.

**`cache.files=auto-full`** — caches file contents aggressively. Good for read-heavy workloads (media streaming). Disable if you have frequent concurrent writes from multiple processes.

**`category.create=mfs`** — "Most Free Space" policy for new file creation. Files are written to whichever branch has the most available space. Keeps drives roughly balanced over time.

**`minfreespace=50G`** — never fill a branch below 50GB free. Prevents a branch from running completely full, which would cause write failures.

**`statfs=sum`** — `df /mnt/unified` reports the sum of all branches. Without this, it reports only the first branch.

**`direct_io`** — bypasses the page cache for I/O through the mergerfs mount. Reduces memory pressure for large media file reads, at the cost of slightly higher CPU usage.

---

## Step 5: Enable and Start

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable all mount units to start on boot
sudo systemctl enable mnt-mercury.mount mnt-venus.mount \
  mnt-mars.mount mnt-jupiter.mount mnt-unified.mount

# Start them
sudo systemctl start mnt-mercury.mount mnt-venus.mount \
  mnt-mars.mount mnt-jupiter.mount mnt-unified.mount

# Verify
df -h | grep -E "unified|mercury|venus|mars|jupiter"
ls /mnt/unified
```

---

## Gotcha: USB Drive Letter Instability

This is the most important operational caveat: USB drives don't have stable device names.

When drives are connected via USB (as mine are, through the TerraMaster enclosure), the kernel assigns device names (`sda`, `sdb`, etc.) based on the order of enumeration at boot. A different boot order, a USB reset, or a drive removal and reinsertion can change which device is `sdb` and which is `sdc`.

If you use device names in your fstab or mount units, you'll occasionally mount `sdc` as `mercury` when it's actually `venus`. This is catastrophic for a storage pool.

**The fix: always use UUIDs.** My mount units use `What=UUID=...`, not `What=/dev/sdX`. The UUID is embedded in the filesystem, not the cable position. It doesn't change on reassignment.

---

## Adding SMART Monitoring with Scrutiny

`mergerfs` gives me a unified pool. Scrutiny gives me visibility into drive health.

In my Docker Compose stack:

```yaml
scrutiny:
  image: ghcr.io/analogj/scrutiny:master-omnibus
  container_name: scrutiny
  cap_add:
    - SYS_RAWIO
  ports:
    - "8082:8080"
  volumes:
    - /run/udev:/run/udev:ro
    - /home/kivan/appdata/scrutiny/config:/opt/scrutiny/config
    - /home/kivan/appdata/scrutiny/influxdb:/opt/scrutiny/influxdb
  # Device passthrough — USB drive letters may shift on reboot (order not guaranteed)
  # Verify with: lsblk
  # Current mapping (last verified 2026-04-29):
  # sda=WD 4TB backup-local, sdb1=Seagate 8TB mercury
  # sdc=Seagate 22TB jupiter, sdd=WD 16TB venus, sde=Seagate 16TB mars
  # nvme0n1=476GB OS (nvme stable, USB drives may shift)
  devices:
    - /dev/sda
    - /dev/sdb
    - /dev/sdc
    - /dev/sdd
    - /dev/sde
    - /dev/nvme0n1
```

Scrutiny runs SMART checks on a schedule and surfaces temperature, reallocated sectors, and pending uncorrectable errors in a dashboard. It's the early warning system for a drive that's starting to fail — crucial when you don't have RAID.

---

## Verifying the Pool

After everything is running:

```bash
# Confirm unified pool sees all branches
df -h /mnt/unified
# Filesystem        Size  Used Avail Use% Mounted on
# mergerfsPool      56T   22T   32T  41% /mnt/unified

# Confirm individual branches are mounted
df -h /mnt/mercury /mnt/venus /mnt/mars /mnt/jupiter

# Write a test file and verify it lands on a branch
touch /mnt/unified/test_file
ls /mnt/mercury/ /mnt/venus/ /mnt/mars/ /mnt/jupiter/ | grep test_file
```

The test file should appear in exactly one of the branch directories (whichever had the most free space at time of creation), and also be visible at `/mnt/unified/test_file`.

---

## Total Cost

| Component | Cost |
|---|---|
| Lenovo ThinkCentre M70q (used) | ~$200 |
| TerraMaster D6-320 enclosure | ~$150 |
| 4x drives (various) | existing |
| mergerfs | Free |
| Ubuntu 24.04 LTS | Free |

For the price of a mid-range NAS device (no drives), I have a full Linux server with 56TB of pooled storage, 70+ Docker containers, and complete control over every layer of the stack.

The tradeoff: no fancy GUI. Everything is configuration files and terminal commands. For me, that's a feature.

---

*The full systemd unit files and Docker Compose stack are in my `homelab-docs` repository. Raise an issue if you run into USB drive letter instability — it's the most common point of confusion.*
