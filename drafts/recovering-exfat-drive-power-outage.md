Title: How I Recovered a 16TB ExFAT Drive After a Power Outage (Without Losing a Single File)
Date: 2026-05-10
Category: How-to
Tags: linux, exfat, fsck, data-recovery, homelab, rsync, macos
Slug: recovering-exfat-drive-after-power-outage
Summary: A power outage mid-rsync left my 16TB ExFAT drive in a state macOS refused to mount. diskutil hung indefinitely. The fix was fsck.exfat on Linux — but getting there required understanding why ExFAT's dirty bit works the way it does, and why macOS is so unforgiving about it.

---

It started with a power outage at the worst possible moment: halfway through an rsync from a 16TB APFS source to an 8TB ExFAT Seagate, running via a Satechi Thunderbolt hub on my M1 MacBook Pro.

Power came back. I plugged in the drive. macOS refused to mount it.

Forty-eight hours later, after moving the drive to my Linux server, running `fsck.exfat`, and debugging a memory-exhaustion problem that was stalling the repair, I had every file back. This is the story of what happened and exactly how I fixed it.

---

## Why ExFAT + Power Loss = Disaster

ExFAT uses a "dirty bit" in the Volume Boot Record to track whether the filesystem was cleanly unmounted. When you plug in an ExFAT drive, the OS sets the dirty bit to indicate "I'm writing to this." When you safely eject, the OS clears it.

A power outage mid-write means the dirty bit stays set. On the next mount, the OS sees a dirty bit and knows the filesystem wasn't cleanly unmounted. The correct response is to repair the filesystem before mounting it.

macOS's response to a dirty ExFAT volume is to refuse to mount it and tell you to run Disk Utility. Disk Utility's `repairVolume` command then... hangs. Indefinitely. In the "Checking file system hierarchy" phase.

This isn't a bug exactly — it's macOS's ExFAT implementation being conservative to a fault. The `diskutil repairVolume` command on macOS will frequently hang on large ExFAT volumes with complex directory hierarchies. Hours in, I killed it and looked for another path.

---

## Moving the Drive to Linux

My Linux server (Apollo, a Lenovo ThinkCentre M70q running Ubuntu 24.04) became the recovery tool. The repair workflow:

```bash
# 1. Identify the drive
lsblk
# NAME        MAJ:MIN RM   SIZE RO TYPE MOUNTPOINTS
# sdf           8:80   0   7.5T  0 disk
# ├─sdf1        8:81   0   200M  0 part
# └─sdf2        8:82   0   7.5T  0 part

# 2. Install exfat tools if not present
sudo apt install exfatprogs

# 3. Run fsck on the data partition
sudo fsck.exfat -y /dev/sdf2
```

The `-y` flag answers "yes" to all repair prompts automatically. For a large drive (7.5TB with 4+ million files in my case), this is going to run for a while.

---

## The `fsck` Run: What to Expect

The `fsck.exfat` run on a large, heavily used volume has a distinctive pattern that looks alarming but is normal:

```
exfatprogs version : 1.2.2
/dev/sdf2: Examining FAT...
```

Then silence. Often for 10-20 minutes at a stretch.

This is CPU-bound logical verification — `fsck` is checking the File Allocation Table integrity without generating disk I/O. In `iostat`, you'll see the drive idle while CPU usage spikes on the `fsck` process. This is correct behavior.

What I actually observed via `iostat -x 5`:

```
Device  r/s   w/s   rMB/s  wMB/s  %util
sdf     2.1   0.0   0.13   0.00   8.2
sdf     0.0   0.0   0.00   0.00   0.0   <- silent period (CPU-bound)
sdf     0.0   0.0   0.00   0.00   0.0
sdf     1.8   0.0   0.11   0.00   6.4
```

The bursty read pattern alternating with silence is `fsck` doing small reads to verify metadata, then doing logical verification in memory.

---

## The Stall: qBittorrent Ate My RAM

Four hours into the fsck run, the process entered `D` state — uninterruptible sleep, waiting on disk I/O. It stopped making progress entirely.

The cause: `qbittorrent-nox` was consuming 21.8GB of RAM. Combined with active downloads on other drives competing for I/O, the system's swap was completely exhausted (8172MB/8192MB used). The kernel couldn't allocate memory for fsck's I/O buffers.

Fix:

```bash
# Kill the memory hogs
kill $(pgrep ffmpeg)           # Jellyfin transcoding
sudo pkill qbittorrent-nox     # 21GB RAM consumer

# Confirm swap freed up
free -h

# Check if fsck recovered
ps aux | grep fsck
```

After killing those processes, fsck exited D state and resumed within a minute. The lesson: `fsck` on a large drive is a resource-intensive operation. Plan it during a maintenance window with no competing I/O.

---

## The Result

```bash
sudo fsck.exfat -y /dev/sdf2
exfatprogs version : 1.2.2
/dev/sdf2: clean. directories 171914, files 4752208
```

`clean`. 171,914 directories. 4,752,208 files. Every single one intact.

Total repair time: approximately 6 hours, including the stall from the RAM issue. Without the memory contention, probably 2-3 hours for a volume this size.

---

## Mounting on macOS After Repair

After cleaning the dirty bit via Linux `fsck`, the drive mounts immediately on macOS — no Disk Utility intervention required.

```bash
# On Linux: unmount safely after fsck
# (Note: if fsck ran directly on the device without mounting, just unplug)
sudo umount /dev/sdf2  # Only if you mounted it; fsck doesn't mount
```

macOS sees a clean dirty bit, mounts the volume, and Finder shows it within a few seconds.

I tested with both the Satechi Thunderbolt hub and an Anker hub that I'd suspected might be causing issues. Both worked fine after the repair. The problem was never the hub — it was the dirty bit from the power outage.

---

## Resuming the rsync

After confirming the drive was clean and mounted, I resumed the rsync with `--append-verify` and `--update`:

```bash
rsync -avh --progress \
  --partial \
  --append-verify \
  --update \
  --exclude='media' \
  /Volumes/source_drive/ \
  /Volumes/seagate_8tb/
```

The key flags:

`--partial` — keeps partially transferred files rather than deleting them. Without this, any file that was mid-transfer during the outage would restart from zero.

`--append-verify` — resumes partially transferred files by appending from where they left off, then checksums the full file. More conservative than `--append` alone.

`--update` — skips files that are newer on the destination than the source. Prevents overwriting files that completed before the outage.

rsync picked up mid-file. A 43GB MKV that was in progress during the outage resumed at 43GB instead of restarting. Total catch-up time was several hours, not days.

---

## The Permanent Fix: Stop Using ExFAT for Large Transfer Drives

ExFAT was designed for flash storage and camera cards. It's cross-platform (Mac and Linux read it natively) and handles large files. But it has no journaling — there's no write-ahead log that allows crash recovery. The dirty bit is a blunt instrument: it tells you something went wrong, not what or how to fix it.

For large drives that I regularly rsync significant data to:

**APFS** (if Mac-only): Journaled, instant crash recovery, Copy-on-Write semantics. The right answer if the drive never needs to touch a Linux or Windows machine.

**exFAT** (if cross-platform required): Acceptable, but:
1. Use a UPS to eliminate the "power outage mid-write" scenario
2. Know that `fsck.exfat` on Linux is your recovery tool, not macOS Disk Utility
3. Plan for occasional dirty bit incidents on large drives

I now have a CyberPower UPS on the desk where this happened. The pure sine wave output protects the Thunderbolt docks. The dirty bit problem should not recur.

---

## Summary

| Step | Command | Notes |
|---|---|---|
| Identify drive | `lsblk` | Find the right device node |
| Install tools | `sudo apt install exfatprogs` | Linux only |
| Repair filesystem | `sudo fsck.exfat -y /dev/sdXN` | May take hours |
| Monitor progress | `iostat -x 5` | Bursty reads + silent CPU periods = normal |
| Kill memory hogs | `sudo pkill qbittorrent-nox` | If fsck enters D state |
| Unmount Linux | `sudo umount /dev/sdXN` | Only if you mounted it |
| Plug into Mac | — | Should mount immediately |
| Resume rsync | `rsync -avh --partial --append-verify --update` | Resumes mid-file |

The whole ordeal was recoverable. But it was also entirely preventable with a UPS and an understanding of how ExFAT's dirty bit works. Consider this your warning.

---

*This recovery was performed on Ubuntu 24.04 LTS with `exfatprogs 1.2.2`. The macOS behavior described applies to macOS Sequoia (15.x). Your mileage may vary on other versions.*
