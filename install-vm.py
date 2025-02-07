#!/usr/bin/env python3
"""
WARNING: This script will wipe the target disk (by default /dev/sda) completely.
Ensure you are running it in a virtual machine (VMware/VirtualBox) under UEFI boot,
from an official Arch live ISO.  Run as root.

This script:
  1. Checks the environment (live ISO, UEFI, virtualization).
  2. Downloads the latest artifact (arch‑custom‑rootfs.tar.zst) from
     https://github.com/soroushalinia/arch-custom-actions via the GitHub API.
  3. Wipes and partitions /dev/sda with:
       • Partition 1: 2GB EFI (FAT32, ESP flag)
       • Partition 2: 8GB swap
       • Partition 3: rest as root (ext4)
  4. Mounts the new partitions and extracts the tarball into /mnt.
  5. Generates an fstab.
  6. Chroots into /mnt to configure the system:
       • Timezone set to Asia/Tehran
       • Locale set to en_US.UTF-8
       • Prompts for hostname, username, and passwords (root and user)
       • Installs systemd-boot and creates boot loader configuration.
"""

import os
import sys
import subprocess
import requests
import zipfile
import io
import getpass
import shutil


# ---------------------------------------------------------------------------
def run_cmd(cmd, check=True):
    """Run a shell command and print it."""
    print("Running:", cmd)
    subprocess.run(cmd, shell=True, check=check)


# ---------------------------------------------------------------------------
def check_environment():
    """Ensure the script is running in the expected live environment."""
    # Must be run as root
    if os.geteuid() != 0:
        print("This script must be run as root.")
        sys.exit(1)

    # Check for Arch live environment (example: /run/archiso exists)
    if not os.path.exists("/run/archiso"):
        print("This does not appear to be a live Arch environment. Exiting.")
        sys.exit(1)

    # Check for UEFI boot (EFI variables directory exists)
    if not os.path.exists("/sys/firmware/efi"):
        print("System is not booted in UEFI mode. Exiting.")
        sys.exit(1)

    # Check for virtualization (VMware or VirtualBox)
    product_name = ""
    try:
        with open("/sys/class/dmi/id/product_name", "r") as f:
            product_name = f.read().strip()
    except Exception:
        pass
    if not ("VirtualBox" in product_name or "VMware" in product_name):
        print(
            "System does not appear to be running inside VMware or VirtualBox. Exiting."
        )
        sys.exit(1)
    print("Environment check passed.")


# ---------------------------------------------------------------------------
def download_artifact():
    """
    Download the latest GitHub Actions artifact from the repository.
    The artifact is assumed to be named "arch-installation" and contain the file
    "arch-custom-rootfs.tar.zst". The downloaded zip is extracted and the tarball
    is returned.
    """
    repo_owner = "soroushalinia"
    repo_name = "arch-custom-actions"
    api_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/actions/artifacts"

    print("Fetching artifact list from GitHub API...")
    response = requests.get(api_url)
    if response.status_code != 200:
        print("Failed to fetch artifact list from GitHub API. Exiting.")
        sys.exit(1)
    data = response.json()
    artifacts = data.get("artifacts", [])
    if not artifacts:
        print("No artifacts found in repository. Exiting.")
        sys.exit(1)

    # Look for the artifact named "arch-installation"
    artifact = None
    for art in artifacts:
        if art.get("name") == "arch-installation":
            artifact = art
            break
    if artifact is None:
        print("Desired artifact not found. Exiting.")
        sys.exit(1)

    download_url = artifact.get("archive_download_url")
    if not download_url:
        print("Artifact download URL not found. Exiting.")
        sys.exit(1)

    print("Downloading artifact from GitHub...")
    artifact_response = requests.get(download_url)
    if artifact_response.status_code != 200:
        print("Failed to download artifact. Exiting.")
        sys.exit(1)

    zip_bytes = io.BytesIO(artifact_response.content)
    with zipfile.ZipFile(zip_bytes) as z:
        # The tarball may be inside a subfolder in the zip archive.
        expected_name = "arch-custom-rootfs.tar.zst"
        tarball_name = None
        for name in z.namelist():
            if name.endswith(expected_name):
                tarball_name = name
                break
        if not tarball_name:
            print("Tarball not found in artifact archive. Exiting.")
            sys.exit(1)

        print(f"Extracting {tarball_name} from artifact...")
        z.extract(tarball_name, path=".")
        # If the file was extracted into a subdirectory, move it to the current directory.
        extracted_path = tarball_name
        if os.path.dirname(tarball_name):
            base_name = os.path.basename(tarball_name)
            shutil.move(tarball_name, base_name)
            extracted_path = base_name

    print(f"Artifact extracted to: {extracted_path}")
    return extracted_path


# ---------------------------------------------------------------------------
def partition_disk(disk="/dev/sda"):
    """Wipe the disk and create partitions:
    Partition 1: EFI (2GB)
    Partition 2: Swap (8GB)
    Partition 3: Root (remaining space, ext4)
    """
    print(f"WARNING: This will wipe all data on {disk}.")
    input("Press Enter to continue or Ctrl+C to abort...")

    # Unmount any mounted partitions on the disk (ignore errors)
    run_cmd(f"umount {disk}* || true", check=False)

    # Wipe any existing partition table/data
    run_cmd(f"sgdisk --zap-all {disk}")
    run_cmd(f"wipefs -a {disk}")

    # Create a new GPT partition table and partitions using parted.
    run_cmd(f"parted --script {disk} mklabel gpt")
    # Partition 1: EFI partition from 1MiB to 2049MiB (~2GB)
    run_cmd(f"parted --script {disk} mkpart primary fat32 1MiB 2049MiB")
    run_cmd(f"parted --script {disk} set 1 esp on")
    # Partition 2: Swap partition from 2049MiB to 10241MiB (~8GB)
    run_cmd(f"parted --script {disk} mkpart primary linux-swap 2049MiB 10241MiB")
    # Partition 3: Root partition from 10241MiB to 100%
    run_cmd(f"parted --script {disk} mkpart primary ext4 10241MiB 100%")

    # Format the partitions:
    run_cmd(f"mkfs.fat -F32 {disk}1")
    run_cmd(f"mkswap {disk}2")
    run_cmd(f"mkfs.ext4 {disk}3")

    # Mount the new partitions
    run_cmd("mount {disk}3 /mnt".format(disk=disk))
    run_cmd("mkdir -p /mnt/boot")
    run_cmd("mount {disk}1 /mnt/boot".format(disk=disk))
    run_cmd("swapon {disk}2".format(disk=disk))


# ---------------------------------------------------------------------------
def extract_tarball(tarball, target="/mnt"):
    """Extract the downloaded tarball into the target mount point."""
    run_cmd(f"tar --zstd -xpf {tarball} -C {target}")


# ---------------------------------------------------------------------------
def generate_fstab(target="/mnt"):
    """Generate an fstab file and append it to /mnt/etc/fstab."""
    run_cmd(f"genfstab -U {target} >> {target}/etc/fstab")


# ---------------------------------------------------------------------------
def configure_chroot(mnt="/mnt"):
    """Chroot into the new system and perform further configuration."""
    # Ask for hostname, username, and passwords.
    hostname = input("Enter hostname for the system: ").strip()
    username = input("Enter username to create: ").strip()
    user_password = getpass.getpass("Enter password for the user: ").strip()
    root_password = getpass.getpass("Enter root password: ").strip()

    # Create a temporary chroot script.
    chroot_script = f"""#!/bin/bash
set -e

# Set hostname and hosts file.
echo "{hostname}" > /etc/hostname
cat <<EOF > /etc/hosts
127.0.0.1   localhost
::1         localhost
127.0.1.1   {hostname}.localdomain {hostname}
EOF

# Set timezone.
ln -sf /usr/share/zoneinfo/Asia/Tehran /etc/localtime
hwclock --systohc

# Set locale.
sed -i 's/^#en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen
locale-gen
echo "LANG=en_US.UTF-8" > /etc/locale.conf

# Set root password.
echo "root:{root_password}" | chpasswd

# Create the user with wheel group (for sudo) and zsh as shell.
useradd -m -G wheel -s /bin/zsh {username}
echo "{username}:{user_password}" | chpasswd

# Allow wheel group sudo privileges.
sed -i 's/^# %wheel ALL=(ALL) ALL/%wheel ALL=(ALL) ALL/' /etc/sudoers

# Install systemd-boot.
bootctl install

# Create loader configuration.
mkdir -p /boot/loader/entries
cat <<EOL > /boot/loader/loader.conf
default  arch
timeout  5
editor   no
EOL

# Create boot entry for Arch Linux.
# Adjust kernel names as needed.
KERNEL_IMG=$(ls /boot/vmlinuz-linux* | head -n 1)
INITRAMFS_IMG=$(ls /boot/initramfs-linux* | head -n 1)
if [ -z "$KERNEL_IMG" ] || [ -z "$INITRAMFS_IMG" ]; then
  echo "Kernel or initramfs not found in /boot. Exiting."
  exit 1
fi

# Determine PARTUUID for the root partition.
ROOT_PART=$(findmnt -n -o SOURCE /)
PARTUUID=$(blkid -s PARTUUID -o value $ROOT_PART)

cat <<EOL > /boot/loader/entries/arch.conf
title   Arch Linux
linux   /$(basename $KERNEL_IMG)
initrd  /$(basename $INITRAMFS_IMG)
options root=PARTUUID=$PARTUUID rw
EOL

exit
"""
    script_path = os.path.join(mnt, "tmp", "chroot_script.sh")
    os.makedirs(os.path.dirname(script_path), exist_ok=True)
    with open(script_path, "w") as f:
        f.write(chroot_script)
    run_cmd(f"chmod +x {script_path}")

    # Run the script inside chroot.
    run_cmd(f"arch-chroot {mnt} /tmp/chroot_script.sh")

    # Remove the temporary chroot script.
    run_cmd(f"rm {script_path}")


# ---------------------------------------------------------------------------
def main():
    check_environment()
    tarball = download_artifact()
    partition_disk("/dev/sda")
    extract_tarball(tarball, "/mnt")
    generate_fstab("/mnt")
    configure_chroot("/mnt")
    print("Installation complete. Please reboot.")


if __name__ == "__main__":
    main()
