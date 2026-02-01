my example personal setup Jan 2026:

homelab = raspberry pi (running Debian Linux)
storage = 1TB hardrive mounted in `/media/idohaber/storage/academic_library`

I have the .pdf devided by sub-dir based on the topic that got me to find them. Example: TI, iEEG, artifactRemoval...

I have the storage mounted on my macbook via Wireguard and sshfs so I can have an easy, contineuos, and secure access.

I have a cron daily schedular for 4am to extract data using grobID to the posgresql db.

commands to have handy:

```bash
idohaber|homelab (main) > sshfs -o uid=$(id -u),gid=$(id -g),reconnect,ServerAliveInterval=15,ServerAliveCountMax=3 \
      idohaber@10.200.200.1:/media/idohaber/storage/ ~/homelabk
```
