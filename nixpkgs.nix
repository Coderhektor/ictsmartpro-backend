let pkgs = import (fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/f9b3b9c91e0691f7c9e07e7f8a2c8c7a3b2e0878.tar.gz";
  sha256 = "1b3j7d0f3i2j6j9f2i1k3l4m5n6o7p8q9r0s1t2u3v4w5x6y7z8a9b0c1d2";
}) {}; in pkgs