Title: Running Jellyfin on a Tesla: A Practical How-To
Date: 2026-05-13
Category: How-to
Tags: jellyfin, tesla, homelab, self-hosted, media-server, streaming, chromium
Slug: jellyfin-on-tesla-browser-how-to
Summary: Tesla's built-in browser is Chromium-based and runs Jellyfin's web client just fine. Here's the setup, the codec constraints, and the tricks for a good experience during Supercharger stops.

---

The Tesla browser is more capable than most people realize. It's Chromium-based — currently at version 140 — which means it can run most modern web apps without modification. Jellyfin's web client is one of them.

I've been running my own Jellyfin instance on Apollo (my home server) with remote access enabled for a while. Getting it to work in the Tesla browser was mostly a matter of understanding what the browser can and can't handle codec-wise, and a small trick for full-screen playback.

---

## Prerequisites

- A Jellyfin instance with **remote access enabled** and a public URL or port-forwarded IP
- An HTTPS URL (the Tesla browser will block mixed content)
- Your media library in H.264 (for direct play) or a server capable of transcoding

---

## Step 1: Ensure Remote Access is Configured

In Jellyfin admin settings:

**Dashboard → Networking:**
- "Allow remote connections to this server" → ✅ enabled
- Your external IP or domain should be listed under "Published server URIs"

If you're using a reverse proxy (Nginx Proxy Manager, Caddy), this is where you configure your public URL: `https://jellyfin.yourdomain.com`.

If you don't have a domain and reverse proxy, you can use a port-forwarded IP directly: `http://your-public-ip:8096`. Note that HTTP without TLS may have issues in the Tesla browser depending on firmware version. HTTPS is strongly recommended.

---

## Step 2: Open Jellyfin in the Tesla Browser

1. Go to **Entertainment** in the Tesla UI
2. Open the **Browser**
3. Navigate to your Jellyfin URL (e.g., `https://jellyfin.yourdomain.com`)
4. Log in with your Jellyfin credentials

The web client loads and functions like it does in any Chromium browser. Library browsing, search, user management — all work.

---

## Step 3: Full-Screen Playback

This is the main friction point. The Tesla browser doesn't expose a standard full-screen button, and the Jellyfin player's full-screen toggle doesn't work in the Tesla browser context.

The workaround, borrowed from Plex users: there's a URL redirect trick that causes the Tesla browser to enter a full-screen-like kiosk mode.

The pattern is to prepend a specific YouTube redirect URL before your target URL:

```
https://www.youtube.com/redirect?q=https://jellyfin.yourdomain.com
```

When the Tesla browser follows this redirect chain, it drops the browser chrome and enters a more immersive mode. The exact behavior has changed across firmware versions — as of recent firmware, this works for initial load; subsequent in-app navigation stays within the same session.

Save this URL as a Tesla browser bookmark for fast access.

---

## Codec Reality Check

Direct play (no transcoding) works best. The Tesla browser supports H.264 in MP4 and MKV containers natively. This covers most of a typical media library.

What requires transcoding:

| Codec | Tesla Browser | Action Required |
|---|---|---|
| H.264 | ✅ Direct play | None |
| HEVC / H.265 | ⚠️ Hit or miss | Enable transcoding |
| AV1 | ❌ No | Transcode to H.264 |
| VP9 | ⚠️ Partial | May work; test per file |
| AC3 / DTS audio | ⚠️ Varies | May need audio transcode |

If your Jellyfin server has a capable CPU (or an NVIDIA GPU with hardware transcoding enabled), let it transcode. The playback experience is smooth even when transcoding, as long as your internet connection is fast enough to stream the transcoded stream.

For Tesla Wi-Fi at a Supercharger (Tesla's own network), streaming quality depends on the charger's internet connection. LTE hotspot from your phone gives you more predictable bandwidth.

---

## Tips for a Good Experience

**Bookmark the URL.** The Tesla browser supports bookmarks. Save your Jellyfin URL (with the full-screen redirect trick if you're using it) as a bookmark so it's one tap from the browser home screen.

**Pre-load before plugging in.** If you know you'll be Supercharging, start a Jellyfin playlist on your phone and let it load while you drive. When you plug in and open the Tesla browser, you can switch to the browser playback from there.

**Set a Jellyfin profile for the Tesla.** In Jellyfin, you can create device-specific playback profiles that force transcoding for certain codecs. Under **Administration → Playback**, add a rule that transcodes HEVC to H.264 for "Browser" client type. This ensures files that would otherwise fail to play get transcoded automatically.

**Keep sessions alive.** Jellyfin sessions time out after inactivity. If you're parked and watching, the session shouldn't expire mid-movie, but if you pause for a long time, you may need to log back in. Set your session timeout in Jellyfin admin to something generous (e.g., 24 hours).

---

## Why Self-Hosted Media in the Tesla

The honest answer: it's mostly for Supercharger stops and road trips.

Tesla's built-in entertainment apps (Netflix, YouTube, Spotify) cover most use cases. But if you have a Jellyfin library — family videos, a specific show you're watching, content that isn't on any streaming service — having it accessible in the Tesla browser is genuinely useful.

It's also just satisfying. The Tesla browser is a surprisingly capable runtime for a car computer. Jellyfin running in it is a natural extension of the self-hosted media philosophy: your library, your server, your terms.

---

## Limitations

**No native app.** There's no Tesla App Store equivalent for Jellyfin. The browser is the only access path.

**No background audio.** If you switch away from the browser (to navigation, for example), playback stops. You can't use Jellyfin as a background music player the way you can with Spotify or TuneIn.

**Casting doesn't work.** You can't cast from your phone's Jellyfin app to the Tesla. The browser client is the only option.

**Screen auto-locks.** If the Tesla goes into energy saving mode, the browser session may need to be reloaded. This is more of an issue when the car is parked and not actively charging.

---

## The Setup in One Minute

1. Enable remote access in Jellyfin admin
2. Ensure HTTPS (reverse proxy with Let's Encrypt, or Cloudflare Tunnel)
3. Open `https://jellyfin.yourdomain.com` in Tesla browser
4. Log in
5. Use the YouTube redirect URL trick for full-screen
6. Bookmark it

That's the whole setup. No custom apps, no firmware modifications, no workarounds beyond the full-screen redirect. The web client just works.

---

*Running Jellyfin on Apollo with mergerfs pooled storage? See my [mergerfs storage pool post](/mergerfs-storage-pool-linux-without-nas.html) for the underlying storage architecture.*
