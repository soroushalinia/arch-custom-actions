# arch-custom-actions

This repository hosts a GitHub Actions workflow that builds a complete Arch Linux CLI system image using Docker and `pacstrap`. The resulting image is archived into a Zstandard-compressed tarball (with metadata preserved) that you can later download, extract, and customize further. The primary goal is to provide a fast, prebuilt Arch Linux base that can be modified or used as a foundation for your custom variations—especially handy if your local system is too slow for lengthy builds.

## Workflow Overview

- **Building the System:**  
  The workflow runs in GitHub Actions on an Ubuntu runner. It uses a privileged Arch Linux Docker container to run `pacstrap` and install a full CLI system (including the kernel, firmware, and commonly used utilities such as `git`, `curl`, `nano`, etc.).

- **Exclusion of Unneeded Files:**  
  Certain directories (e.g., `/proc`, `/sys`, `/dev`) and volatile or host-specific files are excluded to ensure the tarball contains only the essential parts of the system.

- **Metadata Preservation:**  
  The tar command uses the options:
  - `--numeric-owner`: Keeps user/group IDs numeric (useful when transferring between systems).
  - `--xattrs`: Preserves extended attributes.
  - `--acls`: Preserves Access Control Lists (ACLs).  
    These options help maintain file permissions and metadata integrity.

## How to Use

1. **Trigger the Workflow:**  
   You can manually trigger the workflow via GitHub's "workflow_dispatch" interface.

2. **Download the Artifact:**  
   Once the workflow completes, download the artifact (the tarball) from the workflow run details.

3. **Extract the System:**  
   On your target machine or in your chroot environment, extract the tarball:

```bash
tar --zstd -xvf arch-custom-rootfs.tar.zst -C /your/target/directory
```

## Disclaimer

This project is provided as-is without any warranties. Always test in a safe environment before deploying to a production system.
