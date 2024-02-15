variable "ubo_app_version" {
  type = string
}

variable "image_url" {
  type = string
}

variable "image_checksum" {
  type = string
}

variable "target_image_size" {
  type = number
  default = 0
}

source "arm-image" "raspberry_pi_os" {
  iso_url           = var.image_url
  iso_checksum      = var.image_checksum
  output_filename   = "/build/image.img"
  target_image_size = var.target_image_size
}

build {
  sources = ["source.arm-image.raspberry_pi_os"]

  provisioner "file" {
    source      = "ubo_app/system/install.sh"
    destination = "/install.sh"
  }

  provisioner "file" {
    source      = "/build/dist/ubo_app-${var.ubo_app_version}-py3-none-any.whl"
    destination = "/ubo_app-${var.ubo_app_version}-py3-none-any.whl"
  }

  provisioner "shell" {
    inline = [
      "chmod +x /install.sh",
      "/install.sh --for-packer --with-docker --source=/ubo_app-${var.ubo_app_version}-py3-none-any.whl",
      "rm /install.sh /ubo_app-${var.ubo_app_version}-py3-none-any.whl",
      "apt clean"
    ]
  }
}
