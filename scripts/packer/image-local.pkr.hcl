variable "ubo_app_version" {
  type = string
}

source "arm-image" "raspberry_pi_os" {
  iso_checksum = "8da22fe17b23523427a622ef3a8f2b64b98da0f11e9ea40cb4b6bec21cba5e3f"
  iso_url      = "images/2023-12-05-raspios-bookworm-arm64-full.img"
}

build {
  sources = ["source.arm-image.raspberry_pi_os"]

  provisioner "file" {
    source      = "ubo_app/system/install.sh"
    destination = "/install.sh"
  }

  provisioner "shell" {
    inline = [
      "chmod +x /install.sh",
      "/install.sh --in-packer --source /build/wheel/ubo_app-${var.ubo_app_version}-py3-none-any.whl",
      "rm /install.sh"
    ]
  }
}
