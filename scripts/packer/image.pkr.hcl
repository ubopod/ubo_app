variable "ubo_app_version" {
  type = string
}

variable "image_url" {
  type = string
}

variable "image_name" {
  type = string
}

variable "image_checksum_url" {
  type = string
}

variable "target_image_size" {
  type = string
}

packer {
  required_plugins {
    git = {
      version = ">=v0.3.2"
      source  = "github.com/ethanmdavidson/git"
    }
  }
}

source "arm" "raspios" {
  file_urls             = [var.image_url]
  file_checksum_url     = var.image_checksum_url
  file_checksum_type    = "sha256"
  file_target_extension = "xz"
  file_unarchive_cmd    = ["xz", "--decompress", "$ARCHIVE_PATH"]
  image_build_method    = "resize"
  image_path            = "image.img"
  image_size            = var.target_image_size
  image_type            = "dos"

  image_partitions {
    name         = "boot"
    type         = "c"
    start_sector = "8192"
    filesystem   = "fat"
    size         = "512MB"
    mountpoint   = "/boot/firmware"
  }
  image_partitions {
    name         = "root"
    type         = "83"
    start_sector = "1056768"
    filesystem   = "ext4"
    size         = "0"
    mountpoint   = "/"
  }

  image_chroot_env             = ["PATH=/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin"]
  qemu_binary_source_path      = "/usr/bin/qemu-aarch64-static"
  qemu_binary_destination_path = "/usr/bin/qemu-aarch64-static"
}

build {
  sources = ["source.arm.raspios"]

  provisioner "file" {
    source      = "ubo_app/system/scripts/install.sh"
    destination = "/install.sh"
  }

  provisioner "file" {
    source      = "/build/dist"
    destination = "/wheels"
  }

  provisioner "shell" {
    inline = [
      "chmod +x /install.sh",
      "echo \"${var.image_name}\" > /etc/ubo_base_image",
      "sed -i '/^#\\?autologin-user=/c\\autologin-user=ubo' /etc/lightdm/lightdm.conf || true",
      "rm -f /etc/xdg/autostart/piwiz.desktop",
      "/install.sh --in-packer --wheels-directory=/wheels --target-version=${var.ubo_app_version}",
      "rm -rf /install.sh /wheels/",
      "/usr/bin/env systemctl disable userconfig || true",
      "apt-get clean -y",
      "echo DF; df -h"
    ]
  }
}
